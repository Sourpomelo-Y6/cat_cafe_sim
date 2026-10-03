"""好感度・有力者の検証用に、通常操作だけで目標を進める。"""
from .core import cafe_player, cafe_housing, cafe_activities
from .cafe_autoplay_player import player_action


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
        from .core.cafe_patron import destinations
        from .core.cafe_patron_members import terms
        choices = destinations(c)
        ids = {row['id'] for row in choices}
        events = (c.activities or {}).get('events', {}).values()
        if any(e['destination']['id'] in ids and e['status'] != 'resolved' for e in events):
            return None
        for destination in choices:
            key = destination['id']
            if key == c.patron['rules']['destination']['id']:
                satisfied = c.patron['satisfaction'] >= c.patron['rules']['target']
            else:
                member = next(r for r in c.patron['rules']['members'] if r['id']==key)
                satisfied = c.patron['members'][key] >= member['target']
            if satisfied:
                continue
            eligible = [cat for cat in c.cats if not cafe_activities.dispatch_reason(c, cat, destination)]
            eligible = [cat for cat in eligible if terms(c, cat, key) is None or terms(c, cat, key)['gain'] > 0]
            from .cafe_autoplay_patron import dispatch_reason
            eligible = [cat for cat in eligible if not dispatch_reason(c, cat)]
            if eligible:
                cat = min(eligible, key=lambda cat: (-(terms(c, cat, key) or {}).get('gain', 0), c.cats[cat].fatigue, cat))
                note = '健康・疲労・余剰猫条件を確認'
                if terms(c, cat, key):
                    from .core.cafe_patron_members import description
                    note += ' / '+description(c, cat, key)
                player._decision(s.profiles[cat]['name'], '派遣', destination['name']+'。'+note, cat)
                return f'{s.profiles[cat]["name"]}を{destination["name"]}へ派遣', lambda cat=cat, destination=destination: s.dispatch(cat, destination)
    return None
