"""猫別の閲覧データ。過去の詳細行動を日次集計から推定しない。"""
from .core.human_cat_types import Personality
from .cafe_health_text import health_text, health_result_text
from .relationship_presentation import STAGES, stage_index

MISSING = '記録なし'


def number(value):
    return MISSING if value is None else f'{value:g}'


def cat_details(session, cat_id):
    core = session.core
    cat = core.cats[cat_id]
    profile = session.profiles.get(cat_id)
    personality = Personality.from_dict(profile['personality']) if profile else session.interaction_config.personality
    label = next((name for name, value in session.presets.items() if value == personality), 'カスタム')
    active = any(item.cat_id == cat_id for item in session.active_interactions.values())
    status = ('療養' if cat.health_status == 'sick' else '休養' if cat_id not in core.working_cats else
              '交流中' if active else '担当可能' if cat in session.available_cats() else '交流不可')
    from .core.cafe_activities import ACTIVITY_LABELS
    if core.activity(cat_id)!='cafe':status=ACTIVITY_LABELS[core.activity(cat_id)]
    basic = [('名前', profile['name'] if profile else cat_id), ('猫ID', cat_id),
             ('個性', label if profile else f'{label}（未登録・営業の既定個性）'),
             ('体力', f'{cat.stamina:g} / {core.config.max_stamina:g}'),
             ('疲労', number(cat.fatigue) if core.shift_rules else 'ルール未導入'),
             ('体調', health_text(cat.health_status, cat.recovery_days_remaining)),
             ('活動', ACTIVITY_LABELS[core.activity(cat_id)]), ('出勤予定', '対象外' if core.activity(cat_id)!='cafe' else '出勤' if cat_id in core.working_cats else '休養'), ('担当状態', status)]
    from .core.cafe_player import state as player_state, remaining
    bond = player_state(core)
    basic += [('プレイヤーへの好感度', f"{bond['affinity'][cat_id]:g} / 100"),
              ('プレイヤー交流の累計セット数', str(bond['total'][cat_id])),
              ('本日この猫とのセット数', str(bond['today'][cat_id])),
              ('本日の残りセット数（店全体）', str(remaining(core)))]
    basic += [('ストレス', f"{core.management['stress'][cat_id]:g} / 100" if core.management else 'ルール未導入')]
    if core.recruitment and cat_id in core.recruitment['accepted']:
        basic += [('加入経路', '保護猫の受け入れ'), ('加入日', f"{core.recruitment['accepted'][cat_id]}日目")]
    if core.adoption:
        adopted = next((event for event in core.adoption['events'].values()
                        if event['cat_id']==cat_id and event['choice']=='accept'), None)
        if adopted:
            basic += [('譲渡先', adopted['customer_id']), ('譲渡成立日', f"{adopted['resolved_day']}日目")]
    basic += [(f'好み：{kind.name}', number(value)) for kind, value in
              zip(session.interaction_config.types, personality.type_preferences)]
    basic += [(f'強さの好み：{name}', number(value)) for name, value in
              zip(('穏やか', '普通', '活発'), personality.intensity_preferences)]
    basic += [('飽きやすさ', number(personality.boredom_decay)), ('種類切り替えへの反応', number(personality.switch_affinity))]
    pairs = session.store.list_relationships()
    known = {p['customer_id'] for p in pairs} | set(core.visits) | core.returning_customers
    selected = {p['customer_id']: p for p in pairs if p['cat_id'] == cat_id}
    relationships = []
    for customer_id in sorted(known):
        pair = selected.get(customer_id)
        affinity = pair['affinity'] if pair else 0
        relationships.append((customer_id, number(affinity), STAGES[stage_index(affinity)],
                              '交流済み' if pair and pair['revision'] else '未交流'))
    days = list(core.day_results)
    if core.closed:
        days.append(core.day_result())
    history = []
    for day in days:
        row = day.get('cats', {}).get(cat_id)
        if row is None:
            continue
        changes = day.get('affinity_changes')
        delta = None if changes is None else sum(item['change'] for item in changes if item['cat_id'] == cat_id)
        fatigue = (f"{row['fatigue_before']:g} → {row['fatigue_after']:g}"
                   if 'fatigue_before' in row and 'fatigue_after' in row else MISSING)
        history.append((day['day'], '休業' if day.get('day_type') == 'day_off' else '営業',
                        ACTIVITY_LABELS[row['activity']] if row.get('activity','cafe')!='cafe' else {'work':'出勤','rest':'休養'}.get(row.get('shift'), MISSING),
                        number(row.get('interactions')), number(row.get('service_ticks')), number(row.get('spent')),
                        fatigue, health_result_text(row['health']) if row.get('health') else MISSING, number(delta)))
    return dict(basic=basic, relationships=relationships, history=history,
                pending=bool(session.pending))


class CafeCatDetailsWindow:
    def __init__(self, parent, session, cat_id, on_changed=None):
        import tkinter as tk
        from tkinter import ttk
        from .cafe_history import CafeHistoryWindow
        self.session = session
        self.on_changed = on_changed or (lambda: None)
        self.window = tk.Toplevel(parent)
        self.window.title('猫の詳細')
        self.window.geometry('820x540')
        self.window.minsize(500, 400)
        self.window.transient(parent)
        self.window.grab_set()
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        footer = ttk.Frame(frame)
        footer.pack(side='bottom', fill='x', pady=(8, 0))
        self.play_notice = tk.StringVar()
        ttk.Label(footer, textvariable=self.play_notice, wraplength=460).pack(anchor='w')
        self.play_button = ttk.Button(footer, text='交流を始める（1セット）', command=self.play)
        self.play_button.pack(side='left')
        self.close_button = ttk.Button(footer, text='閉じる', command=self.window.destroy)
        self.close_button.pack(side='right')
        self.ids = list(session.core.cats)
        labels = [f"{session.profiles.get(key, {}).get('name', key)}（{key}）" for key in self.ids]
        self.selector = ttk.Combobox(frame, values=labels, state='readonly')
        self.selector.pack(fill='x')
        self.selector.current(self.ids.index(cat_id))
        self.notice = tk.StringVar()
        ttk.Label(frame, textvariable=self.notice, wraplength=460).pack(anchor='w', pady=4)
        notebook = self.notebook = ttk.Notebook(frame)
        notebook.pack(fill='both', expand=True)
        self.tables = {}
        for key, title, columns, note in (
            ('basic', '状態・個性', ('項目', '値'), '現在の状態と好みです。準備中は下のボタンで一緒に遊べます。'),
            ('relationships', 'お客との親しみ', ('お客ID','確定済み親しみ','段階','交流経験'),
             '関係データに保存済みの値です。交流中・未保存の変化は含みません。'),
            ('history', '日次実績', ('日目','営業区分','予定','接客件数','接客行動数','体力消耗','疲労変化','体調変化','親しみ増減合計'),
             '閉店済みの日次実績です。個々の行動履歴ではありません。体力消耗は回復を差し引いた値です。')):
            tab = ttk.Frame(notebook, padding=4)
            notebook.add(tab, text=title)
            ttk.Label(tab, text=note, wraplength=440).pack(anchor='w')
            self.tables[key] = CafeHistoryWindow.table(tab, columns)
        self.tables['basic'].column('項目', width=220)
        self.tables['basic'].column('値', width=400)
        self.selector.bind('<<ComboboxSelected>>', lambda event:self.refresh())
        self.window.bind('<Escape>', lambda event:self.window.destroy())
        self.refresh()

    def play(self):
        from tkinter import messagebox
        from .core.cafe_player import active
        from .cafe_player_gui import CafePlayerWindow
        try:
            if not active(self.session.core):
                self.session.play_with_player(self.ids[self.selector.current()])
        except (ValueError, OSError) as exc:
            messagebox.showerror('猫と遊べません', str(exc), parent=self.window)
            self.refresh()
            return
        self.on_changed()
        self.refresh()
        self.player_window = CafePlayerWindow(self.window, self.session, self.changed)

    def changed(self):
        self.on_changed()
        if self.window.winfo_exists():
            self.refresh()

    def refresh(self):
        from tkinter import messagebox
        from .core.cafe_player import unavailable_reason, remaining, active
        running = bool(active(self.session.core))
        reason = ('先に交流結果の保存を再試行してください。' if self.session.pending else
                  '' if running else unavailable_reason(self.session.core, self.ids[self.selector.current()]))
        self.play_button.configure(text='進行中の交流を開く' if running else '交流を始める（1セット）')
        self.play_button.state(['disabled'] if reason else ['!disabled'])
        self.play_notice.set(f'本日の交流：残り{remaining(self.session.core)}セット（店全体） · ' +
                             (reason or '1セット最大10ターン。コマンドを選んで遊びます。'))
        try:
            data = cat_details(self.session, self.ids[self.selector.current()])
        except (ValueError, OSError) as exc:
            for tree in self.tables.values():
                tree.delete(*tree.get_children())
            self.notice.set('情報を読み込めません。営業画面で保存状態を確認してください。')
            messagebox.showerror('猫の情報を表示できません', str(exc), parent=self.window)
            return
        self.notice.set('未保存の交流成果があります。営業画面で保存を再試行してください。' if data['pending'] else
                        '閲覧中は営業が一時停止します。閉じた後は営業画面で再開してください。')
        for key, tree in self.tables.items():
            tree.delete(*tree.get_children())
            for row in data[key]:
                tree.insert('', 'end', values=row)
            if not data[key]:
                tree.insert('', 'end', values=('記録なし',))
