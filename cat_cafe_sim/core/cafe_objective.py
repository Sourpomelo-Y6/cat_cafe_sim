"""開始時に選んだ目標。各目標の成果・継続処理は既存機能を使う。"""
MODES = {'popularity': '人気3段階', 'patron': '有力者の満足度', 'bond': '猫6匹との好感度', 'free': '自由営業'}


def validate(core, mode):
    if not isinstance(mode, str) or mode not in MODES or not core.management or not core.goal:
        raise ValueError('開始時の目標設定が不正です。')
    if core.goal['started_day'] != 1 or core.management['started_day'] != 1:
        raise ValueError('新規ゲームの目標・経営開始日は1日目です。')
    challenge='challenge_started_day' in core.goal
    if challenge and (mode not in ('free','bond') or core.goal.get('tracking_only')
            or 'stages' not in core.goal['rules'] or any(getattr(core,key) is None for key in
                ('advanced_customers','reservation','quiet_customer','play_customer','contact_customer','vip_customer'))):
        raise ValueError('途中開始の人気挑戦と追加客設定が一致しません。')
    if not challenge and (mode == 'popularity') == bool(core.goal.get('tracking_only')):
        raise ValueError('選択した目標と人気の期限設定が一致しません。')
    data = core.patron if mode == 'patron' else core.bond_goal if mode == 'bond' else None
    if mode in ('patron', 'bond') and (not data or data['started_day'] != 1):
        raise ValueError('選択したクリア目標が開始されていません。')
    return mode


def initialize(core, mode):
    core.require_events_resolved()
    if core.objective is not None or core.day != 1 or not core.can_set_shifts or not core.compact:
        raise ValueError('開始時の目標は新規ゲームの準備時に一度だけ記録できます。')
    core.objective = validate(core, mode)
    core._tick_events=[]
    core._emit('objective_selected', mode=mode)
    core._record(dict(kind='initialize_objective', mode=mode))
