"""好感度・有力者の検証用に、通常操作だけで目標を進める。"""
from .core import cafe_player, cafe_housing, cafe_activities


def prepare(player):
    s, c = player.session, player.session.core
    if player.mode == 'basic':
        return None
    if player.objective == 'bond':
        goal = c.bond_goal
        present = [key for key in c.cats if c.activity(key) != 'adopted']
        if len(present) < goal['rules']['target']:
            from .cafe_autoplay_strategy import reserve
            if not cafe_housing.admission_reason(c):
                if c.recruitment is None:
                    player._decision('保護猫', '候補を確認', '好感度目標に必要な在籍数を確保する')
                    return '好感度目標のため保護猫の候補を確認', s.open_recruitment
                for key, row in sorted(c.recruitment['candidates'].items()):
                    if key not in c.cats and key not in c.recruitment['accepted'] and c.funds > row['cost'] and c.funds-row['cost'] >= reserve(c):
                        player._decision(row['name'], '受け入れ', f"目標{goal['rules']['target']}匹に対し在籍{len(present)}匹。予備資金を確保", key)
                        return f"好感度目標のため{row['name']}を受け入れ", lambda key=key: s.recruit_cat(key)
        affinity = cafe_player.state(c)['affinity']
        eligible = [key for key in c.cats if affinity[key] < goal['rules']['affinity']
                    and not cafe_player.unavailable_reason(c, key)]
        if eligible:
            key = min(eligible, key=lambda key: (affinity[key], key))
            player._decision(s.profiles[key]['name'], '交流', f"好感度{affinity[key]:g}、目標{goal['rules']['affinity']:g}。未達の猫から交流", key)
            return f'{s.profiles[key]["name"]}とプレイヤー交流を開始', lambda: s.play_with_player(key)
    elif player.objective == 'patron':
        from .core.cafe_patron import DESTINATION_ID
        events = (c.activities or {}).get('events', {}).values()
        if any(e['destination']['id'] == DESTINATION_ID and e['status'] != 'resolved' for e in events):
            return None
        destination = c.patron['rules']['destination']
        eligible = [key for key in c.cats if not cafe_activities.dispatch_reason(c, key, destination)]
        if eligible:
            key = min(eligible, key=lambda key: (c.cats[key].fatigue, key))
            player._decision(s.profiles[key]['name'], '派遣', '有力者の満足度を増やす。健康・疲労・店内の担当可能猫数の条件を確認', key)
            return f'{s.profiles[key]["name"]}を有力者へ派遣', lambda: s.dispatch(key, destination)
    return None


def player_action(interaction):
    """公開ルールで2手まで試し、好感度を増やせる交流を選ぶ。実状態は変更しない。"""
    import copy
    valid = interaction.valid_actions()
    if 'connect' in valid:
        return 'connect', None
    if interaction.state['stamina'] <= 20:
        return 'pause', None
    options = [(action, None) for action in valid if action != 'switch']
    if 'switch' in valid:
        options += [('switch', key) for key in interaction.type_map if key != interaction.state['mode']]
    ranked = []
    for index, (action, target) in enumerate(options):
        trial = copy.deepcopy(interaction)
        trial.step(action, target)
        futures = [trial]
        if not trial.state['end_reason']:
            futures = []
            for follow in trial.valid_actions():
                if follow == 'switch':
                    continue
                future = copy.deepcopy(trial)
                future.step(follow)
                futures.append(future)
        score = max((future.state['affinity_pending']-interaction.state['affinity_pending'],
                     future.state['stamina']) for future in futures)
        ranked.append((score, -index, action, target))
    _, _, action, target = max(ranked)
    return action, target
