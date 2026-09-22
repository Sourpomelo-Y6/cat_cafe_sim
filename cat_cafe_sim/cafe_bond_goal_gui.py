"""好感度目標の開始、猫別進捗、達成確認。"""
from .core.cafe_bond_goal import rules, pending, progress, qualifying
from .core.cafe_management import is_over
from .core.cafe_player import state
from .core.cafe_activities import ACTIVITY_LABELS


class CafeBondGoalWindow:
    def __init__(self, parent, session, on_changed):
        import tkinter as tk
        from tkinter import ttk
        self.session, self.on_changed = session, on_changed
        self.window = tk.Toplevel(parent)
        self.window.title('猫との好感度目標・結果')
        self.window.geometry('660x460')
        self.window.minsize(580, 420)
        self.window.transient(parent)
        self.window.grab_set()
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        footer = ttk.Frame(frame)
        footer.pack(side='bottom', fill='x', pady=(10,0))
        self.enable_button = ttk.Button(footer, text='目標を開始', command=self.enable)
        self.enable_button.pack(side='left')
        self.continue_button = ttk.Button(footer, text='結果を確認して営業を続ける', command=self.resume)
        self.continue_button.pack(side='left', padx=4)
        ttk.Button(footer, text='閉じる', command=self.window.destroy).pack(side='right')
        self.status, self.details, self.notice = tk.StringVar(), tk.StringVar(), tk.StringVar()
        for var in (self.status, self.details, self.notice):
            ttk.Label(frame, textvariable=var, wraplength=540).pack(anchor='w', pady=5)
        table = ttk.Frame(frame)
        table.pack(fill='both', expand=True)
        self.cats = ttk.Treeview(table, columns=('name','affinity','activity','eligible'), show='headings', height=5)
        for key, label, width in (('name','猫',180),('affinity','プレイヤー好感度',130),
                                  ('activity','所在・所属',100),('eligible','現在の対象',100)):
            self.cats.heading(key, text=label)
            self.cats.column(key, width=width, minwidth=70)
        self.cats.pack(side='left', fill='both', expand=True)
        bar = ttk.Scrollbar(table, orient='vertical', command=self.cats.yview)
        bar.pack(side='right', fill='y')
        self.cats.configure(yscrollcommand=bar.set)
        self.window.bind('<Escape>', lambda event: self.window.destroy())
        self.refresh()

    def refresh(self):
        from .core.cafe_activities import waiting_events
        core = self.session.core
        data = core.bond_goal
        selected = data['rules'] if data else rules()
        self.status.set(progress(core))
        self.details.set(f"プレイヤーへの好感度{selected['affinity']:g}以上の在籍猫を同時に{selected['target']}匹でクリア。期限はありません。派遣中・家出中も含み、譲渡済みは除きます。人気・有力者目標とは独立し、達成後も営業を続けられます。")
        reason = ''
        try:
            core.require_events_resolved()
        except ValueError as exc:
            reason = str(exc)
        blocked = bool(self.session.pending) or bool(waiting_events(core)) or is_over(core)
        self.enable_button.state(['!disabled'] if not data and core.management and core.can_set_shifts and not reason and not blocked else ['disabled'])
        self.continue_button.state(['!disabled'] if pending(core) and not blocked else ['disabled'])
        names = {key: self.session.profiles.get(key, {}).get('name', key) for key in core.cats}
        achieved = ', '.join(names[key] for key in data['achieved_cats']) if data else ''
        self.notice.set('ゲームオーバーです。目標の確認・継続はできません。' if is_over(core) else
                        '先に接客結果の保存・帰還・譲渡イベントを確認してください。' if blocked else
                        f"{data['resolved_day']}日目に達成：{achieved}" if data and data['status']=='cleared' else
                        '先に経営ルールを開始してください。' if not core.management else
                        '目標は準備中に一度だけ開始できます。猫の詳細から交流して好感度を上げましょう。')
        self.cats.delete(*self.cats.get_children())
        eligible = qualifying(core, selected)
        for key, affinity in state(core)['affinity'].items():
            self.cats.insert('', 'end', iid=key, values=(names[key], f'{affinity:g}', ACTIVITY_LABELS[core.activity(key)], '対象' if key in eligible else '対象外'))

    def perform(self, action):
        from tkinter import messagebox
        try:
            action()
        except (ValueError, OSError) as exc:
            messagebox.showerror('好感度目標を操作できません', str(exc), parent=self.window)
        self.on_changed()
        self.refresh()

    def enable(self):
        from tkinter import messagebox
        selected = rules()
        if messagebox.askyesno('好感度目標を開始', f"プレイヤーへの好感度{selected['affinity']:g}以上の猫{selected['target']}匹を目指します。期限なし・開始後の取消はできません。開始しますか？", parent=self.window):
            self.perform(lambda: self.session.enable_bond_goal(selected))

    def resume(self):
        self.perform(self.session.continue_bond_goal)
