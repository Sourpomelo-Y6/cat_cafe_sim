"""派遣先から紹介された猫の情報と、迎える／見送るの選択。"""
class CafeDispatchIntroductionWindow:
    def __init__(self, parent, session, event_id, on_changed):
        import tkinter as tk
        from tkinter import ttk
        from .cafe_history import CafeHistoryWindow
        self.session, self.event_id, self.on_changed = session, event_id, on_changed
        self.parent = parent
        self.window = tk.Toplevel(parent)
        self.window.title('派遣先からの猫紹介')
        self.window.geometry('680x540'); self.window.minsize(560, 420)
        self.window.transient(parent); self.window.grab_set()
        frame = ttk.Frame(self.window, padding=12); frame.pack(fill='both', expand=True)
        footer = ttk.Frame(frame); footer.pack(side='bottom', fill='x', pady=(10, 0))
        self.accept_button = ttk.Button(footer, text='迎える', command=lambda: self.respond('accept'))
        self.accept_button.pack(side='left')
        self.decline_button = ttk.Button(footer, text='見送る', command=lambda: self.respond('decline'))
        self.decline_button.pack(side='left', padx=8)
        from .cafe_housing_gui import add_introduction_housing
        add_introduction_housing(self, footer)
        self.close_button = ttk.Button(footer, text='閉じる', command=self.close)
        self.close_button.pack(side='right')
        self.title, self.notice = tk.StringVar(), tk.StringVar()
        ttk.Label(frame, textvariable=self.title, font=('', 12, 'bold'), wraplength=520).pack(anchor='w')
        ttk.Label(frame, text='派遣先で、新しい居場所を探している猫を紹介されました。\n見送りによる費用・人気・派遣報酬の変化はありません。', wraplength=520).pack(anchor='w', pady=6)
        ttk.Label(frame, textvariable=self.notice, wraplength=520).pack(anchor='w', pady=6)
        self.details = CafeHistoryWindow.table(frame, ('項目', '内容'))
        self.details.column('項目', width=190); self.details.column('内容', width=330)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.window.bind('<Escape>', lambda event: self.close())
        self.refresh()

    def close(self):
        self.window.destroy()
        if self.parent.winfo_exists() and self.parent.master is not None:
            self.parent.grab_set()

    def refresh(self):
        from .core.cafe_dispatch_introduction import response_reason, admission_reason
        from .core.cafe_housing import status as housing_status
        from .core.cafe_preferences import feature_text
        from .core.cafe_traits import description
        from .core.human_cat_types import Personality
        core = self.session.core
        event = core.activities['events'][self.event_id]; data = event['introduction']; row = data['candidate']
        from .cafe_housing_gui import refresh_introduction_housing
        refresh_introduction_housing(self, data['status']=='waiting')
        personality = Personality.from_dict(row['personality'])
        preset = next((name for name, value in self.session.presets.items() if value == personality), 'カスタム')
        self.title.set(f"{event['destination']['name']}から {row['name']}の紹介")
        values = [('名前 / 個性', f"{row['name']} / {preset}"), ('特徴', feature_text(row.get('features', []))),
                  ('飼育スペース', housing_status(core)), ('初期費用', f"{row['cost']:g}"),
                  ('所持金 / 受け入れ後', f"{core.funds:g} / {core.funds-row['cost']:g}"),
                  ('加入時の状態', '健康・体力全回復・休養予定'), ('疲労 / ストレス / 好感度', '0 / 0 / 0（未交流）')]
        values += description(row.get('trait'))
        values += [(f'好み：{kind.name}', f'{value:g}') for kind, value in zip(self.session.interaction_config.types, personality.type_preferences)]
        self.details.delete(*self.details.get_children())
        for value in values: self.details.insert('', 'end', values=value)
        self.accept_button.state(['disabled']); self.decline_button.state(['disabled'])
        if data['status'] in ('accepted', 'declined'):
            self.notice.set(f"{data['resolved_day']}日目に" + ('迎えました。現在の状態は猫の詳細で確認できます。' if data['status']=='accepted' else '見送りました。回答は変更できません。'))
            return
        problem = '先に交流結果の保存を再試行してください。' if self.session.pending else response_reason(core, self.event_id)
        if problem:
            self.notice.set(problem); return
        self.decline_button.state(['!disabled'])
        problem = admission_reason(core, self.event_id)
        self.accept_button.state(['disabled'] if problem else ['!disabled'])
        self.notice.set(problem + ' 見送ることができます。' if problem else '迎えるか見送るかを選ぶと営業準備を続けられます。')

    def respond(self, choice):
        from tkinter import messagebox
        row = self.session.core.activities['events'][self.event_id]['introduction']['candidate']
        prompt = (f"{row['name']}を迎えますか？\n初期費用：{row['cost']:g}\n加入時は休養予定です。" if choice=='accept'
                  else f"{row['name']}の受け入れを見送りますか？\n費用・人気・派遣報酬への影響はありません。")
        if not messagebox.askyesno('派遣先からの猫紹介', prompt, parent=self.window): return
        try: self.session.resolve_dispatch_introduction(self.event_id, choice)
        except (ValueError, OSError) as exc: messagebox.showerror('回答できません', str(exc), parent=self.window)
        self.on_changed(); self.refresh()
