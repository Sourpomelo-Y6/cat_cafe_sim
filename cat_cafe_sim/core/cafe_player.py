"""営業ごとのプレイヤー好感度と、準備中に使う一日の交流枠。"""
import copy

DAILY_TURNS = 3
SET_TICKS = 10
AFFINITY_GAIN = 5
MAX_AFFINITY = 100


def state(core):
    return core.player_bond or dict(affinity=dict.fromkeys(core.cats, 0),
                                   today=dict.fromkeys(core.cats, 0),
                                   total=dict.fromkeys(core.cats, 0))


def remaining(core):
    return DAILY_TURNS - sum(state(core)['today'].values())


def unavailable_reason(core, cat_id):
    from .cafe_activities import waiting_events
    if active(core) is not None:
        return '進行中のプレイヤー交流を再開または終了してください。'
    if not core.compact or not core.can_set_shifts:
        return '猫と遊べるのは営業準備中です。'
    if waiting_events(core):
        return '先に帰還結果や譲渡の申し出を確認してください。'
    if cat_id not in core.cats:
        return '営業に参加している猫を選んでください。'
    cat = core.cats[cat_id]
    if core.activity(cat_id) != 'cafe':
        return '在店している猫を選んでください。'
    if cat.health_status != 'healthy' or cat.cannot_continue or cat.stamina <= 0:
        return '療養中・体力切れの猫は遊べません。'
    if remaining(core) <= 0:
        return '本日の交流回数を使い切りました。'
    return ''


def legacy_play(core, cat_id):
    reason = unavailable_reason(core, cat_id)
    if reason:
        raise ValueError(reason)
    if core.player_bond is None:
        core.player_bond = state(core)
    bond = core.player_bond
    before = bond['affinity'][cat_id]
    bond['today'][cat_id] += 1
    bond['total'][cat_id] += 1
    bond['affinity'][cat_id] = min(MAX_AFFINITY, before + AFFINITY_GAIN)
    core._tick_events = []
    core._emit('player_played', cat_id=cat_id, before=before,
               after=bond['affinity'][cat_id], remaining=remaining(core))
    core._record(dict(kind='player_play', cat_id=cat_id))


def validate_legacy(core, data):
    if not isinstance(data, dict) or set(data) != {'affinity', 'today', 'total'}:
        raise ValueError('プレイヤー交流の記録が不正です。')
    for field in data:
        rows = data[field]
        if (not isinstance(rows, dict) or set(rows) != set(core.cats)
                or any(type(v) is not int or v < 0 for v in rows.values())):
            raise ValueError('プレイヤー交流の数値が不正です。')
    if sum(data['today'].values()) > DAILY_TURNS or sum(data['total'].values()) > core.day * DAILY_TURNS:
        raise ValueError('プレイヤー交流の回数が不正です。')
    past = sum(data['total'].values()) - sum(data['today'].values())
    if past > (core.day - 1) * DAILY_TURNS:
        raise ValueError('過去の交流回数が不正です。')
    for key in core.cats:
        count = data['total'][key]
        if (data['today'][key] > count or count > MAX_AFFINITY // AFFINITY_GAIN
                or data['affinity'][key] != min(MAX_AFFINITY, count * AFFINITY_GAIN)):
            raise ValueError('好感度と交流回数が一致しません。')
    return copy.deepcopy(data)


def active(core):
    return (core.player_bond or {}).get('active')


def current(core):
    from .human_cat_relationship import verify_relationship
    log = active(core)
    return verify_relationship(log) if log else None


def begin(core, cat_id, config):
    from .human_cat_relationship import RelationshipConfig, RelationshipInteraction
    reason = unavailable_reason(core, cat_id)
    if reason:
        raise ValueError(reason)
    config = RelationshipConfig.from_dict(config)
    if config.ticks != SET_TICKS or config.max_stamina != core.config.max_stamina:
        raise ValueError('プレイヤー交流のターン数・体力上限が不正です。')
    bond = copy.deepcopy(state(core))
    interaction = RelationshipInteraction(config, cat_id=cat_id, customer_id='player',
        session_id=f"player-{core.day}-{sum(bond['today'].values())+1}",
        affinity=bond['affinity'][cat_id], revision=bond['total'][cat_id],
        stamina=core.cats[cat_id].stamina)
    bond.update(version=2, active=interaction.log(), last=bond.get('last'))
    bond['today'][cat_id] += 1
    bond['total'][cat_id] += 1
    core.player_bond = bond
    core._tick_events = []
    core._emit('player_started', cat_id=cat_id, remaining=remaining(core))
    core._record(dict(kind='player_begin', cat_id=cat_id, config=config.to_dict()))


def advance(core, action=None, target_type=None, *, finish=False):
    interaction = current(core)
    if interaction is None:
        if finish:
            return
        raise ValueError('先にプレイヤー交流を開始してください。')
    # Reconstructed copy: invalid commands never change the saved interaction.
    if finish:
        interaction.finish()
    else:
        interaction.step(action, target_type)
    core._tick_events = []
    bond = core.player_bond
    cat = core.cats[interaction.cat_id]
    cat.stamina = interaction.state['stamina']
    if cat.stamina == 0:
        cat.cannot_continue = True
    if not finish:
        core._emit('player_action', cat_id=cat.id, record=interaction.records[-1])
    if interaction.state['end_reason']:
        result = interaction.result()
        bond['affinity'][cat.id] = result['affinity_after']
        bond['active'] = None
        bond['last'] = interaction.log()
        core._emit('player_completed', cat_id=cat.id, result=result)
    else:
        bond['active'] = interaction.log()
    core._record(dict(kind='player_finish') if finish else
                 dict(kind='player_step', action=action, target_type=target_type))


def validate(core, data):
    import math
    from .human_cat_relationship import verify_relationship
    if isinstance(data, dict) and set(data) == {'affinity', 'today', 'total'}:
        return validate_legacy(core, data)
    if (not isinstance(data, dict) or set(data) != {'version','affinity','today','total','active','last'}
            or type(data['version']) is not int or data['version'] != 2):
        raise ValueError('プレイヤー交流の記録が不正です。')
    for field in ('affinity','today','total'):
        rows = data[field]
        if not isinstance(rows, dict) or set(rows) != set(core.cats):
            raise ValueError('プレイヤー交流の猫が不正です。')
        for value in rows.values():
            if field == 'affinity':
                valid = type(value) in (int,float) and math.isfinite(value) and 0 <= value <= 100
            else:
                valid = type(value) is int and value >= 0
            if not valid:
                raise ValueError('プレイヤー交流の数値が不正です。')
    today, total = sum(data['today'].values()), sum(data['total'].values())
    if (today > DAILY_TURNS or total > core.day * DAILY_TURNS or total-today > (core.day-1)*DAILY_TURNS
            or any(data['today'][key] > data['total'][key] for key in core.cats)):
        raise ValueError('プレイヤー交流のセット数が不正です。')
    for field in ('active','last'):
        log = data[field]
        if log is None:
            continue
        interaction = verify_relationship(log)
        key = interaction.cat_id
        if (key not in core.cats or interaction.customer_id != 'player'
                or interaction.config.ticks != SET_TICKS
                or interaction.config.max_stamina != core.config.max_stamina):
            raise ValueError('プレイヤー交流の対象・設定が不正です。')
        if field == 'active':
            cat = core.cats[key]
            if (core.closed or core.tick != 0 or core.visits or core.activity(key) != 'cafe'
                    or cat.health_status != 'healthy' or cat.cannot_continue
                    or interaction.state['end_reason'] or cat.stamina != interaction.state['stamina']
                    or data['today'][key] < 1 or interaction.initial_relationship['affinity'] != data['affinity'][key]
                    or interaction.initial_relationship['revision']+1 != data['total'][key]
                    or interaction.session_id != f"player-{core.day}-{today}"):
                raise ValueError('進行中のプレイヤー交流が不正です。')
        else:
            result = interaction.result()
            if result['affinity_after'] != data['affinity'][key]:
                raise ValueError('前回の交流結果と好感度が一致しません。')
    return copy.deepcopy(data)
