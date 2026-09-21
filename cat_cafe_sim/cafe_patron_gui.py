"""有力者の満足度目標の開始・進捗・クリア確認。"""
from .core.cafe_patron import rules, pending, progress
from .core.cafe_management import is_over


class CafePatronWindow:
    def __init__(self, parent, session, on_changed):
        import tkinter as tk
        from tkinter import ttk
        self.session, self.on_changed = session, on_changed
        self.window = tk.Toplevel(parent)
        self.window.title('有力者目標・結果')
        self.window.geometry('580x360')
        self.window.minsize(500, 320)
        self.window.transient(parent)
        self.window.grab_set()
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        footer = ttk.Frame(frame)
        footer.pack(side='bottom', fill='x')
        self.enable_button = ttk.Button(footer, text='目標を開始', command=self.enable)
        self.enable_button.pack(side='left')
        self.continue_button = ttk.Button(footer, text='結果を確認して営業を続ける', command=self.resume)
        self.continue_button.pack(side='left', padx=4)
        self.close_button = ttk.Button(footer, text='閉じる', command=self.window.destroy)
        self.close_button.pack(side='right')
        self.status, self.details, self.notice = tk.StringVar(), tk.StringVar(), tk.StringVar()
        for var in (self.status, self.details, self.notice):
            ttk.Label(frame, textvariable=var, wraplength=460).pack(anchor='w', pady=8)
        self.window.bind('<Escape>', lambda event: self.window.destroy())
        self.refresh()

    def refresh(self):
        from .core.cafe_activities import waiting_events
        core = self.session.core
        data = core.patron
        selected = data['rules'] if data else rules()
        trip = selected['destination']
        self.status.set(progress(core))
        self.details.set(f"{selected['name']}への派遣帰還を受け取ると満足度＋{selected['gain']:g}。{selected['target']:g}でクリアです。期限はありません。\n派遣は{trip['days']}日・基本報酬{trip['reward']:g}・疲労{trip['max_fatigue']:g}以下。通常の健康・余剰猫条件も適用します。\n人気目標とは独立して達成でき、クリア後も営業を続けられます。")
        reason = ''
        try:
            core.require_events_resolved()
        except ValueError as exc:
            reason = str(exc)
        blocked = bool(self.session.pending) or bool(waiting_events(core)) or is_over(core)
        self.enable_button.state(['!disabled'] if not data and core.management and core.can_set_shifts and not reason and not blocked else ['disabled'])
        self.continue_button.state(['!disabled'] if pending(core) and not blocked else ['disabled'])
        self.notice.set('ゲームオーバーです。新規ゲームから再開してください。' if is_over(core) else
                        '先に接客結果の保存・帰還・譲渡イベントの確認を完了してください。' if blocked else
                        '先に経営ルールを開始してください。' if not core.management else
                        f"{data['resolved_day']}日目に目標達成！" if data and data['status'] == 'cleared' else
                        '開始後は派遣先一覧から有力者への訪問を選べます。開始は準備中に一度だけ可能です。')

    def perform(self, action):
        from tkinter import messagebox
        try:
            action()
        except (ValueError, OSError) as exc:
            messagebox.showerror('有力者目標を操作できません', str(exc), parent=self.window)
        self.on_changed()
        self.refresh()

    def enable(self):
        from tkinter import messagebox
        selected = rules()
        if messagebox.askyesno('有力者目標を開始', f"{selected['name']}の満足度{selected['target']:g}を目指します。期限なし・開始後の取消はできません。開始しますか？", parent=self.window):
            self.perform(lambda: self.session.enable_patron(selected))

    def resume(self):
        self.perform(self.session.continue_patron)
