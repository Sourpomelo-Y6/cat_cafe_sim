"""営業準備中の、プレイヤーがコマンドを選ぶ猫との交流。"""
from .core.cafe_player import current, remaining
from .human_cat_gui import ACTION_NAMES, REACTION_NAMES, END_NAMES


class CafePlayerWindow:
    def __init__(self, parent, session, on_changed):
        import tkinter as tk
        from tkinter import ttk
        from .cafe_history import CafeHistoryWindow
        self.session, self.on_changed = session, on_changed
        self.window = tk.Toplevel(parent)
        self.window.title('プレイヤーと猫の交流')
        self.window.geometry('820x600')
        self.window.minsize(600, 480)
        self.window.transient(parent)
        self.window.grab_set()
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        footer = ttk.Frame(frame)
        footer.pack(side='bottom', fill='x')
        self.finish_button = ttk.Button(footer, text='このセットを切り上げる',
                                        command=lambda: self.act(finish=True))
        self.finish_button.pack(side='left')
        self.close_button = ttk.Button(footer, text='閉じる（途中状態を保持）', command=self.close)
        self.close_button.pack(side='right')
        self.status = tk.StringVar()
        self.result = tk.StringVar()
        ttk.Label(frame, textvariable=self.status, wraplength=560).pack(anchor='w')
        ttk.Label(frame, textvariable=self.result, wraplength=560).pack(anchor='w', pady=4)
        ttk.Label(frame, text='営業時間は進みません。体力は接客と共通です。好感度はセット終了時に確定します。',
                  wraplength=560).pack(anchor='w')
        commands = ttk.Frame(frame)
        commands.pack(fill='x', pady=6)
        self.buttons = {}
        for index, action in enumerate(ACTION_NAMES):
            button = ttk.Button(commands, text=ACTION_NAMES[action], command=lambda a=action:self.act(a))
            button.grid(row=index//3, column=index%3, sticky='ew', padx=2, pady=2)
            self.buttons[action] = button
        for column in range(3):
            commands.columnconfigure(column, weight=1)
        choice = ttk.Frame(frame)
        choice.pack(fill='x')
        ttk.Label(choice, text='切り替え先').pack(side='left')
        self.selector = ttk.Combobox(choice, state='readonly')
        self.selector.pack(side='left', fill='x', expand=True)
        self.history = CafeHistoryWindow.table(frame, ('ターン','行動','猫の反応','関心','テンション','体力','好感度増減'))
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.window.bind('<Escape>', lambda event:self.close())
        self.refresh()

    def close(self):
        parent = self.window.master
        self.window.destroy()
        if parent.winfo_exists():
            parent.grab_set()
        self.on_changed()

    def act(self, action=None, *, finish=False):
        from tkinter import messagebox
        target = None
        if action == 'switch':
            index = self.selector.current()
            target = self.targets[index] if index >= 0 else None
        try:
            self.session.player_command(action, target, finish=finish)
        except (ValueError, OSError) as exc:
            messagebox.showerror('交流を進められません', str(exc), parent=self.window)
        self.on_changed()
        self.refresh()

    def refresh(self):
        from .core.human_cat_relationship import verify_relationship
        interaction = current(self.session.core)
        active = interaction is not None
        if interaction is None:
            log = (self.session.core.player_bond or {}).get('last')
            interaction = verify_relationship(log) if log else None
        if interaction is None:
            return
        summary = interaction.summary()
        name = self.session.profiles.get(interaction.cat_id, {}).get('name', interaction.cat_id)
        self.status.set(f"{name} · 残り{interaction.state['remaining_ticks']}ターン · 本日あと{remaining(self.session.core)}セット\n"
                        f"種類：{interaction.type_map[interaction.state['mode']].name} · 関心 {summary['engagement']:g} · "
                        f"テンション {summary['tension']:g} · 体力 {summary['stamina']:g}")
        self.result.set(f"プレイヤー好感度 {summary['affinity_before']:g} → {summary['affinity_after']:g} "
                        + ('（見込み）' if active else f"（確定） · {END_NAMES[interaction.state['end_reason']]}"))
        valid = interaction.valid_actions() if active and not self.session.pending else ()
        for action, button in self.buttons.items():
            button.state(['!disabled'] if action in valid else ['disabled'])
        self.finish_button.state(['!disabled'] if active and not self.session.pending else ['disabled'])
        selected = self.selector.get()
        self.targets = [key for key in interaction.type_map if key != interaction.state['mode']]
        labels = [interaction.type_map[key].name for key in self.targets]
        self.selector.configure(values=labels, state='readonly' if active else 'disabled')
        if selected in labels:
            self.selector.set(selected)
        elif labels:
            self.selector.current(0)
        self.history.delete(*self.history.get_children())
        for row in interaction.records:
            target = row['target_type']
            action = ACTION_NAMES[row['action']] + (' → '+interaction.type_map[target].name if target else '')
            after = row['after']
            self.history.insert('', 'end', values=(row['tick']+1, action, REACTION_NAMES[row['reaction']],
                f"{after['engagement']:g}", f"{after['tension']:g}", f"{after['stamina']:g}",
                f"{sum(row['affinity_breakdown'].values()):+g}"))
        items = self.history.get_children()
        if items:
            self.history.see(items[-1])
