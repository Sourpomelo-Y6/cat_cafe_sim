"""1操作ずつTkのイベントループへ戻す、最大10日間の自動プレイ画面。"""
from .cafe_autoplay import AutoPlayer, REASONS


OBJECTIVES = {'人気': 'popularity', '好感度': 'bond', '有力者': 'patron'}


def objective_targets(core):
    return {key: value for key, value in (
        ('popularity', core.goal if core.goal and not core.goal.get('tracking_only') else None),
        ('bond', core.bond_goal), ('patron', core.patron)) if value is not None}


def autoplay_available(session):
    from .core import cafe_goal, cafe_bond_goal, cafe_patron
    core = session.core
    return bool(core.goal and core.management and not core.management.get('game_over')
                and not session.pending and any(row['status']=='active' for row in objective_targets(core).values())
                and not (cafe_goal.pending(core) or cafe_bond_goal.pending(core) or cafe_patron.pending(core)))


class CafeAutoPlayWindow:
    interval_ms = 20
    MODES = {'基礎営業': 'basic', '安定経営': 'clear', '積極経営': 'fast'}

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
        self.decision_rows = {}
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
                  '基礎営業は出勤・休養と必要な回答。安定経営・積極経営では選んだ目標への交流・加入・派遣も任せます。', wraplength=700).grid(row=0, sticky='w')
        row = ttk.Frame(frame)
        row.grid(row=1, sticky='ew', pady=8)
        targets = objective_targets(self.session.core)
        self.objectives = {label: key for label, key in OBJECTIVES.items() if key in targets}
        preferred = self.session.core.objective
        if preferred not in targets or targets[preferred]['status']!='active':
            preferred = next((key for key, target in targets.items() if target['status']=='active'), next(iter(targets), ''))
        self.objective = tk.StringVar(value=next((label for label, key in self.objectives.items() if key==preferred), ''))
        ttk.Label(row, text='目標：').pack(side='left')
        self.objective_selector = ttk.Combobox(row, textvariable=self.objective, values=tuple(self.objectives), state='readonly', width=7)
        self.objective_selector.pack(side='left', padx=(0,6))
        self.objective_selector.bind('<<ComboboxSelected>>', lambda event: self._controls())
        self.mode = tk.StringVar(value='基礎営業')
        ttk.Label(row, text='方針：').pack(side='left')
        self.selector = ttk.Combobox(row, textvariable=self.mode, values=tuple(self.MODES), state='readonly', width=12)
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
        self.tabs = ttk.Notebook(frame)
        self.tabs.grid(row=4, sticky='nsew')
        decisions = ttk.Frame(self.tabs)
        self.tabs.add(decisions, text='判断一覧')
        decisions.columnconfigure(0, weight=1)
        decisions.rowconfigure(0, weight=1)
        self.decision_table = ttk.Treeview(decisions, columns=('day','target','choice','reason','status'),
                                         show='headings', height=5)
        for key, title, width in (('day','日',40),('target','対象',130),('choice','判断',65),
                                  ('reason','理由',250),('status','実行結果',85)):
            self.decision_table.heading(key, text=title)
            self.decision_table.column(key, width=width, minwidth=35, stretch=key=='reason')
        self.decision_table.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(decisions, orient='vertical', command=self.decision_table.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.decision_table.configure(yscrollcommand=scroll.set)
        self.decision_detail = tk.Text(decisions, height=3, wrap='word', state='disabled')
        self.decision_detail.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(4,0))
        self.decision_table.bind('<<TreeviewSelect>>', self.show_decision)
        self._decision_text('開始後に判断を表示します。行を選ぶと理由の全文を確認できます。')
        history = ttk.Frame(self.tabs)
        self.tabs.add(history, text='操作ログ')
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
        target = objective_targets(self.session.core).get(self.objectives.get(self.objective.get()))
        return bool(target and target['status']=='active' and autoplay_available(self.session)
                    and self.session is self.app.session)

    def _target_progress(self):
        core = self.session.core
        objective = self.objectives.get(self.objective.get())
        if objective=='bond':
            from .core.cafe_bond_goal import progress
            return progress(core)
        if objective=='patron':
            from .core.cafe_patron import progress
            return progress(core)
        if objective=='popularity':
            from .core.cafe_goal import current_rules
            return f"人気：{core.management['popularity']:g} / {current_rules(core.goal)['target']:g}"
        return '目標が未導入です。'

    def _controls(self):
        self.selector.configure(state='disabled' if self.running else 'readonly')
        self.objective_selector.configure(state='disabled' if self.running else 'readonly')
        self.start_button.state(['!disabled'] if not self.running and self._available() else ['disabled'])
        self.stop_button.state(['!disabled'] if self.running else ['disabled'])
        if self.player is None:self.progress.set('待機中：0 / 10日 · '+self._target_progress())

    def emit(self, line):
        self.lines.append(line)
        self.log.configure(state='normal')
        self.log.insert('end', line+'\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def _decision_text(self, text):
        self.decision_detail.configure(state='normal')
        self.decision_detail.delete('1.0', 'end')
        self.decision_detail.insert('end', text)
        self.decision_detail.configure(state='disabled')

    def show_decision(self, event=None):
        selection = self.decision_table.selection()
        if selection:
            day, target, choice, reason, status = self.decision_table.item(selection[0], 'values')
            self._decision_text(f'{day}日目 · {target}：{choice} · {status}\n{reason}')

    def record_decision(self, row):
        key = (row['day'], row['subject'])
        values = tuple(row[k] for k in ('day','target','choice','reason','status'))
        if key in self.decision_rows:
            item = self.decision_rows[key]
            self.decision_table.item(item, values=values)
        else:
            item = self.decision_table.insert('', 'end', values=values)
            self.decision_rows[key] = item
            self.decision_table.see(item)
        if item in self.decision_table.selection():
            self.show_decision()

    def _state(self):
        c = self.session.core
        return dict(funds=c.funds, popularity=c.management['popularity'],
                    cats={key: (cat.fatigue, c.management['stress'][key], cat.health_status, c.activity(key))
                          for key, cat in c.cats.items()})

    def start(self):
        if self.running or not self._available():
            return
        self.before = self._state()
        self.decision_table.delete(*self.decision_table.get_children())
        self.decision_rows.clear()
        self._decision_text('行を選ぶと、判断理由の全文と実行結果を確認できます。')
        self.player = AutoPlayer(self.session, mode=self.MODES[self.mode.get()], max_days=10,
                                 emit=self.emit, stop_on_goal=True, on_decision=self.record_decision,
                                 objective=self.objectives[self.objective.get()])
        self.emit('おまかせ目標：'+self.objective.get())
        self.running = True
        self.progress.set('進行中：0 / 10日 · '+self._target_progress())
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
        from .core.cafe_player import current
        interaction = current(self.session.core)
        before_operations = len(self.session.core.operations)
        try:
            progressed = self.player.step()
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
            self.player._stop('blocked', str(error))
            progressed = False
        for row in self.session.core.operations[before_operations:]:
            for event in row['events']:
                if event['kind']=='player_action':
                    from .human_cat_gui import ACTION_NAMES, REACTION_NAMES
                    record = event['record']
                    name = self.session.profiles.get(event['cat_id'], {}).get('name', event['cat_id'])
                    action = ACTION_NAMES[record['action']]
                    if record['target_type'] and interaction:
                        action += ' → '+interaction.type_map[record['target_type']].name
                    self.emit(f"交流操作：{name} · {action} · {REACTION_NAMES[record['reaction']]}"
                              f" / 残り体力 {record['after']['stamina']:g}")
                elif event['kind']=='player_completed':
                    result = event['result']
                    name = self.session.profiles.get(event['cat_id'], {}).get('name', event['cat_id'])
                    self.emit(f"交流結果：{name} · 好感度 {result['affinity_before']:g} → {result['affinity_after']:g}"
                              f" / 残り体力 {result['stamina']:g} / 同時発動 {result['simultaneous_count']}回")
                elif event['kind']=='patron_satisfaction':
                    name = event.get('name', self.session.core.patron['rules']['name'])
                    self.emit(f"訪問結果：{name} · 満足度＋{event['gain']:g} / 現在 {event['satisfaction']:g}")
        self.progress.set(f'進行中：{self.player._days()-self.player.start_days} / 10日 · {self.session.core.day}日目 · '+self._target_progress())
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
        self.progress.set(f'終了：{REASONS[result.reason]} · {result.days} / 10日 · '+self._target_progress())
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
