"""2席の交流を同じ営業時計で進める。旧営業ログは従来coreで再生する。"""
import copy
from dataclasses import asdict

from .cafe_interaction import CafeInteractionCore
from .models import Seat, StartState
from .config import Config
from .human_cat_relationship import verify_relationship


class MultiSeatCafeCore(CafeInteractionCore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seats = {key:Seat(id=key) for key in ('seat-1','seat-2')}
        self.interactions = {}
        self._suppress_record = False
        self._sync()

    def _sync(self):
        key = next(iter(self.interactions), 'seat-1')
        self.seat = self.seats[key]
        self.active = self.interactions.get(key)
        if self.active:
            self.cat = self.cats[self.active.cat_id]

    def _full_snapshot(self):
        state = super()._full_snapshot()
        for key in ('interaction','seat','cat'):
            state.pop(key, None)
        state.update(seats={key:asdict(seat) for key,seat in self.seats.items()},
                     interactions={key:interaction.log() for key,interaction in self.interactions.items()},
                     cats={key:asdict(cat) for key,cat in self.cats.items()})
        return state

    def _record(self, operation):
        if not self._suppress_record:
            super()._record(operation)

    def _emit(self, kind, **data):
        if kind in ('assigned','interaction_started','human_cat_action','interaction_completed'):
            data['seat_id'] = self.seat.id
        elif kind=='departure' and self.visits[data['customer_id']].seated_at is not None:
            data['seat_id'] = self.seat.id
        super()._emit(kind, **data)

    def start(self, interaction, seat_id=None):
        seat_id = seat_id or next((key for key in self.seats if key not in self.interactions), None)
        if seat_id not in self.seats or seat_id in self.interactions:
            raise ValueError('空いている席を選んでください。')
        if any(item.cat_id==interaction.cat_id or item.session_id==interaction.session_id for item in self.interactions.values()):
            raise ValueError('この猫は別の席で交流中です。')
        self.seat = self.seats[seat_id]
        self.active = None
        self._suppress_record = True
        try:
            super().start(interaction)
            self.interactions[seat_id] = self.active
        finally:
            self._suppress_record = False
            self._sync()
        self._record(dict(kind='start',seat_id=seat_id,interaction=interaction.log()))

    def _complete(self):
        seat_id=self.seat.id
        super()._complete()
        del self.interactions[seat_id]

    def step(self, commands=None):
        if self.closed:
            raise RuntimeError('営業は終了しています')
        commands = {} if commands is None else commands
        if not isinstance(commands,dict) or set(commands)!=set(self.interactions):
            raise ValueError('交流中の各席に1つずつ行動が必要です。')
        # どの席の無効入力でも、全席と営業時計を変更しない。
        for seat_id,interaction in self.interactions.items():
            command=commands[seat_id]
            if not isinstance(command,(tuple,list)) or len(command)!=2:
                raise ValueError('行動と変更先を指定してください。')
            copy.deepcopy(interaction).step(*command)
        self._tick_events=[]
        self._arrive()
        for seat_id in sorted(self.interactions):
            self.seat=self.seats[seat_id]
            self.active=self.interactions[seat_id]
            self.cat=self.cats[self.active.cat_id]
            self._interact(commands[seat_id])
        for customer_id in list(self.queue):
            visit=self.visits[customer_id]
            if self.tick-visit.arrival_tick+1 >= self.config.max_wait_ticks:
                self._depart(visit,'wait_timeout')
        if self.tick+1 >= self.config.opening_ticks:
            for visit in self.visits.values():
                if visit.departure_reason is None:
                    self._depart(visit,'closing')
            self.closed=True
            self._emit('closed',revenue=self.funds-self.config.initial_funds)
        self.tick+=1
        self._sync()
        self._record(dict(kind='step',commands={key:list(value) for key,value in commands.items()}))
        return self.snapshot()

    def finish(self, seat_id=None):
        if seat_id is None:
            for key in list(self.interactions):
                self.finish(key)
            return
        if seat_id not in self.seats:
            raise ValueError('不明な席です。')
        if seat_id not in self.interactions:
            return
        self._tick_events=[]
        self.seat=self.seats[seat_id]
        self.active=self.interactions[seat_id]
        self.cat=self.cats[self.active.cat_id]
        self.active.finish()
        self._complete()
        self._sync()
        self._record(dict(kind='finish',seat_id=seat_id))

    def summary(self):
        result=super().summary()
        result.pop('stamina',None)
        result['cat_stamina']={key:cat.stamina for key,cat in self.cats.items()}
        result['seat_count']=2
        return result

    def log(self):
        if self.compact:
            return super().log()
        return {**super().log(),'format_version':3,'cat_ids':list(self.cats),'seat_ids':list(self.seats)}


def verify_multi_seat(data):
    if data.get('seat_ids') != ['seat-1','seat-2']:
        raise ValueError('unsupported seats')
    core=MultiSeatCafeCore(Config.from_dict(data['config']),seed=data['seed'],
                           start_state=StartState(**data['start_state']),cat_ids=data['cat_ids'])
    for item in data['operations']:
        operation=item['operation']
        if operation['kind']=='enable_health':
            core.enable_health(operation['rules'])
        elif operation['kind']=='set_shifts':
            core.set_shifts(operation['working_cats'],operation['rules'])
        elif operation['kind']=='start':
            core.start(verify_relationship(operation['interaction']),operation['seat_id'])
        elif operation['kind']=='step':
            core.step(operation['commands'])
        elif operation['kind']=='day_off':
            core.day_off()
        elif operation['kind']=='next_day':
            core.next_day()
        elif operation['kind']=='finish':
            core.finish(operation['seat_id'])
        else:
            raise ValueError('unknown cafe operation')
        if not core.operations or core.operations[-1]!=item:
            raise ValueError('multi-seat replay mismatch')
    if core.log()!=data:
        raise ValueError('multi-seat replay metadata or summary mismatch')
    return core
