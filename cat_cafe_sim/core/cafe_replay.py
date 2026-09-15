"""現在状態を起点にした詳細ログ。営業セーブとは別に明示出力する。"""
import copy
import json
from dataclasses import asdict
from .human_cat_relationship import verify_relationship


def apply_operation(core, operation):
    kind=operation['kind']
    if kind=='enable_health':core.enable_health(operation['rules'])
    elif kind=='set_shifts':core.set_shifts(operation['working_cats'],operation['rules'])
    elif kind=='day_off':core.day_off()
    elif kind=='next_day':core.next_day()
    elif kind=='start':
        interaction=verify_relationship(operation['interaction'])
        if hasattr(core,'seats'):core.start(interaction,operation['seat_id'])
        else:core.start(interaction)
    elif kind=='step':
        if hasattr(core,'seats'):core.step(operation['commands'])
        else:core.step(operation['action'],operation['target_type'])
    elif kind=='finish':
        if hasattr(core,'seats'):core.finish(operation['seat_id'])
        else:core.finish()
    else:raise ValueError('unknown cafe operation')


def replay_log(core):
    return dict(mode_id='cafe-human-cat',format_version=4,
                config=json.loads(json.dumps(core.config.to_dict())),seed=core.seed,
                start_state=asdict(core.start_state),cat_ids=core.roster_ids,
                seat_count=2 if hasattr(core,'seats') else 1,
                base=copy.deepcopy(core.replay_base),operations=copy.deepcopy(core.operations),summary=core.summary())


def verify(data):
    from .cafe_checkpoint import restore
    from .cafe_interaction import CafeInteractionCore
    from .multi_seat_cafe import MultiSeatCafeCore
    from .config import Config
    from .models import StartState
    if data['base'] is not None:
        core=restore(data['base'])
    else:
        if data['seat_count'] not in (1,2):raise ValueError('invalid seat count')
        cls=MultiSeatCafeCore if data['seat_count']==2 else CafeInteractionCore
        core=cls(Config.from_dict(data['config']),seed=data['seed'],start_state=StartState(**data['start_state']),
                 cat_ids=data['cat_ids'],compact=True)
    for item in data['operations']:
        apply_operation(core,item['operation'])
        if core.operations[-1]!=item:raise ValueError('cafe replay mismatch')
    if replay_log(core)!=data:raise ValueError('cafe replay metadata or summary mismatch')
    return core
