"""版4交流を用いる複数猫・1席の営業。従来の自動接客モードとは別に再生する。"""
import copy
import json
from dataclasses import asdict

from .simulation import SimulationCore, Command
from .human_cat_relationship import verify_relationship, identity
from .models import Cat


class CafeInteractionCore(SimulationCore):
    def __init__(self, *args, cat_ids=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.roster_ids = None if cat_ids is None else list(cat_ids)
        ids = self.roster_ids if self.roster_ids is not None else [self.cat.id]
        for cat_id in ids:
            identity(cat_id)
        if not ids or len(set(ids)) != len(ids):
            raise ValueError('営業する猫IDは重複のない1匹以上を指定してください。')
        self.cats = {cat_id: Cat(id=cat_id, stamina=self.start_state.stamina, spirit=self.start_state.spirit) for cat_id in ids}
        self.cat = self.cats[ids[0]]
        self.active = None
        self.outcomes = {}
        self.operations = []
        self.interaction_bonus = 0
        self.day_results = []
        self.day_outcome_offset = 0
        self.returning_customers = set()

    def snapshot(self):
        return {**super().snapshot(),
                'interaction': self.active.log() if self.active else None,
                **({'day_results': copy.deepcopy(self.day_results)} if self.day_results else {}),
                'outcomes': copy.deepcopy(self.outcomes), 'interaction_bonus': self.interaction_bonus,
                **({'cats': {key:asdict(cat) for key,cat in self.cats.items()}} if self.roster_ids is not None else {})}

    def _arrive(self):
        super()._arrive()
        for visit in self.visits.values():
            visit.first_visit = visit.id not in self.returning_customers

    def day_result(self):
        if not self.closed:
            raise ValueError('閉店後に結果を確認してください。')
        changes = {}
        for log in list(self.outcomes.values())[self.day_outcome_offset:]:
            result = verify_relationship(log).result()
            key = (result['cat_id'], result['customer_id'])
            changes[key] = changes.get(key, 0) + result['affinity_after'] - result['affinity_before']
        return dict(day=self.day, summary=self.summary(),
                    cats={key: dict(stamina=cat.stamina,
                         spent=(self.start_state.stamina if self.day == 1 else self.config.max_stamina)-cat.stamina)
                          for key,cat in self.cats.items()},
                    affinity_changes=[dict(cat_id=key[0], customer_id=key[1], change=value)
                                      for key,value in changes.items()])

    def next_day(self):
        if not self.closed or self.active or getattr(self, 'interactions', {}):
            raise ValueError('交流を終了して閉店してから翌日へ進んでください。')
        result = self.day_result()
        self.day_results.append(result)
        self.day_outcome_offset = len(self.outcomes)
        self.returning_customers.update(self.visits)
        self.visits = {}
        self.queue = []
        self.tick = 0
        self.day += 1
        self.closed = False
        self.service_ticks = 0
        self.spirit_spent = 0
        self.interaction_bonus = 0
        for cat in self.cats.values():
            cat.stamina = self.config.max_stamina
            if cat.health_status == 'healthy':
                cat.cannot_continue = False
        self._tick_events = []
        self._emit('next_day', day=self.day)
        self._record(dict(kind='next_day'))

    def _record(self, operation):
        self.operations.append(dict(operation=operation, events=copy.deepcopy(self._tick_events), state=self.snapshot()))

    def start(self, interaction):
        if self.closed or self.active or self.seat.customer_id is not None:
            raise ValueError('交流を開始できません。営業中の空席が必要です。')
        if interaction.cat_id not in self.cats or interaction.customer_id not in self.queue:
            raise ValueError('営業中の猫と待機中のお客を選んでください。')
        cat = self.cats[interaction.cat_id]
        if cat.health_status != 'healthy' or cat.cannot_continue or cat.stamina <= 0:
            raise ValueError('この猫は現在交流できません。')
        if (interaction.records or interaction.state['end_reason'] or
                interaction.state['stamina'] != cat.stamina or
                interaction.config.max_stamina != self.config.max_stamina or
                interaction.config.ticks > self.config.opening_ticks - self.tick or
                interaction.session_id in self.outcomes):
            raise ValueError('交流の開始条件が営業状態と一致しません。')
        self._tick_events = []
        self.cat = cat
        self._apply(Command('assign', interaction.customer_id, interaction.cat_id, self.seat.id))
        self.active = copy.deepcopy(interaction)
        self.visits[interaction.customer_id].first_meeting = interaction.initial_relationship['revision'] == 0
        self._emit('interaction_started', session_id=interaction.session_id, customer_id=interaction.customer_id)
        self._record(dict(kind='start', interaction=interaction.log()))

    def _interact(self, action_override):
        if self.active is None:
            return None
        action, target = action_override
        record = self.active.step(action, target)
        self.cat.stamina = self.active.state['stamina']
        visit = self.visits[self.active.customer_id]
        visit.seated_ticks += 1
        visit.actions_taken += 1
        self.service_ticks += 1
        self._emit('human_cat_action', session_id=self.active.session_id, record=record)
        if self.active.state['end_reason']:
            self._complete()
        return action_override

    def _complete(self):
        interaction = self.active
        result = interaction.result()
        reason = ('interaction_exhausted' if result['end_reason'] == 'exhausted' else
                  'closing' if result['end_reason'] == 'time_limit' and self.tick + 1 >= self.config.opening_ticks else
                  'interaction_' + result['end_reason'])
        visit = self.visits[interaction.customer_id]
        self._depart(visit, reason)
        # 旧営業の成功ボーナスは使わず、版4の成果を同じ会計へ加える。
        bonus = result['bonus_funds']
        visit.bill += bonus
        self.funds += bonus
        self.interaction_bonus += bonus
        self.events[-1].update(bonus=bonus, bill=visit.bill)
        self.outcomes[interaction.session_id] = interaction.log()
        self._emit('interaction_completed', session_id=interaction.session_id, result=result)
        if self.cat.stamina == 0:
            self.cat.cannot_continue = True
        self.active = None

    def step(self, action=None, target_type=None):
        if self.closed:
            raise RuntimeError('営業は終了しています')
        if self.active:
            # 無効操作で営業の来客・時計だけが進むことを防ぐ。
            copy.deepcopy(self.active).step(action, target_type)
        elif action is not None or target_type is not None:
            raise ValueError('先に待機中のお客との交流を開始してください。')
        super().step(cat_action=(action, target_type))
        self._record(dict(kind='step', action=action, target_type=target_type))
        return self.observation()

    def finish(self):
        if self.active is None:
            return  # 保存再試行や終了ボタンの連打では会計を繰り返さない。
        self._tick_events = []
        self.active.finish()
        self._complete()
        self._record(dict(kind='finish'))

    def summary(self):
        visits = list(self.visits.values())
        return dict(ticks=self.tick, closed=self.closed, arrivals=len(visits),
                    completed_interactions=len(self.outcomes)-self.day_outcome_offset,
                    departures={reason:sum(v.departure_reason == reason for v in visits)
                                for reason in sorted({v.departure_reason for v in visits if v.departure_reason})},
                    revenue=sum(v.bill for v in visits), funds=self.funds,
                    interaction_bonus=self.interaction_bonus, stamina=self.cat.stamina,
                    service_ticks=self.service_ticks,
                    **({'cat_stamina': {key:cat.stamina for key,cat in self.cats.items()}} if self.roster_ids is not None else {}))

    def log(self):
        return dict(mode_id='cafe-human-cat', format_version=2 if self.roster_ids is not None else 1, config=json.loads(json.dumps(self.config.to_dict())),
                    seed=self.seed, start_state=asdict(self.start_state),
                    operations=copy.deepcopy(self.operations), summary=self.summary(),
                    **({'cat_ids': list(self.roster_ids)} if self.roster_ids is not None else {}))


def verify_cafe_interaction(data):
    from .config import Config
    from .models import StartState
    if data.get('mode_id') == 'cafe-human-cat' and data.get('format_version') == 3:
        from .multi_seat_cafe import verify_multi_seat
        return verify_multi_seat(data)
    if data.get('mode_id') != 'cafe-human-cat' or data.get('format_version') not in (1, 2):
        raise ValueError('unsupported cafe interaction log')
    core = CafeInteractionCore(Config.from_dict(data['config']), seed=data['seed'],
                               start_state=StartState(**data['start_state']),
                               cat_ids=data['cat_ids'] if data['format_version'] == 2 else None)
    for item in data['operations']:
        operation = item['operation']
        if operation['kind'] == 'start':
            core.start(verify_relationship(operation['interaction']))
        elif operation['kind'] == 'step':
            core.step(operation['action'], operation['target_type'])
        elif operation['kind'] == 'next_day':
            core.next_day()
        elif operation['kind'] == 'finish':
            core.finish()
        else:
            raise ValueError('unknown cafe operation')
        if core.operations[-1] != item:
            raise ValueError('cafe replay mismatch')
    if core.log() != data:
        raise ValueError('cafe replay metadata or summary mismatch')
    return core
