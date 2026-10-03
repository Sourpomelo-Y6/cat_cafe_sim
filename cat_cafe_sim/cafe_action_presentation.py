"""ゲームを変更せず、試作画像に対応する現在の状態だけを抽出する。"""


def interaction_scene(records):
    if not records:
        return 'normal'
    record = records[-1]
    if record['action'] not in ('direct', 'adapt', 'intense', 'feint', 'gentle'):
        return 'normal'
    if record.get('normal_reaction', record.get('reaction')) in ('turn_away', 'listless', 'confused'):
        return 'normal'
    return {'teaser': 'play', 'pet': 'pet'}.get(record['before']['mode'], 'normal')


def current_scene(session, cat_id=None):
    core = session.core
    if cat_id not in core.cats:
        cat_id = 'playtest-mike' if 'playtest-mike' in core.cats else next(iter(core.cats), None)
    if cat_id is None:
        return dict(scene='normal', cat_id=None, name='対象なし', room='対象なし', status='猫がいません。')
    name = session.profiles.get(cat_id, {}).get('name', cat_id)
    result = dict(scene='normal', cat_id=cat_id, name=name, room='接客スペース', status='待機中')
    if core.activity(cat_id) != 'cafe':
        result.update(room='店外', status='在店していません（通常画像で代替）')
        return result
    # 準備中のプレイヤー交流は出勤予定より優先する。
    player = (core.player_bond or {}).get('active')
    if player and player['initial_relationship']['cat_id'] == cat_id:
        result.update(scene=interaction_scene(player['records']), status='プレイヤーと交流中')
        return result
    if core.cats[cat_id].health_status == 'sick':
        result.update(scene='sleep', room='療養スペース', status='療養中（眠る画像で代替）')
        return result
    if cat_id not in core.working_cats:
        result.update(scene='sleep', room='休養スペース', status='休養中')
        return result
    interaction = next((item for item in session.active_interactions.values() if item.cat_id == cat_id), None)
    if interaction is not None:
        result.update(scene=interaction_scene(interaction.records), status='お客さんと交流中')
    return result
