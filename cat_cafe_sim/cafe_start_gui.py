"""新規ゲーム・既存セーブの入口と、終了結果からの再開始。"""
from .cafe_new_game import create_game, starting_conditions


class NewGameWindow:
    def __init__(self, parent, on_started, before_start=lambda: True, previous=None, directory='saves/games'):
        import tkinter as tk
        from tkinter import ttk
        self.on_started, self.before_start = on_started, before_start
        self.directory = directory
        self.conditions = starting_conditions()
        self.window = tk.Toplevel(parent)
        self.window.title('新しいゲーム')
        self.window.geometry('580x460')
        self.window.minsize(500, 430)
        self.window.transient(parent)
        self.window.grab_set()
        frame = ttk.Frame(self.window, padding=16)
        frame.pack(fill='both', expand=True)
        controls = ttk.Frame(frame)
        controls.pack(side='bottom', fill='x', pady=8)
        self.start_button = ttk.Button(controls, text='この条件で新しく始める', command=self.start)
        self.start_button.pack(side='left')
        self.cancel_button = ttk.Button(controls, text='戻る', command=self.window.destroy)
        self.cancel_button.pack(side='right')
        if previous is not None:
            from .core.cafe_management import is_over
            if is_over(previous):
                reason = '資金が0以下になりました' if previous.management['game_over']['reason'] == 'funds' else '人気が0になりました'
                total = sum(row['summary']['revenue'] for row in previous.day_results) + previous.summary()['revenue']
                ttk.Label(frame, text=f'ゲームオーバー：{reason}\n{previous.day}日目 / 資金 {previous.funds:g} / 人気 {previous.management["popularity"]:g}\n累計接客売上 {total:g}', wraplength=460).pack(anchor='w', pady=(0,12))
        rule = self.conditions['management']
        ttk.Label(frame, text=f"新しい店の初期条件\n資金 {rule['starting_funds']:g} / 人気 {rule['starting_popularity']:g} / {self.conditions['seat_count']}席", wraplength=460).pack(anchor='w')
        names = '・'.join(row['name'] for row in self.conditions['profiles']['cats'].values())
        ttk.Label(frame, text=f'所属猫：{names}\n全猫が健康・体力全回復で、出勤予定から開始します。', wraplength=460).pack(anchor='w', pady=8)
        ttk.Label(frame, text='ストレス・家出・経営ルール：有効\n資金0以下または人気0でゲームオーバー。\n譲渡イベント：初期OFF（準備中に変更できます）。', wraplength=460).pack(anchor='w')
        ttk.Label(frame, text='新しい店は1日目の準備から始まります。猫との関係や資金は引き継ぎません。以前のゲームは保存先を分けて残します。', wraplength=460).pack(anchor='w', pady=8)
        self.window.bind('<Escape>', lambda event: self.window.destroy())

    def start(self):
        from tkinter import messagebox
        if not self.before_start():
            return
        self.start_button.state(['disabled'])
        try:
            session = create_game(self.directory, self.conditions)
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
            messagebox.showerror('新しく始められませんでした', str(exc), parent=self.window)
            self.start_button.state(['!disabled'])
            return
        self.window.destroy()
        self.on_started(session, False)


class CafeStartWindow:
    def __init__(self, root, directory='saves/games'):
        from tkinter import ttk
        self.root, self.directory = root, directory
        root.title('猫カフェ — はじめる')
        root.geometry('580x340')
        root.minsize(500, 300)
        root.protocol('WM_DELETE_WINDOW', root.destroy)
        self.frame = ttk.Frame(root, padding=24)
        self.frame.pack(fill='both', expand=True)
        ttk.Label(self.frame, text='猫カフェ', font=('', 20)).pack(pady=12)
        ttk.Label(self.frame, text='猫たちの出勤・休養・派遣を考えながら、店を経営します。', wraplength=450).pack(pady=8)
        self.new_button = ttk.Button(self.frame, text='新しく始める', command=self.new_game)
        self.new_button.pack(fill='x', pady=6)
        self.resume_button = ttk.Button(self.frame, text='セーブから続ける…', command=self.resume)
        self.resume_button.pack(fill='x', pady=6)
        ttk.Button(self.frame, text='終了', command=root.destroy).pack(anchor='e', pady=12)

    def new_game(self):
        from tkinter import messagebox
        try:
            self.new_window = NewGameWindow(self.root, self.show_game, directory=self.directory)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror('初期条件を読み込めません', str(exc), parent=self.root)

    def resume(self):
        from tkinter import filedialog, messagebox
        from .storage.cafe_saves import load_game
        path = filedialog.askopenfilename(parent=self.root, title='セーブから続ける', initialdir=self.directory,
                                          filetypes=[('営業セーブ', '*.json')])
        if not path:
            return
        try:
            session, auto_assign = load_game(path)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            messagebox.showerror('営業を開けませんでした', str(exc), parent=self.root)
            return
        self.show_game(session, auto_assign)

    def show_game(self, session, auto_assign):
        from .cafe_interaction_gui import CafeInteractionWindow
        self.frame.destroy()
        self.app = CafeInteractionWindow(self.root, session)
        self.app.new_game_directory = self.directory
        self.app.auto_assign.set(auto_assign)
        self.app.refresh()
