"""保護猫の候補・個性・費用を確認して受け入れる画面。"""
from .core.human_cat_types import Personality


class CafeRecruitmentWindow:
    def __init__(self, parent, session, on_changed):
        import tkinter as tk
        from tkinter import ttk
        from .cafe_history import CafeHistoryWindow
        self.session, self.on_changed = session, on_changed
        self.window = tk.Toplevel(parent)
        self.window.title('保護猫の受け入れ')
        self.window.geometry('800x560')
        self.window.minsize(500, 440)
        self.window.transient(parent)
        self.window.grab_set()
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        footer = ttk.Frame(frame)
        footer.pack(side='bottom', fill='x')
        self.receive_button = ttk.Button(footer, text='選んだ猫を受け入れる', command=self.receive)
        self.receive_button.pack(side='left')
        self.close_button = ttk.Button(footer, text='閉じる', command=self.window.destroy)
        self.close_button.pack(side='right')
        self.funds = tk.StringVar()
        ttk.Label(frame, textvariable=self.funds).pack(anchor='w')
        ttk.Label(frame, text='準備中に受け入れます。加入時は健康・体力全回復・休養予定です。3日ごとに候補を3匹追加します。以前の候補も残ります。', wraplength=460).pack(anchor='w')
        self.schedule = tk.StringVar()
        ttk.Label(frame, textvariable=self.schedule, wraplength=460).pack(anchor='w')
        self.notice = tk.StringVar()
        ttk.Label(frame, textvariable=self.notice, wraplength=460).pack(anchor='w')
        self.cats = CafeHistoryWindow.table(frame, ('名前', '個性', '特性', '初期費用', '状態'))
        self.details = CafeHistoryWindow.table(frame, ('項目', '値'))
        self.details.column('項目', width=230)
        self.details.column('値', width=220)
        self.cats.bind('<<TreeviewSelect>>', lambda event: self.selection_changed())
        self.window.bind('<Escape>', lambda event: self.window.destroy())
        self.refresh()

    def refresh(self):
        core = self.session.core
        self.funds.set(f'所持金：{core.funds:g}')
        from .core.cafe_recruitment import next_candidate_day
        due = next_candidate_day(core.recruitment)
        self.schedule.set(f'次の候補追加：{due}日目（準備中にこの画面を開くと追加）')
        selected = self.cats.selection()
        self.cats.delete(*self.cats.get_children())
        for key, row in core.recruitment['candidates'].items():
            personality = Personality.from_dict(row['personality'])
            label = next((name for name, value in self.session.presets.items() if value == personality), 'カスタム')
            day = core.recruitment['accepted'].get(key)
            self.cats.insert('', 'end', iid=key, values=(row['name'], label, row.get('trait',{}).get('name','なし'), f"{row['cost']:g}", f'{day}日目に受入済み' if day else '候補'))
        self.cats.selection_set(selected[0] if selected else next(iter(core.recruitment['candidates'])))
        self.selection_changed()

    def selection_changed(self):
        from .core.cafe_recruitment import require_preparation
        core = self.session.core
        selected = self.cats.selection()
        self.details.delete(*self.details.get_children())
        self.receive_button.state(['disabled'])
        if not selected:
            self.notice.set('候補を選んでください。')
            return
        key = selected[0]
        row = core.recruitment['candidates'][key]
        personality = Personality.from_dict(row['personality'])
        from .core.cafe_traits import description
        values = description(row.get('trait')) + [('猫ID', key), ('提示日', f"{core.recruitment.get('presented_days', {}).get(key, core.recruitment['opened_day'])}日目"), ('体力', f'{core.config.max_stamina:g} / {core.config.max_stamina:g}'),
                  ('疲労 / ストレス', '0 / 0'), ('体調 / 出勤予定', '健康 / 休養'),
                  ('プレイヤー・お客への好感度', '0（未交流）')]
        values += [(f'好み：{kind.name}', f'{value:g}') for kind, value in zip(self.session.interaction_config.types, personality.type_preferences)]
        values += [(f'強さの好み：{name}', f'{value:g}') for name, value in zip(('穏やか', '普通', '活発'), personality.intensity_preferences)]
        values += [('飽きやすさ', f'{personality.boredom_decay:g}'), ('種類切り替えへの反応', f'{personality.switch_affinity:g}')]
        for value in values:
            self.details.insert('', 'end', values=value)
        if key in core.recruitment['accepted']:
            self.notice.set('受け入れ済みです。上の能力は加入時の値です。現在の状態は「猫の詳細…」で確認できます。')
            return
        reason = ''
        try:
            require_preparation(core)
        except ValueError as exc:
            reason = str(exc)
        if self.session.pending:
            reason = '接客結果の保存を再試行してください。'
        if not reason and core.funds <= row['cost']:
            reason = '受け入れ後に資金が残る必要があります。'
        self.notice.set(reason or f"初期費用 {row['cost']:g} / 受け入れ後の所持金 {core.funds - row['cost']:g}。出勤予定は加入後に設定できます。")
        self.receive_button.state(['disabled'] if reason else ['!disabled'])

    def receive(self):
        from tkinter import messagebox
        selected = self.cats.selection()
        if not selected:
            return
        core = self.session.core
        row = core.recruitment['candidates'][selected[0]]
        if not messagebox.askyesno('保護猫の受け入れ',
                f"{row['name']}を迎えますか？\n初期費用：{row['cost']:g}\n受け入れ後の所持金：{core.funds - row['cost']:g}\n加入時は休養予定です。", parent=self.window):
            return
        try:
            self.session.recruit_cat(selected[0])
        except (ValueError, OSError) as exc:
            messagebox.showerror('受け入れできません', str(exc), parent=self.window)
        self.on_changed()
        self.refresh()
