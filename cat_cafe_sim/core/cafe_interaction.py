"""版4交流を用いる複数猫・1席の営業。従来の自動接客モードとは別に再生する。"""
import copy
import json
from dataclasses import asdict

from .simulation import SimulationCore, Command
from .human_cat_relationship import verify_relationship, identity
from .models import Cat


class CafeInteractionCore(SimulationCore):
    def __init__(self, *args, cat_ids=None, compact=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.compact = compact
        self.recorded_digest = None
        self.replay_base = None
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
        self.weekdays = None
        self.player_bond = None
        self.management = None
        self.goal = None
        self.patron = None
        self.bond_goal = None
        self.expansion = None
        self.rest_space = None
        self.traits = None
        self.cat_features = None
        self.customer_preferences = None
        self.recruitment = None
        self.adoption = None
        self.activities = None
        self.health_rules = None
        self.initial_health = {}
        self.health_results = {}
        self.shift_rules = None
        self.working_cats = set(ids)
        self.cat_service_ticks = dict.fromkeys(ids, 0)
        self.initial_fatigue = dict.fromkeys(ids, 0)

    def snapshot(self):
        if self.compact:
            from .cafe_checkpoint import snapshot
            return snapshot(self)
        return self._full_snapshot()

    def _full_snapshot(self):
        return {**super().snapshot(),
                'interaction': self.active.log() if self.active else None,
                **({'weekdays': copy.deepcopy(self.weekdays)} if self.weekdays is not None else {}),
                **({'shifts': self.shift_state()} if self.shift_rules else {}),
                **({'health': dict(rules=asdict(self.health_rules), initial=copy.deepcopy(self.initial_health),
                                  results=copy.deepcopy(self.health_results))} if self.health_rules else {}),
                **({'day_results': copy.deepcopy(self.day_results)} if self.day_results else {}),
                **({'player_bond': copy.deepcopy(self.player_bond)} if self.player_bond is not None else {}),
                **({'cat_features': copy.deepcopy(self.cat_features)} if self.cat_features is not None else {}),
                **({'customer_preferences': copy.deepcopy(self.customer_preferences)} if self.customer_preferences is not None else {}),
                **({'rest_space': copy.deepcopy(self.rest_space)} if self.rest_space is not None else {}),
                **({'expansion': copy.deepcopy(self.expansion)} if self.expansion is not None else {}),
                **({'traits': copy.deepcopy(self.traits)} if self.traits is not None else {}),
                **({'patron': copy.deepcopy(self.patron)} if self.patron is not None else {}),
                **({'bond_goal': copy.deepcopy(self.bond_goal)} if self.bond_goal is not None else {}),
                **({'goal': copy.deepcopy(self.goal)} if self.goal is not None else {}),
                **({'management': copy.deepcopy(self.management)} if self.management is not None else {}),
                **({'recruitment': copy.deepcopy(self.recruitment)} if self.recruitment is not None else {}),
                **({'adoption': copy.deepcopy(self.adoption)} if self.adoption is not None else {}),
                **({'activities': copy.deepcopy(self.activities)} if self.activities is not None else {}),
                'outcomes': copy.deepcopy(self.outcomes), 'interaction_bonus': self.interaction_bonus,
                **({'cats': {key:asdict(cat) for key,cat in self.cats.items()}} if self.roster_ids is not None or self.recruitment is not None else {})}

    def open_recruitment(self, candidates):
        from .cafe_recruitment import open_candidates
        open_candidates(self, candidates)

    def recruit_cat(self, cat_id):
        from .cafe_recruitment import accept
        accept(self, cat_id)

    def play_with_player(self, cat_id, config):
        from .cafe_player import begin
        begin(self, cat_id, config)

    def player_command(self, action=None, target_type=None, *, finish=False):
        from .cafe_player import advance
        advance(self, action, target_type, finish=finish)

    def require_running(self):
        from .cafe_management import require_running
        require_running(self)

    def purchase_rest_space(self, rules=None):
        from .cafe_equipment import purchase
        purchase(self, rules)

    def expand_seats(self, rules=None):
        from .cafe_expansion import purchase
        purchase(self, rules)

    def initialize_preferences(self, cats, rules=None):
        from .cafe_preferences import initialize
        initialize(self, cats, rules)

    def initialize_traits(self, traits):
        from .cafe_traits import initialize
        initialize(self, traits)

    def enable_bond_goal(self, rules=None):
        from .cafe_bond_goal import enable
        enable(self, rules)

    def continue_bond_goal(self):
        from .cafe_bond_goal import continue_game
        continue_game(self)

    def enable_patron(self, rules=None):
        from .cafe_patron import enable
        enable(self, rules)

    def continue_patron(self):
        from .cafe_patron import continue_game
        continue_game(self)

    def enable_goal(self, rules=None):
        from .cafe_goal import enable
        enable(self, rules)

    def continue_goal(self):
        from .cafe_goal import continue_game
        continue_game(self)

    def enable_management(self, rules=None):
        from .cafe_management import enable
        enable(self, rules)

    def resolve_missing(self, event_id):
        from .cafe_management import resolve
        resolve(self, event_id)

    def configure_adoption(self, enabled):
        from .cafe_adoption import configure
        configure(self, enabled)

    def resolve_adoption(self, event_id, choice):
        from .cafe_adoption import resolve
        resolve(self, event_id, choice)

    def activity(self, cat_id):
        from .cafe_activities import activity
        return activity(self, cat_id)

    def dispatch(self, cat_id, rules=None):
        from .cafe_activities import dispatch
        dispatch(self, cat_id, rules)

    def resolve_activity(self, event_id, choice='receive'):
        from .cafe_activities import resolve
        resolve(self, event_id, choice)

    def require_events_resolved(self):
        self.require_running()
        from .cafe_bond_goal import pending as bond_pending
        if bond_pending(self):
            raise ValueError("好感度目標の結果を確認して継続営業を選んでください。")
        from .cafe_patron import pending as patron_pending
        if patron_pending(self):
            raise ValueError('派遣・イベントの「有力者目標・結果…」で継続営業を選んでください。')
        from .cafe_goal import pending
        if pending(self):
            raise ValueError('目標画面で結果を確認し、継続営業を選んでください。')
        from .cafe_player import active
        if active(self):
            raise ValueError('進行中のプレイヤー交流を終了してください。')
        from .cafe_activities import waiting_events
        if waiting_events(self):
            raise ValueError('派遣・イベント画面で帰還結果や譲渡・家出イベントを確認してください。')

    @property
    def can_set_shifts(self):
        return not self.closed and self.tick == 0 and not self.visits and not self.active

    def shift_state(self):
        return dict(rules=asdict(self.shift_rules), working_cats=sorted(self.working_cats),
                    service_ticks=dict(self.cat_service_ticks), initial_fatigue=dict(self.initial_fatigue))

    def set_shifts(self, working_cats, rules=None):
        from .cafe_shifts import ShiftRules
        self.require_events_resolved()
        if not self.can_set_shifts:
            raise ValueError('出勤・休養は営業開始前に設定してください。')
        if (not isinstance(working_cats, list) or any(not isinstance(key, str) for key in working_cats)
                or len(set(working_cats)) != len(working_cats) or not set(working_cats) <= set(self.cats)):
            raise ValueError('営業に参加している猫を重複なく指定してください。')
        if any(self.activity(key) != 'cafe' for key in working_cats):
            raise ValueError('在店している猫だけ出勤できます。')
        if any(self.cats[key].health_status != 'healthy' for key in working_cats):
            raise ValueError('療養中の猫は出勤できません。')
        selected_rules = ShiftRules(**rules) if rules is not None else self.shift_rules or ShiftRules.load()
        if self.shift_rules and selected_rules != self.shift_rules:
            raise ValueError('営業途中の履歴では疲労ルールを変更できません。')
        if not self.shift_rules:
            self.initial_fatigue = {key: cat.fatigue for key, cat in self.cats.items()}
        self.shift_rules = selected_rules
        self.working_cats = set(working_cats)
        self._tick_events = []
        self._emit('shifts_set', working_cats=sorted(self.working_cats))
        self._record(dict(kind='set_shifts', working_cats=sorted(self.working_cats), rules=asdict(selected_rules)))

    def enable_health(self, rules):
        from .cafe_health import HealthRules
        if not self.can_set_shifts or not self.shift_rules or self.health_rules:
            raise ValueError('病気ルールは出勤設定後の営業準備中に1回だけ有効にできます。')
        selected = HealthRules(**rules)
        self.health_rules = selected
        self.initial_health = self._health_state()
        self._tick_events = []
        self._emit('health_enabled')
        self._record(dict(kind='enable_health', rules=asdict(selected)))

    def _health_state(self):
        return {key: dict(status=cat.health_status, remaining=cat.recovery_days_remaining)
                for key, cat in self.cats.items()}

    def _settle_health(self):
        from .cafe_health import health_draw
        for key, cat in self.cats.items():
            initial = self.initial_health[key]
            chance, draw = None, None
            if self.activity(key) != 'cafe':
                outcome = 'healthy' if initial['status']=='healthy' else 'recovering'
            elif initial['status'] == 'sick':
                cat.recovery_days_remaining = max(0, initial['remaining'] - 1)
                cat.health_status = 'sick' if cat.recovery_days_remaining else 'healthy'
                outcome = 'recovering' if cat.recovery_days_remaining else 'recovered'
            else:
                chance = self.health_rules.probability(cat.fatigue)
                draw = health_draw(self.seed, self.day, key)
                sick = draw < chance
                cat.health_status = 'sick' if sick else 'healthy'
                cat.recovery_days_remaining = self.health_rules.recovery_days if sick else 0
                outcome = 'sick' if sick else 'healthy'
            if cat.health_status == 'sick':
                cat.cannot_continue = True
            result = dict(before=initial['status'], after=cat.health_status,
                          remaining_before=initial['remaining'], remaining_after=cat.recovery_days_remaining,
                          outcome=outcome, probability=chance, draw=draw)
            self.health_results[key] = result
            self._emit('cat_health', cat_id=key, **result)

    def _emit(self, kind, **data):
        if kind == 'closed' and self.shift_rules:
            for key, cat in self.cats.items():
                if self.activity(key) != 'cafe':
                    continue
                from .cafe_traits import fatigue_change
                change = fatigue_change(self, key, key in self.working_cats, self.cat_service_ticks[key])
                cat.fatigue = max(0, min(self.shift_rules.max_fatigue, self.initial_fatigue[key] + change))
        if kind == 'closed' and self.health_rules:
            self._settle_health()
        super()._emit(kind, **data)
        if kind == 'closed':
            from .cafe_activities import close_day
            close_day(self)
            from .cafe_management import close_day as management_close
            management_close(self)
            from .cafe_goal import settle
            settle(self)

    def initialize_weekdays(self, rules=None):
        from .cafe_weekdays import initialize
        initialize(self, rules)

    def _arrive(self):
        if self.weekdays is None:
            super()._arrive()
        else:
            from .cafe_weekdays import schedule
            from .models import Visit
            for key, tick in schedule(self).items():
                if tick != self.tick:
                    continue
                visit = Visit(key, tick)
                self.visits[key] = visit
                self._emit('arrival', customer_id=key)
                if len(self.queue) >= self.config.queue_capacity:
                    self._depart(visit, 'queue_full')
                else:
                    self.queue.append(key)
        from .cafe_preferences import arrive
        arrive(self)
        for visit in self.visits.values():
            visit.first_visit = visit.id not in self.returning_customers

    def day_result(self):
        if not self.closed:
            raise ValueError('閉店後に結果を確認してください。')
        from .cafe_checkpoint import outcome_result
        changes = {}
        for log in list(self.outcomes.values())[self.day_outcome_offset:]:
            result = outcome_result(log)
            key = (result['cat_id'], result['customer_id'])
            changes[key] = changes.get(key, 0) + result['affinity_after'] - result['affinity_before']
        return dict(day=self.day, summary=self.summary(),
                    **({"customer_visits": sorted(self.visits)} if self.weekdays is not None else {}),
                    cats={key: dict(stamina=cat.stamina,
                         **(dict(stress=self.management['stress'][key]) if self.management else {}),
                         **(dict(activity=self.activities['day_locations'][key]) if self.activities else {}),
                         **(dict(interactions=sum(1 for value in list(self.outcomes.values())[self.day_outcome_offset:]
                              if outcome_result(value)['cat_id']==key)) if self.compact else {}),
                         spent=(self.start_state.stamina if self.day == 1 and not (self.recruitment and key in self.recruitment['accepted']) else self.config.max_stamina)-cat.stamina,
                         **(dict(shift='work' if key in self.working_cats else 'rest',
                                 fatigue_before=self.initial_fatigue[key], fatigue_after=cat.fatigue,
                                 service_ticks=self.cat_service_ticks[key]) if self.shift_rules else {}),
                         **(dict(health=copy.deepcopy(self.health_results[key])) if self.health_rules else {}))
                          for key,cat in self.cats.items()},
                    affinity_changes=[dict(cat_id=key[0], customer_id=key[1], change=value)
                                      for key,value in changes.items()])

    def next_day(self):
        self.require_events_resolved()
        if not self.closed or self.active or getattr(self, 'interactions', {}):
            raise ValueError('交流を終了して閉店してから翌日へ進んでください。')
        self._advance_day(self.day_result(), dict(kind='next_day'))

    def day_off(self):
        self.require_events_resolved()
        if not self.can_set_shifts or not self.shift_rules or not self.health_rules:
            raise ValueError('休業は出勤・病気ルールが有効な営業準備中に選んでください。')
        planned = set(self.working_cats)
        self.working_cats = set()
        self._tick_events = []
        self._emit('day_off', day=self.day)
        self.tick = self.config.opening_ticks
        self.closed = True
        self._emit('closed', revenue=0)
        result = self.day_result()
        result['day_type'] = 'day_off'
        self.working_cats = {key for key in planned if self.activity(key)=='cafe' and self.cats[key].health_status=='healthy'}
        from .cafe_management import is_over
        if is_over(self):
            self._record(dict(kind='day_off'))
            return
        self._advance_day(result, dict(kind='day_off'), list(self._tick_events))

    def _advance_day(self, result, operation, events=None):
        self.day_results.append(result)
        self.day_outcome_offset = len(self.outcomes)
        self.returning_customers.update(self.visits)
        self.visits = {}
        self.queue = []
        self.tick = 0
        self.day += 1
        if self.player_bond is not None:
            self.player_bond['today'] = dict.fromkeys(self.cats, 0)
        self.closed = False
        self.service_ticks = 0
        self.spirit_spent = 0
        self.interaction_bonus = 0
        for cat in self.cats.values():
            if self.activity(cat.id) != 'cafe':
                continue
            cat.stamina = self.config.max_stamina
            if cat.health_status == 'healthy':
                cat.cannot_continue = False
        self._tick_events = [] if events is None else events
        self.cat_service_ticks = dict.fromkeys(self.cats, 0)
        self.initial_fatigue = {key: cat.fatigue for key, cat in self.cats.items()}
        if self.activities:
            self.activities['day_locations'] = dict(self.activities['cats'])
        if self.health_rules:
            self.working_cats = {key for key in self.working_cats if self.cats[key].health_status == 'healthy' and self.activity(key) == 'cafe'}
            self.initial_health = self._health_state()
            self.health_results = {}
        self._emit('next_day', day=self.day)
        self._record(operation)

    def _record(self, operation):
        if self.compact:
            from .cafe_checkpoint import record_digest
            self.recorded_digest=record_digest(self)
            self.operations.append(dict(operation=operation,events=copy.deepcopy(self._tick_events),state_digest=self.recorded_digest))
        else:
            self.operations.append(dict(operation=operation, events=copy.deepcopy(self._tick_events), state=self.snapshot()))

    def start(self, interaction):
        if self.closed or self.active or self.seat.customer_id is not None:
            raise ValueError('交流を開始できません。営業中の空席が必要です。')
        self.require_events_resolved()
        if interaction.cat_id not in self.cats or interaction.customer_id not in self.queue:
            raise ValueError('営業中の猫と待機中のお客を選んでください。')
        cat = self.cats[interaction.cat_id]
        if self.activity(cat.id) != 'cafe' or cat.id not in self.working_cats or cat.health_status != 'healthy' or cat.cannot_continue or cat.stamina <= 0:
            raise ValueError('この猫は現在交流できません。')
        if (interaction.records or interaction.state['end_reason'] or
                interaction.state['stamina'] != cat.stamina or
                interaction.config.max_stamina != self.config.max_stamina or
                interaction.config.ticks > self.config.opening_ticks - self.tick or
                interaction.session_id in self.outcomes):
            raise ValueError('交流の開始条件が営業状態と一致しません。')
        from .cafe_preferences import check_interaction
        check_interaction(self, interaction)
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
        self.cat_service_ticks[self.cat.id] += 1
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
        from .cafe_adoption import consider
        consider(self, result)
        if self.cat.stamina == 0:
            self.cat.cannot_continue = True
        self.active = None

    def step(self, action=None, target_type=None):
        self.require_events_resolved()
        if self.closed:
            raise RuntimeError('営業は終了しています')
        if self.active:
            # 無効操作で営業の来客・時計だけが進むことを防ぐ。
            copy.deepcopy(self.active).step(action, target_type)
        elif action is not None or target_type is not None:
            raise ValueError('先に待機中のお客との交流を開始してください。')
        super().step(cat_action=(action, target_type))
        if self.compact:
            self.records.clear()
        self._record(dict(kind='step', action=action, target_type=target_type))
        return self.observation()

    def finish(self):
        self.require_events_resolved()
        if self.active is None:
            return  # 保存再試行や終了ボタンの連打では会計を繰り返さない。
        self._tick_events = []
        self.active.finish()
        self._complete()
        self._record(dict(kind='finish'))

    def summary(self):
        from .cafe_recruitment import expenses
        from .cafe_expansion import expenses as expansion_expenses
        from .cafe_equipment import expenses as equipment_expenses
        from .cafe_activities import reward
        visits = list(self.visits.values())
        return dict(ticks=self.tick, closed=self.closed, arrivals=len(visits),
                    completed_interactions=len(self.outcomes)-self.day_outcome_offset,
                    departures={reason:sum(v.departure_reason == reason for v in visits)
                                for reason in sorted({v.departure_reason for v in visits if v.departure_reason})},
                    revenue=sum(v.bill for v in visits), funds=self.funds,
                    **({'goal_status': self.goal['status'], 'popularity_gain': next((r['gain'] for r in self.goal['days'] if r['day']==self.day),0)} if self.goal else {}),
                    **({'equipment_expenses': equipment_expenses(self, self.day)} if self.rest_space is not None else {}),
                    **({'expansion_expenses': expansion_expenses(self, self.day)} if self.expansion is not None else {}),
                    **({'recruitment_expenses': expenses(self, self.day)} if self.recruitment is not None else {}),
                    **(dict(popularity=self.management['popularity'],game_over=copy.deepcopy(self.management['game_over']),
                             kitten_expenses=sum(e['cost'] for e in self.management['events'].values()
                                                 if e['resolved_day']==self.day)) if self.management else {}),
                    interaction_bonus=self.interaction_bonus, stamina=self.cat.stamina,
                    **({'dispatch_income': sum(reward(self,e) for e in self.activities['events'].values()
                        if e['status']=='resolved' and e['resolved_day']==self.day)} if self.activities else {}),
                    service_ticks=self.service_ticks,
                    **({'cat_stamina': {key:cat.stamina for key,cat in self.cats.items()}} if self.roster_ids is not None else {}))

    def log(self):
        if self.compact:
            from .cafe_replay import replay_log
            return replay_log(self)
        return dict(mode_id='cafe-human-cat', format_version=2 if self.roster_ids is not None else 1, config=json.loads(json.dumps(self.config.to_dict())),
                    seed=self.seed, start_state=asdict(self.start_state),
                    operations=copy.deepcopy(self.operations), summary=self.summary(),
                    **({'cat_ids': list(self.roster_ids)} if self.roster_ids is not None else {}))


def verify_cafe_interaction(data):
    from .config import Config
    from .models import StartState
    if data.get('mode_id') == 'cafe-human-cat' and data.get('format_version') == 4:
        from .cafe_replay import verify
        return verify(data)
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
        if operation['kind'] == 'enable_health':
            core.enable_health(operation['rules'])
        elif operation['kind'] == 'set_shifts':
            core.set_shifts(operation['working_cats'], operation['rules'])
        elif operation['kind'] == 'start':
            core.start(verify_relationship(operation['interaction']))
        elif operation['kind'] == 'step':
            core.step(operation['action'], operation['target_type'])
        elif operation['kind'] == 'day_off':
            core.day_off()
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
