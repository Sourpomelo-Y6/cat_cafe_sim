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
    basic = [('名前', profile['name'] if profile else cat_id), ('猫ID', cat_id),
             ('個性', label if profile else f'{label}（未登録・営業の既定個性）'),
             ('体力', f'{cat.stamina:g} / {core.config.max_stamina:g}'),
             ('疲労', number(cat.fatigue) if core.shift_rules else 'ルール未導入'),
             ('体調', health_text(cat.health_status, cat.recovery_days_remaining)),
             ('出勤予定', '出勤' if cat_id in core.working_cats else '休養'), ('担当状態', status)]
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
                        {'work':'出勤','rest':'休養'}.get(row.get('shift'), MISSING),
                        number(row.get('interactions')), number(row.get('service_ticks')), number(row.get('spent')),
                        fatigue, health_result_text(row['health']) if row.get('health') else MISSING, number(delta)))
    return dict(basic=basic, relationships=relationships, history=history,
                pending=bool(session.pending))


class CafeCatDetailsWindow:
    def __init__(self, parent, session, cat_id):
        import tkinter as tk
        from tkinter import ttk
        from .cafe_history import CafeHistoryWindow
        self.session = session
        self.window = tk.Toplevel(parent)
        self.window.title('猫の詳細')
        self.window.geometry('820x540')
        self.window.minsize(500, 400)
        self.window.transient(parent)
        self.window.grab_set()
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        self.close_button = ttk.Button(frame, text='閉じる', command=self.window.destroy)
        self.close_button.pack(side='bottom', anchor='e', pady=(8, 0))
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
            ('basic', '状態・個性', ('項目', '値'), '現在の状態と好みです。値はこの画面では編集しません。'),
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

    def refresh(self):
        from tkinter import messagebox
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
