"""営業の現在状態。操作履歴を含めず、終了成果は照合用の受領記録にする。"""
import copy
import hashlib
import json
import math
from dataclasses import asdict

from .models import Cat, Seat, StartState, Visit
from .config import Config
from .human_cat_relationship import identity, verify_relationship


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def is_receipt(value):
    return value.get('kind') == 'cafe-outcome-receipt'


def receipt(value):
    if is_receipt(value):
        return copy.deepcopy(value)
    return dict(kind='cafe-outcome-receipt', digest=digest(value),
                initial_relationship=copy.deepcopy(value['initial_relationship']),
                result=copy.deepcopy(value['summary']))


def outcome_result(value):
    return value['result'] if is_receipt(value) else value['summary']


def snapshot(core):
    state = core._full_snapshot()
    state['outcomes'] = {key: receipt(value) for key, value in core.outcomes.items()}
    counts = {}
    day = 1
    for event in core.events:
        if event['kind'] == 'next_day':
            day = event['day']
        elif event['kind'] == 'interaction_completed':
            key = (day, event['result']['cat_id'])
            counts[key] = counts.get(key, 0) + 1
    for result in state.get('day_results', []):
        for cat_id, cat in result['cats'].items():
            cat.setdefault('interactions', counts.get((result['day'], cat_id), 0))
    return state


def record_digest(core):
    return digest(dict(state=snapshot(core), config=core.config.to_dict(), seed=core.seed,
                       start_state=asdict(core.start_state), cat_ids=core.roster_ids,
                       cat_id=core.cat.id, returning_customers=sorted(core.returning_customers),
                       day_outcome_offset=core.day_outcome_offset))


def assert_recorded(core):
    if core.compact and core.recorded_digest is not None:
        if record_digest(core) != core.recorded_digest:
            raise ValueError('営業状態と記録が一致しないため保存できません。')
    elif core.operations:
        if core.operations[-1]['state'] != core.snapshot():
            raise ValueError('営業状態と記録が一致しないため保存できません。')
    else:
        from .cafe_interaction import CafeInteractionCore
        from .multi_seat_cafe import MultiSeatCafeCore
        cls = MultiSeatCafeCore if hasattr(core, 'seats') else CafeInteractionCore
        initial = cls(core.config, seed=core.seed, start_state=core.start_state, cat_ids=core.roster_ids)
        if initial.snapshot() != core.snapshot():
            raise ValueError('初期状態と一致しないため保存できません。')


def checkpoint(core, pending):
    assert_recorded(core)
    start = next((i for i in range(len(core.events)-1, -1, -1)
                  if core.events[i]['kind'] == 'next_day'), 0)
    data = dict(kind='cafe-checkpoint', version=1, config=json.loads(json.dumps(core.config.to_dict())),
                seed=core.seed, start_state=asdict(core.start_state), cat_ids=core.roster_ids,
                seat_count=2 if hasattr(core, 'seats') else 1, state=snapshot(core), summary=core.summary(),
                resume=dict(cat_id=core.cat.id, returning_customers=sorted(core.returning_customers),
                            day_outcome_offset=core.day_outcome_offset,
                            events=copy.deepcopy([event for event in core.events[start:] if event['kind']!='human_cat_action']),
                            pending={key:copy.deepcopy(core.outcomes[key]) for key in pending}))
    return dict(data, digest=digest(data))


def restore(data):
    from .cafe_interaction import CafeInteractionCore
    from .multi_seat_cafe import MultiSeatCafeCore
    from .cafe_shifts import ShiftRules
    from .cafe_health import HealthRules
    fields={'kind','version','config','seed','start_state','cat_ids','seat_count','state','summary','resume','digest'}
    if (not isinstance(data,dict) or set(data)!=fields or data['kind']!='cafe-checkpoint'
            or type(data['version']) is not int or data['version']!=1
            or type(data['seat_count']) is not int or data['seat_count'] not in (1,2)
            or digest({k:v for k,v in data.items() if k!='digest'})!=data['digest']):
        raise ValueError('営業セーブの現在状態が破損しています。')
    cls=MultiSeatCafeCore if data['seat_count']==2 else CafeInteractionCore
    core=cls(Config.from_dict(data['config']),seed=data['seed'],start_state=StartState(**data['start_state']),
             cat_ids=data['cat_ids'],compact=True)
    state, resume=data['state'],data['resume']
    if set(resume)!={'cat_id','returning_customers','day_outcome_offset','events','pending'}:
        raise ValueError('invalid resume fields')
    cats=state.get('cats',{state.get('cat',{}).get('id'):state.get('cat')})
    if set(cats)!=set(core.cats):
        raise ValueError('invalid cat roster')
    for key, value in cats.items():
        cat=Cat(**value)
        if cat.id!=key or cat.health_status not in ('healthy','sick') or type(cat.cannot_continue) is not bool:
            raise ValueError('invalid cat state')
        for number, maximum in ((cat.stamina,core.config.max_stamina),(cat.spirit,core.config.max_spirit),(cat.fatigue,float('inf'))):
            if type(number) not in (int,float) or not math.isfinite(number) or not 0<=number<=maximum:
                raise ValueError('invalid cat resources')
        if type(cat.recovery_days_remaining) is not int or cat.recovery_days_remaining<0:
            raise ValueError('invalid recovery days')
        core.cats[key]=cat
    core.cat=core.cats[resume['cat_id']]
    for name in ('day','tick','funds','closed','spirit_spent','service_ticks','interaction_bonus'):
        setattr(core,name,state[name])
    if (type(core.day) is not int or core.day<1 or type(core.tick) is not int
            or not 0<=core.tick<=core.config.opening_ticks or type(core.closed) is not bool
            or core.closed!=(core.tick==core.config.opening_ticks)):
        raise ValueError('invalid business clock')
    for value in (core.funds,core.spirit_spent,core.service_ticks,core.interaction_bonus):
        if type(value) not in (int,float) or not math.isfinite(value) or value<0:
            raise ValueError('invalid business totals')
    core.queue=copy.deepcopy(state['queue'])
    core.visits={row['id']:Visit(**row) for row in state['visits']}
    if (len(core.visits)!=len(state['visits']) or len(set(core.queue))!=len(core.queue)
            or not set(core.queue)<=set(core.visits)):
        raise ValueError('invalid visits or queue')
    core.outcomes=copy.deepcopy(state['outcomes'])
    for key,value in core.outcomes.items():
        identity(key)
        if (not is_receipt(value) or set(value)!={'kind','digest','initial_relationship','result'}
                or value['result']['session_id']!=key or value['initial_relationship']['session_id']!=key
                or not isinstance(value['digest'],str) or len(value['digest'])!=64):
            raise ValueError('invalid outcome receipt')
    for key,log in resume['pending'].items():
        completed=verify_relationship(log)
        completed.result()
        if key not in core.outcomes or receipt(log)!=core.outcomes[key]:
            raise ValueError('invalid pending outcome')
        core.outcomes[key]=copy.deepcopy(log)
    core.day_results=copy.deepcopy(state.get('day_results',[]))
    if len(core.day_results)!=core.day-1 or any(r['day']!=i+1 for i,r in enumerate(core.day_results)):
        raise ValueError('invalid day results')
    core.day_outcome_offset=resume['day_outcome_offset']
    if type(core.day_outcome_offset) is not int or not 0<=core.day_outcome_offset<=len(core.outcomes):
        raise ValueError('invalid outcome offset')
    core.returning_customers=set(resume['returning_customers'])
    for key in core.returning_customers:identity(key)
    core.events=copy.deepcopy(resume['events'])
    if 'shifts' in state:
        shifts=state['shifts']
        core.shift_rules=ShiftRules(**shifts['rules'])
        core.working_cats=set(shifts['working_cats'])
        core.cat_service_ticks=copy.deepcopy(shifts['service_ticks'])
        core.initial_fatigue=copy.deepcopy(shifts['initial_fatigue'])
        if (not core.working_cats<=set(core.cats) or set(core.cat_service_ticks)!=set(core.cats)
                or set(core.initial_fatigue)!=set(core.cats)):
            raise ValueError('invalid shifts')
    if 'health' in state:
        health=state['health']
        core.health_rules=HealthRules(**health['rules'])
        core.initial_health=copy.deepcopy(health['initial'])
        core.health_results=copy.deepcopy(health['results'])
        if not core.shift_rules or set(core.initial_health)!=set(core.cats):
            raise ValueError('invalid health state')
    if 'activities' in state:
        from .cafe_activities import validate
        core.activities=validate(core,state['activities'])
    if 'adoption' in state:
        from .cafe_adoption import validate as validate_adoption
        core.adoption=validate_adoption(core,state['adoption'])
    if 'player_bond' in state:
        from .cafe_player import validate as validate_player
        core.player_bond=validate_player(core,state['player_bond'])
        from .cafe_player import active as player_active
        from .cafe_adoption import waiting as adoption_waiting
        if player_active(core) and adoption_waiting(core):
            raise ValueError('プレイヤー交流と未解決の譲渡が同時に進行しています。')
    if data['seat_count']==2:
        core.seats={key:Seat(**row) for key,row in state['seats'].items()}
        if set(core.seats)!={'seat-1','seat-2'}:
            raise ValueError('invalid seats')
        core.interactions={key:verify_relationship(log) for key,log in state['interactions'].items()}
        core._sync()
        active=core.interactions
        seats=core.seats
    else:
        core.seat=Seat(**state['seat'])
        core.active=verify_relationship(state['interaction']) if state['interaction'] else None
        active={core.seat.id:core.active} if core.active else {}
        seats={core.seat.id:core.seat}
    busy_cats,busy_guests=set(),set()
    for key,seat in seats.items():
        if seat.id!=key:
            raise ValueError('invalid seat identity')
        if key not in active:
            if seat.customer_id is not None or seat.cat_id is not None:
                raise ValueError('occupied seat without interaction')
            continue
        interaction=active[key]
        cat=core.cats[interaction.cat_id]
        if (interaction.state['end_reason'] or core.closed or interaction.cat_id in busy_cats
                or interaction.customer_id in busy_guests or interaction.customer_id in core.queue
                or interaction.customer_id not in core.visits or interaction.session_id in core.outcomes
                or cat.stamina!=interaction.state['stamina'] or seat.cat_id!=cat.id
                or seat.customer_id!=interaction.customer_id or cat.health_status!='healthy'
                or cat.id not in core.working_cats or cat.cannot_continue or core.activity(cat.id)!='cafe'):
            raise ValueError('invalid active interaction')
        busy_cats.add(cat.id);busy_guests.add(interaction.customer_id)
    if not set(active)<=set(seats) or snapshot(core)!=state or core.summary()!=data['summary']:
        raise ValueError('営業セーブの状態と集計が一致しません。')
    expected_funds = core.config.initial_funds + sum(row['summary']['revenue'] for row in core.day_results) + sum(v.bill for v in core.visits.values())
    from .cafe_activities import income
    expected_funds += income(core)
    if not math.isclose(core.funds,expected_funds,rel_tol=1e-12,abs_tol=1e-8):
        raise ValueError('会計の合計と所持金が一致しません。')
    core.recorded_digest=record_digest(core)
    core.replay_base=copy.deepcopy(data)
    return core
