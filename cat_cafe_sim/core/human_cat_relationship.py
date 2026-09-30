"""版4：終了理由と成果の分離。永続保存はこのcoreから行わない。"""
import copy
import math
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .human_cat_types import TypesConfig, TypesInteraction, bounded
from .human_cat_interaction import INTERACTIONS, MODE_ID

RELATIONSHIP_CONFIG = Path(__file__).resolve().parents[2] / 'config/human_cat_relationship.json'


def identity(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError('IDs must be nonempty strings up to 200 characters')
    return value


@dataclass(frozen=True)
class RelationshipConfig(TypesConfig):
    customer_tension_multiplier: float = 1
    equipment_engagement_multiplier: float = 1
    equipment_tension_multiplier: float = 1
    contact_service: bool = False
    play_service: bool = False
    quiet_service: bool = False
    equipment_group: str = ''
    mastery_group: str = ''
    second_mastery_group: str = ''
    third_mastery_group: str = ''
    mastery_engagement_multiplier: float = 1
    type_mastery: str = ''
    second_type_mastery: str = ''
    second_group_type_mastery: str = ''
    second_group_second_type_mastery: str = ''
    type_mastery_engagement_multiplier: float = 1
    affinity_enthusiastic: float = 1
    affinity_favorable: float = .5
    affinity_turn_away_loss: float = 1
    affinity_connect: float = 1
    affinity_open_up: float = 2
    affinity_simultaneous: float = 1
    affinity_exhausted_loss: float = 2

    def __post_init__(self):
        super().__post_init__()
        if type(self.contact_service) is not bool or (self.contact_service and (self.play_service or self.quiet_service)):
            raise ValueError('invalid contact service flag')
        if type(self.play_service) is not bool or (self.play_service and self.quiet_service):
            raise ValueError('invalid play service flag')
        if type(self.quiet_service) is not bool:
            raise ValueError("invalid quiet service flag")
        bounded(self.customer_tension_multiplier, 1, 2, 'customer tension multiplier')
        bounded(self.equipment_engagement_multiplier, 1, 2, 'equipment engagement multiplier')
        bounded(self.equipment_tension_multiplier, 1, 2, 'equipment tension multiplier')
        if self.equipment_group not in ('', 'play', 'contact', 'quiet'):
            raise ValueError('invalid equipment group')
        if self.equipment_group and (self.equipment_engagement_multiplier == 1 or self.equipment_tension_multiplier != 1):
            raise ValueError('group equipment requires engagement bonus without tension bonus')
        if self.mastery_group not in ('','play','contact','quiet'):
            raise ValueError('invalid mastery group')
        if self.second_mastery_group not in ('','play','contact','quiet') or (self.second_mastery_group
                and (not self.mastery_group or self.second_mastery_group==self.mastery_group)):
            raise ValueError('second mastery group must be distinct and require first mastery')
        bounded(self.mastery_engagement_multiplier, 1, 2, 'mastery engagement multiplier')
        if bool(self.mastery_group)!=(self.mastery_engagement_multiplier!=1):
            raise ValueError('mastery group and multiplier must be set together')
        from .human_cat_types import TYPE_IDS
        if self.third_mastery_group not in ('','play','contact','quiet') or (self.third_mastery_group
                and (not self.second_mastery_group or self.third_mastery_group in (self.mastery_group,self.second_mastery_group))):
            raise ValueError('third mastered group must be distinct and follow second mastered group')
        if not isinstance(self.type_mastery,str) or self.type_mastery not in ('',*TYPE_IDS):
            raise ValueError('invalid individual mastery type')
        bounded(self.type_mastery_engagement_multiplier, 1, 2, 'individual mastery engagement multiplier')
        if bool(self.type_mastery or self.second_group_type_mastery)!=(self.type_mastery_engagement_multiplier!=1):
            raise ValueError('individual mastery type and multiplier must be set together')
        if self.type_mastery and next(row.group for row in self.types if row.id==self.type_mastery)!=self.mastery_group:
            raise ValueError('individual mastery must belong to mastered group')
        if not isinstance(self.second_type_mastery,str) or self.second_type_mastery not in ('',*TYPE_IDS):
            raise ValueError('invalid second individual mastery type')
        if self.second_type_mastery and (not self.type_mastery or self.second_type_mastery==self.type_mastery
                or next(row.group for row in self.types if row.id==self.second_type_mastery)!=self.mastery_group):
            raise ValueError('second individual mastery must be distinct and belong to mastered group')
        if not isinstance(self.second_group_type_mastery,str) or self.second_group_type_mastery not in ('',*TYPE_IDS):
            raise ValueError('invalid second group individual mastery type')
        if self.second_group_type_mastery and (not self.second_mastery_group
                or next(row.group for row in self.types if row.id==self.second_group_type_mastery)!=self.second_mastery_group):
            raise ValueError('second group individual mastery must belong to second mastered group')
        if not isinstance(self.second_group_second_type_mastery,str) or self.second_group_second_type_mastery not in ('',*TYPE_IDS):
            raise ValueError('invalid second group additional individual mastery type')
        if self.second_group_second_type_mastery and (not self.second_group_type_mastery
                or self.second_group_second_type_mastery==self.second_group_type_mastery
                or next(row.group for row in self.types if row.id==self.second_group_second_type_mastery)!=self.second_mastery_group):
            raise ValueError('additional individual mastery must be distinct and belong to second mastered group')
        if any(not math.isfinite(value * self.equipment_engagement_multiplier) for key,value in vars(self).items() if key.endswith('_gain') and isinstance(value,(int,float))):
            raise ValueError('equipment engagement overflow')
        if not math.isfinite(max(self.tension_enthusiastic, self.tension_favorable, self.tension_neutral) * self.customer_tension_multiplier * self.equipment_tension_multiplier):
            raise ValueError('customer tension overflow')
        maximum = sum(getattr(self, key) for key in ('affinity_enthusiastic','affinity_favorable',
                      'affinity_turn_away_loss','affinity_connect','affinity_open_up','affinity_simultaneous','affinity_exhausted_loss'))
        if not math.isfinite(maximum * self.ticks):
            raise ValueError('affinity accumulation overflow')

    def to_dict(self):
        data = super().to_dict()
        if not self.contact_service:
            data['rules'].pop('contact_service')
        if not self.play_service:
            data['rules'].pop('play_service')
        if not self.quiet_service:
            data["rules"].pop("quiet_service")
        if self.customer_tension_multiplier == 1:
            data['rules'].pop('customer_tension_multiplier')
        for key in ("equipment_engagement_multiplier", "equipment_tension_multiplier"):
            if getattr(self,key) == 1:
                data["rules"].pop(key)
        if not self.equipment_group:
            data['rules'].pop('equipment_group')
        if not self.mastery_group:
            data['rules'].pop('mastery_group')
            data['rules'].pop('mastery_engagement_multiplier')
        if not self.third_mastery_group:
            data['rules'].pop('third_mastery_group')
        if not self.second_mastery_group:
            data['rules'].pop('second_mastery_group')
        if not self.type_mastery:
            data['rules'].pop('type_mastery')
        if not (self.type_mastery or self.second_group_type_mastery):
            data['rules'].pop('type_mastery_engagement_multiplier')
        if not self.second_type_mastery:
            data['rules'].pop('second_type_mastery')
        if not self.second_group_second_type_mastery:
            data['rules'].pop('second_group_second_type_mastery')
        if not self.second_group_type_mastery:
            data['rules'].pop('second_group_type_mastery')
        return data

    @classmethod
    def load(cls, path=RELATIONSHIP_CONFIG):
        return super().load(path)


class RelationshipInteraction(TypesInteraction):
    def __init__(self, config=None, *, cat_id='cat-1', customer_id='guest-1', session_id=None,
                 affinity=0, revision=0, **kwargs):
        super().__init__(config or RelationshipConfig(), **kwargs)
        self.cat_id, self.customer_id = identity(cat_id), identity(customer_id)
        self.session_id = identity(str(uuid4()) if session_id is None else session_id)
        bounded(affinity, 0, 100, 'initial affinity')
        if type(revision) is not int or revision < 0:
            raise ValueError('revision must be a nonnegative integer')
        self.initial_relationship = dict(cat_id=self.cat_id, customer_id=self.customer_id,
                                         session_id=self.session_id, affinity=affinity, revision=revision)
        self.state.update(affinity_start=affinity, affinity_pending=0)
        self.finish_event = None

    def _tension_effect(self, delta, opened):
        return delta * self.config.customer_tension_multiplier * self.config.equipment_tension_multiplier if delta > 0 and not opened else delta

    def _normal_effect(self, action):
        cost, score, reaction, diagnostic = super()._normal_effect(action)
        if (action in INTERACTIONS and score > 0 and self.config.equipment_engagement_multiplier != 1
                and (not self.config.equipment_group or diagnostic.get('boredom_group') == self.config.equipment_group)):
            score *= self.config.equipment_engagement_multiplier
            diagnostic = dict(diagnostic, equipment_multiplier=self.config.equipment_engagement_multiplier)
            if self.config.equipment_group:
                diagnostic = dict(diagnostic, equipment_group=self.config.equipment_group)
        if (action in INTERACTIONS and score>0 and self.config.mastery_group
                and diagnostic.get('boredom_group') in (self.config.mastery_group,self.config.second_mastery_group,self.config.third_mastery_group)):
            score*=self.config.mastery_engagement_multiplier
            diagnostic=dict(diagnostic,mastery_group=diagnostic['boredom_group'],
                            mastery_multiplier=self.config.mastery_engagement_multiplier,score=score)
        if action in INTERACTIONS and score>0 and self.state['mode'] in (self.config.type_mastery,self.config.second_type_mastery,self.config.second_group_type_mastery,self.config.second_group_second_type_mastery):
            score*=self.config.type_mastery_engagement_multiplier
            diagnostic=dict(diagnostic,type_mastery=self.state['mode'],
                            type_mastery_multiplier=self.config.type_mastery_engagement_multiplier,score=score)
        return cost, score, reaction, diagnostic

    def _end_reason(self):
        return 'exhausted' if self.state['stamina'] == 0 else 'time_limit' if self.state['remaining_ticks'] == 0 else None

    def step(self, action, target_type=None):
        record = super().step(action, target_type)
        c = self.config
        if (action=='switch' and c.mastery_group
                and self.type_map[target_type].group in (c.mastery_group,c.second_mastery_group,c.third_mastery_group)):
            record['diagnostic']=dict(record['diagnostic'],mastery_switch=True,mastery_group=self.type_map[target_type].group)
        if action=='switch' and target_type in (c.type_mastery,c.second_type_mastery,c.second_group_type_mastery,c.second_group_second_type_mastery):
            record['diagnostic']=dict(record['diagnostic'],type_mastery_switch=True,type_mastery=target_type)
        normal = record['normal_reaction']
        normal_delta = (c.affinity_enthusiastic if normal == 'enthusiastic' else c.affinity_favorable if normal == 'favorable'
                        else -c.affinity_turn_away_loss if normal == 'turn_away' else 0) if action in INTERACTIONS else 0
        connect, opened = record['connect_source'] is not None, record['open_up_source'] is not None
        parts = dict(normal=normal_delta, connect=c.affinity_connect if connect else 0,
                     open_up=c.affinity_open_up if opened else 0,
                     simultaneous=c.affinity_simultaneous if connect and opened else 0,
                     exhaustion=-c.affinity_exhausted_loss if self.state['end_reason'] == 'exhausted' else 0)
        self.state['affinity_pending'] += sum(parts.values())
        record.update(affinity_breakdown=parts, after=self.observation())
        self.records[-1] = copy.deepcopy(record)
        return record

    def finish(self):
        if not self.state['end_reason']:
            before = self.observation()
            expired = dict(connect=self.state['connect_pending'], open_up=self.state['open_up_pending'])
            self.state.update(end_reason='manual', connect_pending=False, open_up_pending=False)
            self.finish_event = dict(kind='finish', before=before, after=self.observation(), expired_reservations=expired)
        return self.result()

    def summary(self):
        result = super().summary()
        start, pending = self.state['affinity_start'], self.state['affinity_pending']
        end = min(100, max(0, start + pending))
        parts = {key:sum(r['affinity_breakdown'][key] for r in self.records) for key in
                 ('normal','connect','open_up','simultaneous','exhaustion')}
        result.update(cat_id=self.cat_id, customer_id=self.customer_id, session_id=self.session_id,
                      affinity_before=start, affinity_pending=pending, affinity_after=end,
                      affinity_delta=end-start, affinity_unapplied=pending-(end-start), affinity_breakdown=parts,
                      stamina_recovered=sum(r['stamina_recovered'] for r in self.records))
        if self.config.contact_service:
            result['contact_equipment'] = self.config.equipment_group == 'contact'
        if self.config.play_service:
            result['play_equipment'] = self.config.equipment_group == 'play'
        if self.config.quiet_service:
            result['quiet_equipment'] = self.config.equipment_group == 'quiet'
        if self.finish_event:
            result['expired_reservations'] += sum(self.finish_event['expired_reservations'].values())
        return result

    def result(self):
        if not self.state['end_reason']:
            raise ValueError('finish the interaction before committing outcomes')
        return self.summary()

    def log(self):
        result = super().log()
        result.update(rule_version=4, initial_relationship=dict(self.initial_relationship),
                      finish_event=copy.deepcopy(self.finish_event))
        return result


def verify_relationship(data):
    if data.get('mode_id') != MODE_ID or 'initial_relationship' not in data or 'finish_event' not in data:
        raise ValueError('unsupported relationship log')
    core = RelationshipInteraction(RelationshipConfig.from_dict(data['config']), stamina=data['initial_stamina'],
                                   **data['initial_gauges'], **data['initial_relationship'])
    for i, record in enumerate(data['records']):
        if core.step(record['action'], record['target_type']) != record:
            raise ValueError(f'replay mismatch at tick {i}')
    if data['finish_event'] is not None:
        core.finish()
    if core.log() != data:
        raise ValueError('replay finish, metadata or summary mismatch')
    return core
