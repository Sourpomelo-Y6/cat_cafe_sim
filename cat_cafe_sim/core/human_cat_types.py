"""版3：種類定義と猫の個性。特別行動と通常状態更新は既存coreを共有。"""
from dataclasses import asdict, dataclass, field
import copy
import json
import math
from pathlib import Path

from .human_cat_interaction import ACTIONS, INTERACTIONS, NEGATIVE, MODE_ID
from .human_cat_special import SpecialConfig, SpecialInteraction

TYPE_IDS = ('teaser', 'ball', 'plush', 'tunnel', 'pet', 'brush', 'voice', 'presence')
STRENGTHS = ('gentle', 'standard', 'active')
TYPES_CONFIG = Path(__file__).resolve().parents[2] / 'config/human_cat_types.json'
PRESETS_CONFIG = TYPES_CONFIG.with_name('cat_personalities.json')


def bounded(value, lower, upper, name, *, exclusive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper or (exclusive and value == lower):
        raise ValueError(f'invalid {name}: expected {lower}..{upper}')


@dataclass(frozen=True)
class InteractionType:
    id: str
    name: str
    group: str
    gain: float
    cost: float
    actions: tuple

    def __post_init__(self):
        if self.id not in TYPE_IDS or not isinstance(self.name, str) or not self.name.strip() or self.group not in ('play', 'contact', 'quiet'):
            raise ValueError('invalid interaction type identity')
        bounded(self.gain, 0, 2, 'type gain', exclusive=True)
        bounded(self.cost, 0, 2, 'type cost', exclusive=True)
        if (not isinstance(self.actions, tuple) or not all(isinstance(a, str) for a in self.actions)
                or len(set(self.actions)) != len(self.actions) or not {'direct', 'adapt'} <= set(self.actions)
                or not set(self.actions) <= set(INTERACTIONS)):
            raise ValueError('invalid type action list')


def default_types():
    names = ('ねこじゃらし', 'ボール遊び', 'ぬいぐるみ遊び', 'トンネル遊び', 'なでる', 'ブラッシング', '声をかける', 'そばで見守る')
    gains, costs = (1, 1, .9, 1.1, 1, .9, .7, .5), (1, 1.1, .9, 1.2, 1, .8, .5, .3)
    return tuple(InteractionType(key, names[i], 'play' if i < 4 else 'contact' if i < 6 else 'quiet', gains[i], costs[i],
                                INTERACTIONS if i in (0, 1, 3) else ('direct', 'adapt', 'feint') if i == 2 else ('direct', 'adapt'))
                 for i, key in enumerate(TYPE_IDS))


@dataclass(frozen=True)
class Personality:
    type_preferences: tuple = (1,) * 8
    intensity_preferences: tuple = (1, 1, 1)
    boredom_decay: float = .15
    switch_affinity: float = 0

    def __post_init__(self):
        for values, length in ((self.type_preferences, 8), (self.intensity_preferences, 3)):
            if not isinstance(values, tuple) or len(values) != length:
                raise ValueError('all type and strength preferences are required')
            for value in values:
                bounded(value, 0, 2, 'preference')
        bounded(self.boredom_decay, 0, 1, 'boredom decay')
        bounded(self.switch_affinity, -.5, .5, 'switch affinity')

    def to_dict(self):
        return dict(type_preferences=dict(zip(TYPE_IDS, self.type_preferences)),
                    intensity_preferences=dict(zip(STRENGTHS, self.intensity_preferences)),
                    boredom_decay=self.boredom_decay, switch_affinity=self.switch_affinity)

    @classmethod
    def from_dict(cls, data):
        if set(data) != {'type_preferences', 'intensity_preferences', 'boredom_decay', 'switch_affinity'}:
            raise ValueError('invalid personality fields')
        if set(data['type_preferences']) != set(TYPE_IDS) or set(data['intensity_preferences']) != set(STRENGTHS):
            raise ValueError('missing or unknown preference IDs')
        return cls(tuple(data['type_preferences'][k] for k in TYPE_IDS),
                   tuple(data['intensity_preferences'][k] for k in STRENGTHS), data['boredom_decay'], data['switch_affinity'])


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def load_presets(path=PRESETS_CONFIG):
    data = json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique_object)
    return {name: Personality.from_dict(values) for name, values in data.items()}


@dataclass(frozen=True)
class TypesConfig(SpecialConfig):
    types: tuple = field(default_factory=default_types)
    personality: Personality = field(default_factory=Personality)

    def __post_init__(self):
        super().__post_init__()
        if self.preferences != (1, 1) or self.boredom_decay != .15:
            raise ValueError('use personality fields instead of legacy preferences or boredom_decay')
        if (not isinstance(self.types, tuple) or not all(isinstance(t, InteractionType) for t in self.types)
                or len(self.types) != 8 or {t.id for t in self.types} != set(TYPE_IDS)):
            raise ValueError('exactly eight unique types required')
        if not isinstance(self.personality, Personality):
            raise ValueError('invalid personality')
        if not math.isfinite(max(self.direct_gain, self.adapt_gain, self.gentle_gain, self.intense_gain,
                                 self.feint_gain, self.combo_gain) * 12):
            raise ValueError('type effect overflow')

    def to_dict(self):
        rules = {k: v for k, v in asdict(self).items() if k not in ('types', 'personality', 'preferences', 'boredom_decay')}
        return dict(rules=rules, types=[{**asdict(t), 'actions': list(t.actions)} for t in self.types], personality=self.personality.to_dict())

    @classmethod
    def from_dict(cls, data):
        if set(data) != {'rules', 'types', 'personality'} or set(data['rules']) & {'preferences', 'boredom_decay', 'types', 'personality'}:
            raise ValueError('version 3 requires explicit type definitions and personality')
        types = tuple(InteractionType(**{**t, 'actions': tuple(t['actions'])}) for t in data['types'])
        return cls(**data['rules'], types=types, personality=Personality.from_dict(data['personality']))

    @classmethod
    def load(cls, path=TYPES_CONFIG):
        return cls.from_dict(json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique_object))


class TypesInteraction(SpecialInteraction):
    def __init__(self, config=None, **kwargs):
        super().__init__(config or TypesConfig(), **kwargs)
        self.type_map = {t.id: t for t in self.config.types}
        self.state.update(mode='teaser', last_interaction_group=None)
        self._target_type = None

    def valid_actions(self):
        s = self.state
        if s['end_reason']:
            return ()
        if s['connect_pending']:
            return ('connect',)
        valid = self.type_map[s['mode']].actions + ('pause', 'switch')
        return valid + (('connect',) if s['tension'] >= self.config.optional_threshold else ())

    def step(self, action, target_type=None):
        if not isinstance(action, str) or action not in self.valid_actions():
            raise ValueError('invalid action or forced connect pending')
        if action == 'switch':
            if not isinstance(target_type, str) or target_type not in self.type_map or target_type == self.state['mode']:
                raise ValueError('choose a different known target type')
        elif target_type is not None:
            raise ValueError('target type is only allowed for switch')
        self._target_type = target_type
        try:
            record = super().step(action)
        finally:
            self._target_type = None
        record['target_type'] = target_type
        self.records[-1] = copy.deepcopy(record)
        return record

    def _switch_mode(self):
        return self._target_type

    def _normal_effect(self, action):
        c, s = self.config, self.state
        t, p = self.type_map[s['mode']], c.personality
        if action not in INTERACTIONS:
            reaction = 'listless' if s['stamina'] <= c.low_stamina else 'neutral'
            return 0, 0, reaction, dict(base_gain=0, score=0, boredom_multiplier=1)
        base, cost = getattr(c, action + '_gain'), getattr(c, action + '_cost')
        strength = 'active' if action == 'intense' else 'standard'
        if action == 'adapt' and s['previous_reaction'] in NEGATIVE:
            base, cost, strength = c.gentle_gain, c.gentle_cost, 'gentle'
        if action == 'feint' and s['previous_action'] == 'pause' and s['pause_after_interaction']:
            base = c.combo_gain
        switched = s['last_interaction_group'] is not None and s['last_interaction_group'] != t.group
        s['interaction_streak'] = s['interaction_streak'] + 1 if s['last_interaction_group'] == t.group else 1
        s['last_interaction_kind'], s['last_interaction_group'] = t.id, t.group
        boredom = max(c.boredom_floor, 1 - p.boredom_decay * (s['interaction_streak'] - 1))
        switch = 1 + p.switch_affinity if switched else 1
        preference = p.type_preferences[TYPE_IDS.index(t.id)]
        intensity = p.intensity_preferences[STRENGTHS.index(strength)]
        score = base * t.gain * preference * intensity * boredom * switch
        if preference == 0 or intensity == 0:
            reaction = 'turn_away'
        elif s['stamina'] <= c.low_stamina:
            reaction = 'listless'
        elif score < c.confused_threshold:
            reaction = 'confused'
        elif score >= c.enthusiastic_threshold:
            reaction = 'enthusiastic'
        elif score >= c.favorable_threshold:
            reaction = 'favorable'
        else:
            reaction = 'neutral'
        return cost * t.cost, score, reaction, dict(base_gain=base, score=score, boredom_multiplier=boredom,
            type_id=t.id, strength=strength, boredom_group=t.group, type_gain=t.gain, type_cost=t.cost,
            type_preference=preference, intensity_preference=intensity, switch_multiplier=switch)

    def log(self):
        result = super().log()
        result['rule_version'] = 3
        return result

    def summary(self):
        result = super().summary()
        result['type_actions'] = {key: sum(r['before']['mode'] == key and r['action'] in INTERACTIONS for r in self.records) for key in TYPE_IDS}
        return result


def verify_types(data):
    if data.get('mode_id') != MODE_ID or 'initial_gauges' not in data:
        raise ValueError('unsupported type log')
    core = TypesInteraction(TypesConfig.from_dict(data['config']), stamina=data['initial_stamina'], **data['initial_gauges'])
    for i, record in enumerate(data['records']):
        if core.step(record['action'], record['target_type']) != record:
            raise ValueError(f'replay mismatch at tick {i}')
    if core.log() != data:
        raise ValueError('replay metadata or summary mismatch')
    return core
