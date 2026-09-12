"""人の動作に猫が応じる独立した、決定的な交流ルール。"""
from dataclasses import asdict, dataclass
import copy
import json
import math
from pathlib import Path

ACTIONS = ('direct', 'adapt', 'intense', 'feint', 'pause', 'switch')
INTERACTIONS = ACTIONS[:4]
NEGATIVE = ('turn_away', 'listless', 'confused')
MODE_ID = 'human-cat-interaction'
RULE_VERSION = 1
DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / 'config/human_cat_interaction.json'


@dataclass(frozen=True)
class InteractionConfig:
    ticks: int = 20
    max_stamina: float = 100
    target: float = 100
    preferences: tuple = (1, 1)
    direct_gain: float = 12
    direct_cost: float = 5
    adapt_gain: float = 10
    adapt_cost: float = 5
    gentle_gain: float = 8
    gentle_cost: float = 2
    intense_gain: float = 24
    intense_cost: float = 15
    feint_gain: float = 10
    feint_cost: float = 8
    combo_gain: float = 18
    pause_recovery: float = 2
    boredom_decay: float = .15
    boredom_floor: float = .4
    low_stamina: float = 20
    confused_threshold: float = 6
    favorable_threshold: float = 10
    enthusiastic_threshold: float = 18
    confused_multiplier: float = .5

    def __post_init__(self):
        if type(self.ticks) is not int or self.ticks < 1:
            raise ValueError('ticks must be a positive integer')
        for key, value in asdict(self).items():
            if key in ('ticks', 'preferences', 'types', 'personality'):
                continue
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f'invalid {key}')
        if min(self.max_stamina, self.target) <= 0:
            raise ValueError('resource limits must be positive')
        if not isinstance(self.preferences, tuple) or len(self.preferences) != 2 or any(
                type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 2 for p in self.preferences):
            raise ValueError('two preferences within [0, 2] required')
        if any(getattr(self, k) > 1 for k in ('boredom_decay', 'boredom_floor', 'confused_multiplier')):
            raise ValueError('multipliers must be within [0, 1]')
        if self.low_stamina > self.max_stamina or not (
                self.confused_threshold <= self.favorable_threshold <= self.enthusiastic_threshold):
            raise ValueError('invalid thresholds')
        if not math.isfinite(max(self.direct_gain, self.adapt_gain, self.gentle_gain,
                                 self.intense_gain, self.feint_gain, self.combo_gain) * 2):
            raise ValueError('gain overflow')

    def to_dict(self):
        data = asdict(self)
        data['preferences'] = list(self.preferences)
        return data

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        if 'preferences' in data:
            data['preferences'] = tuple(data['preferences'])
        return cls(**data)

    @classmethod
    def load(cls, path=DEFAULT_CONFIG):
        return cls.from_dict(json.loads(Path(path).read_text(encoding='utf-8')))


class HumanCatInteraction:
    def __init__(self, config=None, *, stamina=None):
        self.config = config or InteractionConfig()
        stamina = self.config.max_stamina if stamina is None else stamina
        if type(stamina) not in (int, float) or not math.isfinite(stamina) or not 0 < stamina <= self.config.max_stamina:
            raise ValueError('initial stamina must be within (0, max_stamina]')
        self.initial_stamina = stamina
        self.state = dict(engagement=0, stamina=stamina, mode='play', last_interaction_kind=None,
                          interaction_streak=0, previous_action=None, previous_reaction=None,
                          pause_after_interaction=False, remaining_ticks=self.config.ticks,
                          end_reason=None)
        self.records = []

    def observation(self):
        return dict(self.state)

    def valid_actions(self):
        if self.state['end_reason']:
            return ()
        return tuple(a for a in ACTIONS if self.state['mode'] == 'play' or a not in ('intense', 'feint'))

    def step(self, action):
        if not isinstance(action, str) or action not in self.valid_actions():
            raise ValueError('invalid action or session already ended')
        return self._step_normal(action)

    def _step_normal(self, action):
        c, s = self.config, self.state
        before = self.observation()
        cost, score, reaction, diagnostic = self._normal_effect(action)
        multiplier = 0 if reaction in ('turn_away', 'listless') else c.confused_multiplier if reaction == 'confused' else 1
        s['engagement'] = min(c.target, s['engagement'] + score * multiplier)
        s['stamina'] = max(0, s['stamina'] - cost)
        if action == 'pause':
            s['stamina'] = min(c.max_stamina, s['stamina'] + c.pause_recovery)
        elif action == 'switch':
            s['mode'] = self._switch_mode()
        s['pause_after_interaction'] = action == 'pause' and before['previous_action'] in INTERACTIONS
        s['previous_action'], s['previous_reaction'] = action, reaction
        s['remaining_ticks'] -= 1
        s['end_reason'] = ('exhausted' if s['stamina'] == 0 else 'success' if s['engagement'] >= c.target
                           else 'timeout' if s['remaining_ticks'] == 0 else None)
        record = dict(tick=len(self.records), action=action, reaction=reaction, before=before,
                      after=self.observation(), engagement_delta=s['engagement'] - before['engagement'],
                      stamina_spent=min(before['stamina'], cost),
                      stamina_recovered=max(0, s['stamina'] - before['stamina']),
                      diagnostic=diagnostic)
        self.records.append(record)
        return copy.deepcopy(record)

    def _switch_mode(self):
        return 'pet' if self.state['mode'] == 'play' else 'play'

    def _normal_effect(self, action):
        c, s = self.config, self.state
        before = self.observation()
        exchange = action in INTERACTIONS
        base = cost = score = 0
        boredom = 1
        if exchange:
            base, cost = getattr(c, action + '_gain'), getattr(c, action + '_cost')
            if action == 'adapt' and s['previous_reaction'] in NEGATIVE:
                base, cost = c.gentle_gain, c.gentle_cost
            if action == 'feint' and s['previous_action'] == 'pause' and s['pause_after_interaction']:
                base = c.combo_gain
            s['interaction_streak'] = s['interaction_streak'] + 1 if s['last_interaction_kind'] == s['mode'] else 1
            s['last_interaction_kind'] = s['mode']
            boredom = max(c.boredom_floor, 1 - c.boredom_decay * (s['interaction_streak'] - 1))
            preference = c.preferences[0 if s['mode'] == 'play' else 1]
            score = base * preference * boredom
        if exchange and preference == 0:
            reaction = 'turn_away'
        elif before['stamina'] <= c.low_stamina:
            reaction = 'listless'
        elif exchange and score < c.confused_threshold:
            reaction = 'confused'
        elif exchange and score >= c.enthusiastic_threshold:
            reaction = 'enthusiastic'
        elif exchange and score >= c.favorable_threshold:
            reaction = 'favorable'
        else:
            reaction = 'neutral'
        return cost, score, reaction, dict(base_gain=base, score=score, boredom_multiplier=boredom)

    def summary(self):
        return dict(engagement=self.state['engagement'], stamina=self.state['stamina'],
                    ticks=len(self.records), end_reason=self.state['end_reason'],
                    stamina_spent=sum(r['stamina_spent'] for r in self.records),
                    reactions={name: sum(r['reaction'] == name for r in self.records) for name in
                               ('turn_away', 'listless', 'confused', 'enthusiastic', 'favorable', 'neutral')})

    def log(self):
        return copy.deepcopy(dict(mode_id=MODE_ID, rule_version=RULE_VERSION, config=self.config.to_dict(),
                                  initial_stamina=self.initial_stamina, records=self.records, summary=self.summary()))


def save(session, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(session.log(), ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def verify(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('rule_version') == 4 and type(data.get('rule_version')) is int:
        from .human_cat_relationship import verify_relationship
        return verify_relationship(data)
    if data.get('rule_version') == 3 and type(data.get('rule_version')) is int:
        from .human_cat_types import verify_types
        return verify_types(data)
    if data.get('rule_version') == 2 and type(data.get('rule_version')) is int:
        from .human_cat_special import verify_special
        return verify_special(data)
    if data.get('mode_id') != MODE_ID or type(data.get('rule_version')) is not int or data['rule_version'] != RULE_VERSION:
        raise ValueError('unsupported interaction mode or version')
    session = HumanCatInteraction(InteractionConfig.from_dict(data['config']), stamina=data['initial_stamina'])
    for index, record in enumerate(data['records']):
        if session.step(record['action']) != record:
            raise ValueError(f'replay mismatch at tick {index}')
    if session.log() != data:
        raise ValueError('replay summary or metadata mismatch')
    return session
