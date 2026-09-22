"""固定日の受け入れ依頼と回答履歴。"""
class CafeIntakeRequestWindow:
    def __init__(self, parent, session, on_changed):
        import tkinter as tk
        from tkinter import ttk
        from .cafe_history import CafeHistoryWindow
        self.session, self.on_changed = session, on_changed
        self.parent = parent
        self.window = tk.Toplevel(parent)
        self.window.title('保護猫の受け入れ依頼')
        self.window.geometry('640x520')
        self.window.minsize(560, 420)
        self.window.transient(parent)
        self.window.grab_set()
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        footer = ttk.Frame(frame)
        footer.pack(side='bottom', fill='x', pady=(10, 0))
        self.accept_button = ttk.Button(footer, text='迎える', command=lambda: self.respond('accept'))
        self.accept_button.pack(side='left')
        self.decline_button = ttk.Button(footer, text='見送る', command=lambda: self.respond('decline'))
        self.decline_button.pack(side='left', padx=8)
        self.close_button = ttk.Button(footer, text='閉じる', command=self.close)
        self.close_button.pack(side='right')
        self.title = tk.StringVar()
        ttk.Label(frame, textvariable=self.title, font=('', 12, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='保護猫の新しい居場所を探しています。迎えるか見送るかを選んでください。\n見送っても費用や人気への影響はありません。', wraplength=520).pack(anchor='w', pady=6)
        self.notice = tk.StringVar()
        ttk.Label(frame, textvariable=self.notice, wraplength=520).pack(anchor='w', pady=6)
        self.details = CafeHistoryWindow.table(frame, ('項目', '内容'))
        self.details.column('項目', width=190)
        self.details.column('内容', width=330)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.window.bind('<Escape>', lambda event: self.close())
        self.refresh()

    def close(self):
        self.window.destroy()
        if self.parent.winfo_exists() and self.parent.winfo_toplevel() is self.parent and self.parent.master is not None:
            self.parent.grab_set()

    def refresh(self):
        from .core.cafe_intake_request import pending, require_response
        from .core.cafe_preferences import feature_text
        from .core.cafe_traits import description
        from .core.human_cat_types import Personality
        core = self.session.core
        data = core.intake_request
        rule, status = data['rules'], data['status']
        row = rule['candidate']
        personality = Personality.from_dict(row['personality'])
        preset = next((name for name, value in self.session.presets.items() if value == personality), 'カスタム')
        self.title.set(f"{row['name']}の受け入れ依頼 · {rule['day']}日目")
        self.details.delete(*self.details.get_children())
        values = [('名前 / 個性', f"{row['name']} / {preset}"), ('特徴', feature_text(row.get('features', [])))]
        values += description(row.get('trait'))
        values += [('初期費用', f"{row['cost']:g}"), ('加入時の状態', '健康・体力全回復・休養予定'), ('疲労 / ストレス / 好感度', '0 / 0 / 0（未交流）')]
        values += [(f'好み：{kind.name}', f'{value:g}') for kind, value in zip(self.session.interaction_config.types, personality.type_preferences)]
        for value in values:
            self.details.insert('', 'end', values=value)
        self.accept_button.state(['disabled'])
        self.decline_button.state(['disabled'])
        if not pending(core):
            self.notice.set({'scheduled': 'まだ依頼は届いていません。', 'accepted': f"{data['resolved_day']}日目に迎えました。現在の状態は猫の詳細で確認できます。", 'declined': f"{data['resolved_day']}日目に見送りました。この依頼は再発生しません。"}[status])
            return
        try:
            require_response(core)
            if self.session.pending:
                raise ValueError('先に交流結果の保存を再試行してください。')
        except ValueError as exc:
            self.notice.set(str(exc))
            return
        self.decline_button.state(['!disabled'])
        if core.funds <= row['cost']:
            self.notice.set(f'所持金 {core.funds:g}。受け入れ後に資金が残る必要があります。見送ることができます。')
        else:
            self.accept_button.state(['!disabled'])
            self.notice.set(f"所持金 {core.funds:g} → 受け入れ後 {core.funds-row['cost']:g}。回答すると営業準備を続けられます。")

    def respond(self, choice):
        from tkinter import messagebox
        data = self.session.core.intake_request
        row = data['rules']['candidate']
        prompt = f"{row['name']}を迎えますか？\n初期費用：{row['cost']:g}\n加入時は休養予定です。" if choice == 'accept' else f"{row['name']}の受け入れを見送りますか？\nこの依頼は再発生しません。"
        if not messagebox.askyesno('受け入れ依頼への回答', prompt, parent=self.window):
            return
        try:
            self.session.resolve_intake_request(choice)
        except (ValueError, OSError) as exc:
            messagebox.showerror('回答できません', str(exc), parent=self.window)
        self.on_changed()
        self.refresh()
