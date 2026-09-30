"""開始画面の目標説明と、選んだ目標の進捗表示。"""
from .core.cafe_objective import MODES


def description(conditions, mode):
    if mode == 'popularity':
        rules = conditions['goal']
        stages = [rules] + rules.get('stages', [])
        return ' → '.join(f"人気{r['target']:g}（{r['days']}日間）" for r in stages) + '。段階ごとに次の挑戦か自由営業を選べます。第1段階達成で白猫好きのこだわり客が解放されます。'
    if mode == 'patron':
        rules = conditions['patron']
        return f"{rules['name']}への派遣で満足度{rules['target']:g}を目指します。期限なし。帰還報酬の受取時に加算します。"
    if mode == 'bond':
        rules = conditions['bond']
        return f"プレイヤーへの好感度{rules['affinity']:g}以上の在籍猫を同時に{rules['target']}匹。期限なし。猫を迎え、準備中の交流で親しくなります。人気3段階への挑戦も任意で追加できます。"
    if mode == 'free':
        return '開始時のクリア目標・期限はありません。営業、猫との交流、派遣などを自由に続けられます。準備中に人気3段階への挑戦も開始できます。'
    raise ValueError('目標を選んでください。')


def progress(core):
    if core.objective == 'patron':
        from .core.cafe_patron import progress
        return progress(core)
    if core.objective == 'bond':
        from .core.cafe_bond_goal import progress
        text = progress(core)
        if 'challenge_started_day' in (core.goal or {}):
            from .cafe_goal_gui import progress as popularity_progress
            text += '\n' + popularity_progress(core)
        return text
    if core.objective == 'free':
        if 'challenge_started_day' in (core.goal or {}):
            from .cafe_goal_gui import progress
            return '自由営業から挑戦 · '+progress(core)
        return '自由営業 · クリア目標・期限なし'
    from .cafe_goal_gui import progress
    return progress(core)
