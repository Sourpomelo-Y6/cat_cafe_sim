"""ルール版2：テンションと双方の特別行動。通常効果は版1と共通。"""
from dataclasses import dataclass
import copy
import math
from pathlib import Path

from .human_cat_interaction import HumanCatInteraction, InteractionConfig, INTERACTIONS, MODE_ID

SPECIAL_CONFIG = Path(__file__).resolve().parents[2] / 'config/human_cat_special.json'


@dataclass(frozen=True)
class SpecialConfig(InteractionConfig):
    optional_threshold: float = 80
    forced_threshold: float = 100
    gauge_cost: float = 80
    connect_bonus: float = 50
    open_up_bonus: float = 50
    simultaneous_bonus: float = 100
    open_up_tension: float = 10
    tension_enthusiastic: float = 20
    tension_favorable: float = 12
    tension_neutral: float = 6
    tension_confused_loss: float = 4
    tension_listless_loss: float = 6
    tension_turn_away_loss: float = 8

    def __post_init__(self):
        super().__post_init__()
        if not 0 < self.gauge_cost <= self.optional_threshold < self.forced_threshold <= self.target:
            raise ValueError('invalid special action thresholds')
        if not math.isfinite(self.connect_bonus + self.open_up_bonus + self.simultaneous_bonus):
            raise ValueError('bonus overflow')

    @classmethod
    def load(cls, path=SPECIAL_CONFIG):
        return super().load(path)


class SpecialInteraction(HumanCatInteraction):
    def __init__(self, config=None, *, stamina=None, tension=0, engagement=0):
        super().__init__(config or SpecialConfig(), stamina=stamina)
        for value in (tension, engagement):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= self.config.target:
                raise ValueError('initial gauges must lie within limits')
        self.initial_gauges = dict(tension=tension, engagement=engagement)
        self.state.update(tension=tension, engagement=engagement,
                          connect_pending=tension >= self.config.forced_threshold,
                          open_up_pending=engagement >= self.config.forced_threshold,
                          connect_count=0, open_up_count=0, simultaneous_count=0, bonus_funds=0,
                          previous_cat_action=None)

    def valid_actions(self):
        if self.state['end_reason']:
            return ()
        if self.state['connect_pending']:
            return ('connect',)
        return super().valid_actions() + (('connect',) if self.state['tension'] >= self.config.optional_threshold else ())

    def cat_will_open(self):
        s, c = self.state, self.config
        return not s['end_reason'] and (s['open_up_pending'] or (
            s['engagement'] >= c.optional_threshold and (s['tension'] >= c.optional_threshold
            or s['remaining_ticks'] == 1 or s['stamina'] <= c.low_stamina)))

    def step(self, action):
        if not isinstance(action, str) or action not in self.valid_actions():
            raise ValueError('invalid action or forced connect pending')
        before, c, s = self.observation(), self.config, self.state
        connect, opened = action == 'connect', bool(self.cat_will_open())
        s['tension'] -= c.gauge_cost if connect else 0
        s['engagement'] -= c.gauge_cost if opened else 0
        s['connect_pending'] = s['open_up_pending'] = False
        if connect:
            s.update(previous_action='connect', previous_reaction=None, pause_after_interaction=False,
                     remaining_ticks=s['remaining_ticks'] - 1)
            record = dict(tick=len(self.records), action=action, reaction='received',
                          stamina_spent=0, stamina_recovered=0,
                          diagnostic=dict(base_gain=0, score=0, boredom_multiplier=1))
            self.records.append(record)
            gain = 0
        else:
            record = self._step_normal(action)
            # _step_normal returns a copy; replace the stored record after v2 resolution.
            gain = record['engagement_delta']
        normal_reaction = s['previous_reaction']
        if opened:
            delta = c.open_up_tension
        elif action in INTERACTIONS:
            delta = (getattr(c, 'tension_' + normal_reaction) if normal_reaction in
                     ('enthusiastic', 'favorable', 'neutral') else -getattr(c, 'tension_' + normal_reaction + '_loss'))
        else:
            delta = 0
        raw_tension = s['tension'] + delta
        s['tension'] = max(0, min(c.target, raw_tension))
        bonuses = dict(connect=c.connect_bonus if connect else 0, open_up=c.open_up_bonus if opened else 0,
                       simultaneous=c.simultaneous_bonus if connect and opened else 0)
        s['bonus_funds'] += sum(bonuses.values())
        s['connect_count'] += int(connect)
        s['open_up_count'] += int(opened)
        s['simultaneous_count'] += int(connect and opened)
        s['previous_cat_action'] = 'open_up' if opened else 'received' if connect else 'normal'
        s['end_reason'] = ('exhausted' if s['stamina'] == 0 else 'success' if s['connect_count'] and s['open_up_count']
                           else 'timeout' if s['remaining_ticks'] == 0 else None)
        pending = dict(connect=s['tension'] >= c.forced_threshold, open_up=s['engagement'] >= c.forced_threshold)
        s['connect_pending'] = pending['connect'] and not s['end_reason']
        s['open_up_pending'] = pending['open_up'] and not s['end_reason']
        s['connect_pending'], s['open_up_pending'] = bool(s['connect_pending']), bool(s['open_up_pending'])
        raw_gain = record['diagnostic']['score'] * (0 if normal_reaction in ('turn_away', 'listless')
                    else c.confused_multiplier if normal_reaction == 'confused' else 1)
        record.update(before=before, after=self.observation(),
                      reaction='open_up' if opened else record['reaction'], normal_reaction=normal_reaction,
                      cat_action=s['previous_cat_action'],
                      connect_source=('forced' if before['connect_pending'] else 'optional') if connect else None,
                      open_up_source=('forced' if before['open_up_pending'] else 'optional') if opened else None,
                      tension_spent=c.gauge_cost if connect else 0, engagement_spent=c.gauge_cost if opened else 0,
                      tension_effect=delta, engagement_gain=gain,
                      tension_delta=s['tension'] - before['tension'], engagement_delta=s['engagement'] - before['engagement'],
                      tension_overflow=max(0, raw_tension - c.target), engagement_overflow=max(0, raw_gain - gain),
                      bonuses=bonuses, expired_reservations={k: bool(v and s['end_reason']) for k, v in pending.items()})
        self.records[-1] = record
        return copy.deepcopy(record)

    def summary(self):
        result = super().summary()
        result.update({k: self.state[k] for k in ('tension', 'connect_count', 'open_up_count', 'simultaneous_count', 'bonus_funds')})
        result['expired_reservations'] = sum(sum(r['expired_reservations'].values()) for r in self.records)
        result['reactions'].update({name: sum(r['reaction'] == name for r in self.records) for name in ('received', 'open_up')})
        return result

    def log(self):
        result = super().log()
        result.update(rule_version=2, initial_gauges=dict(self.initial_gauges))
        return result


def verify_special(data):
    if data.get('mode_id') != MODE_ID or 'initial_gauges' not in data:
        raise ValueError('unsupported interaction mode')
    session = SpecialInteraction(SpecialConfig.from_dict(data['config']), stamina=data['initial_stamina'], **data['initial_gauges'])
    for i, record in enumerate(data['records']):
        if session.step(record['action']) != record:
            raise ValueError(f'replay mismatch at tick {i}')
    if session.log() != data:
        raise ValueError('replay metadata or summary mismatch')
    return session


def create_session(config, **kwargs):
    from .human_cat_types import TypesConfig, TypesInteraction
    if isinstance(config, TypesConfig):
        return TypesInteraction(config, **kwargs)
    return SpecialInteraction(config, **kwargs) if isinstance(config, SpecialConfig) else HumanCatInteraction(config, **kwargs)
