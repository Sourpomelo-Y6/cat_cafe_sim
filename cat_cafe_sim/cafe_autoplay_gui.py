"""1操作ずつTkのイベントループへ戻す、最大10日間の自動プレイ画面。"""
from .cafe_autoplay import AutoPlayer, REASONS


class CafeAutoPlayWindow:
    interval_ms = 20
    MODES = {'基礎営業': 'basic', 'クリアを目指す': 'clear'}

    def __init__(self, app):
        import tkinter as tk
        from tkinter import ttk
        self.app = app
        self.session = app.session
        self.player = None
        self.timer = None
        self.running = False
        self.before = None
        self.lines = []
        self.window = tk.Toplevel(app.root)
        self.window.title('10日間おまかせ')
        self.window.geometry('760x620')
        self.window.minsize(600,480)
        self.window.transient(app.root)
        self.window.grab_set()
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(4, weight=1)
        ttk.Label(frame, text='最大10日進め、各目標の達成・期限切れ・ゲームオーバーで止まります。\n'
                  '基礎営業は出勤・休養と必要な回答、クリア方針は設備投資・予約も任せます。', wraplength=700).grid(row=0, sticky='w')
        row = ttk.Frame(frame)
        row.grid(row=1, sticky='ew', pady=8)
        self.mode = tk.StringVar(value='基礎営業')
        ttk.Label(row, text='方針：').pack(side='left')
        self.selector = ttk.Combobox(row, textvariable=self.mode, values=tuple(self.MODES), state='readonly', width=18)
        self.selector.pack(side='left')
        self.start_button = ttk.Button(row, text='10日間おまかせ開始', command=self.start)
        self.start_button.pack(side='left', padx=8)
        self.stop_button = ttk.Button(row, text='中止', command=self.stop, state='disabled')
        self.stop_button.pack(side='left')
        self.progress = tk.StringVar(value='待機中：0 / 10日')
        ttk.Label(frame, textvariable=self.progress, wraplength=700).grid(row=2, sticky='w')
        self.summary = tk.StringVar(value='終了時に現在のセーブへ保存します。' if self.session.checkpoint_path else
                                    '保存先は未設定です。終了後、メイン画面の「保存…」で保存できます。')
        ttk.Label(frame, textvariable=self.summary, wraplength=700).grid(row=3, sticky='w', pady=8)
        history = ttk.Frame(frame)
        history.grid(row=4, sticky='nsew')
        history.columnconfigure(0, weight=1)
        history.rowconfigure(0, weight=1)
        self.log = tk.Text(history, wrap='word', state='disabled')
        self.log.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(history, orient='vertical', command=self.log.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.log.configure(yscrollcommand=scroll.set)
        footer = ttk.Frame(frame)
        footer.grid(row=5, sticky='ew', pady=(8,0))
        ttk.Button(footer, text='操作ログを保存…', command=self.save_log).pack(side='left')
        ttk.Button(footer, text='通常操作へ戻る', command=self.close).pack(side='right')
        self._controls()

    def _available(self):
        c = self.session.core
        return bool(c.goal and not c.goal.get('tracking_only') and c.goal['status']=='active'
                    and not (c.management or {}).get('game_over') and not self.session.pending
                    and self.session is self.app.session)

    def _controls(self):
        self.selector.configure(state='disabled' if self.running else 'readonly')
        self.start_button.state(['!disabled'] if not self.running and self._available() else ['disabled'])
        self.stop_button.state(['!disabled'] if self.running else ['disabled'])

    def emit(self, line):
        self.lines.append(line)
        self.log.configure(state='normal')
        self.log.insert('end', line+'\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def _state(self):
        c = self.session.core
        return dict(funds=c.funds, popularity=c.management['popularity'],
                    cats={key: (cat.fatigue, c.management['stress'][key], cat.health_status, c.activity(key))
                          for key, cat in c.cats.items()})

    def start(self):
        if self.running or not self._available():
            return
        self.before = self._state()
        self.player = AutoPlayer(self.session, mode=self.MODES[self.mode.get()], max_days=10,
                                 emit=self.emit, stop_on_goal=True)
        self.running = True
        self.progress.set('進行中：0 / 10日')
        self.summary.set('中止・通常操作へ戻ると、処理中の操作を終えて停止します。')
        self._controls()
        self._schedule()

    def _schedule(self):
        if self.running and self.timer is None:
            self.timer = self.window.after(self.interval_ms, self.advance)

    def advance(self):
        self.timer = None
        if not self.running:
            return
        if self.session is not self.app.session:
            self.stop()
            return
        try:
            progressed = self.player.step()
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
            self.player._stop('blocked', str(error))
            progressed = False
        self.progress.set(f'進行中：{self.player._days()-self.player.start_days} / 10日 · {self.session.core.day}日目')
        self.app.refresh()
        if progressed:
            self._schedule()
        else:
            self._finish()

    def stop(self):
        if not self.running:
            return
        if self.timer is not None:
            self.window.after_cancel(self.timer)
            self.timer = None
        self.player.cancel()
        self.player.step()
        self._finish()

    def _finish(self):
        self.running = False
        result = self.player.result
        self.progress.set(f'終了：{REASONS[result.reason]} · {result.days} / 10日')
        after = self._state()
        rows = [f'資金 {self.before["funds"]:g} → {after["funds"]:g} / 人気 {self.before["popularity"]:g} → {after["popularity"]:g}']
        for key, values in after['cats'].items():
            old = self.before['cats'].get(key, values)
            from .core.cafe_activities import ACTIVITY_LABELS
            health = {'healthy': '健康', 'sick': '療養'}
            rows.append(f'{self.session.profiles.get(key, {}).get("name", key)}：疲労 {old[0]:g} → {values[0]:g} / ストレス {old[1]:g} → {values[1]:g}'
                        f' / {health.get(old[2], old[2])} → {health.get(values[2], values[2])}'
                        f' / {ACTIVITY_LABELS[old[3]]} → {ACTIVITY_LABELS[values[3]]}')
        try:
            if self.session.checkpoint_path:
                from .storage.cafe_saves import save_game
                save_game(self.session, self.session.checkpoint_path, auto_assign=self.app.auto_assign.get())
                rows.append('現在のセーブへ保存しました。')
            else:
                rows.append('メイン画面の「保存…」で保存できます。')
        except (OSError, ValueError) as error:
            rows.append(f'営業セーブの保存に失敗しました：{error}')
        self.summary.set('\n'.join(rows))
        self.emit(self.summary.get())
        self._controls()
        self.app.refresh()

    def save_log(self):
        from tkinter import filedialog, messagebox
        from pathlib import Path
        self.stop()
        path = filedialog.asksaveasfilename(parent=self.window, title='おまかせ操作ログを保存',
                                          defaultextension='.txt', filetypes=[('操作ログ', '*.txt')])
        if not path:
            return
        try:
            target = Path(path).resolve()
            protected = [self.session.store.path.resolve(), self.session.checkpoint_path]
            if target in protected:
                raise ValueError('営業セーブ・関係データとは別のファイルを指定してください。')
            target.write_text('\n'.join(self.lines)+'\n', encoding='utf-8')
        except (OSError, ValueError) as error:
            messagebox.showerror('操作ログを保存できません', str(error), parent=self.window)

    def close(self):
        self.stop()
        self.window.grab_release()
        self.window.destroy()
        if self.app.autoplay_window is self:
            self.app.autoplay_window = None
        self.app.refresh()
