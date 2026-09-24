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
        self.window.geometry('600x520')
        self.window.minsize(500, 460)
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
        from .core.cafe_objective import MODES
        pages = ttk.Notebook(frame)
        pages.pack(fill='both', expand=True)
        goal_page = ttk.Frame(pages, padding=12)
        setup_page = ttk.Frame(pages, padding=12)
        pages.add(goal_page, text='挑戦する目標')
        pages.add(setup_page, text='初期条件')
        ttk.Label(goal_page, text='今回の店で目指す目標を選んでください。', wraplength=430).pack(anchor='w', pady=8)
        self.objective_ids = list(MODES)
        self.objective_choice = ttk.Combobox(goal_page, state='readonly', values=list(MODES.values()))
        self.objective_choice.pack(fill='x', pady=8)
        self.objective_choice.current(0)
        self.objective_description = tk.StringVar()
        ttk.Label(goal_page, textvariable=self.objective_description, wraplength=430).pack(anchor='w', pady=12)
        ttk.Label(goal_page, text='どの目標でも資金0以下・人気0でゲームオーバー。\n達成後は営業を続けられます。接客による人気の増加は全モード共通です。', wraplength=430).pack(anchor='w', pady=8)
        rule = self.conditions['management']
        ttk.Label(setup_page, text=f"資金 {rule['starting_funds']:g} / 人気 {rule['starting_popularity']:g} / {self.conditions['seat_count']}席", wraplength=430).pack(anchor='w', pady=8)
        names = '・'.join(row['name'] for row in self.conditions['profiles']['cats'].values())
        ttk.Label(setup_page, text=f'所属猫：{names}\n全猫が健康・体力全回復で、出勤予定から開始します。', wraplength=430).pack(anchor='w', pady=8)
        ttk.Label(setup_page, text='ストレス・家出・経営ルール：有効\n譲渡イベント：初期OFF（準備中に変更できます）。', wraplength=430).pack(anchor='w', pady=8)
        ttk.Label(setup_page, text='新しい店は1日目の準備から始まります。猫との関係や資金は引き継ぎません。以前のゲームは保存先を分けて残します。', wraplength=430).pack(anchor='w', pady=8)
        self.objective_choice.bind('<<ComboboxSelected>>', lambda event: self.select_objective())
        self.select_objective()
        self.window.bind('<Escape>', lambda event: self.window.destroy())

    def select_objective(self):
        from .cafe_objective import description
        mode = self.objective_ids[self.objective_choice.current()]
        self.conditions["objective"] = mode
        self.objective_description.set(description(self.conditions, mode))

    def start(self):
        from tkinter import messagebox
        self.select_objective()
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
