"""営業中のお客を選び、版4交流の成果を営業へ戻す試遊画面。"""
from .cafe_health_text import health_text, health_result_text
from .human_cat_gui import ACTION_NAMES, history_row
from .relationship_presentation import greeting_text


class ManualCafeInteractionWindow:
    def __init__(self, root, session):
        import tkinter as tk
        from tkinter import ttk
        self.root, self.session = root, session
        self.logged = 0
        root.title('猫カフェ — 営業と交流')
        root.geometry('1000x700'); root.minsize(860,600)
        frame = ttk.Frame(root, padding=12); frame.pack(fill='both',expand=True)
        frame.columnconfigure(0,weight=1); frame.rowconfigure(5,weight=1,minsize=140)
        self.status = tk.StringVar(); self.details = tk.StringVar(); self.notice = tk.StringVar()
        ttk.Label(frame,textvariable=self.status,wraplength=820).grid(row=0,sticky='w',pady=6)
        self.instructions=ttk.Label(frame,text='検証用：時間送りと交流コマンドを手動で操作します。営業状態は起動中だけ保持します。',wraplength=820)
        self.instructions.grid(row=1,sticky='w')
        controls = self.controls = ttk.Frame(frame); controls.grid(row=2,sticky='ew',pady=8)
        self.customer = tk.StringVar()
        self.queue = ttk.Combobox(controls,textvariable=self.customer,state='readonly',width=18)
        self.queue.pack(side='left')
        self.start_button=ttk.Button(controls,text='選んだお客と交流',command=lambda:self.perform(lambda:self.session.start(self.customer.get())))
        self.start_button.pack(side='left',padx=6)
        self.wait_button=ttk.Button(controls,text='営業を1tick進める',command=lambda:self.perform(self.session.step))
        self.wait_button.pack(side='left')
        self.finish_button=ttk.Button(controls,text='切り上げて会計',command=lambda:self.perform(self.session.finish))
        self.finish_button.pack(side='left',padx=6)
        self.retry_button=ttk.Button(controls,text='結果保存を再試行',command=lambda:self.perform(self.session.persist))
        self.retry_button.pack(side='left')
        ttk.Label(frame,textvariable=self.details,wraplength=820).grid(row=3,sticky='w',pady=6)
        actions=self.actions_frame=ttk.Frame(frame); actions.grid(row=4,sticky='ew')
        self.types={t.name:t.id for t in session.interaction_config.types}
        self.target=tk.StringVar(value=next(iter(self.types)))
        ttk.Combobox(actions,textvariable=self.target,values=tuple(self.types),state='readonly',width=18).grid(row=0,column=0,columnspan=2,sticky='w')
        self.buttons={}
        for i,action in enumerate(tuple(ACTION_NAMES)):
            if action not in ('direct','adapt','intense','feint','pause','switch','connect'): continue
            button=ttk.Button(actions,text=ACTION_NAMES[action],command=lambda a=action:self.act(a))
            button.grid(row=1+i//4,column=i%4,sticky='ew',padx=3,pady=3)
            actions.columnconfigure(i%4,weight=1)
            self.buttons[action]=button
        history=ttk.Frame(frame);history.grid(row=5,sticky='nsew',pady=8)
        history.columnconfigure(0,weight=1);history.rowconfigure(0,weight=1)
        self.history=ttk.Treeview(history,columns=('tick','event'),show='headings',height=7)
        self.history.heading('tick',text='営業tick');self.history.heading('event',text='営業・交流ログ')
        self.history.column('tick',width=70,stretch=False);self.history.column('event',width=740)
        self.history.grid(row=0,column=0,sticky='nsew')
        scroll=ttk.Scrollbar(history,orient='vertical',command=self.history.yview)
        scroll.grid(row=0,column=1,sticky='ns');self.history.configure(yscrollcommand=scroll.set)
        ttk.Label(frame,textvariable=self.notice,wraplength=820).grid(row=6,sticky='w')
        self.file_controls=ttk.Frame(frame)
        self.file_controls.grid(row=7,sticky='ew')
        ttk.Button(self.file_controls,text='営業ログを保存…',command=self.save_log).pack(side='right')
        root.protocol('WM_DELETE_WINDOW',self.close)
        self.refresh()

    def act(self, action):
        self.perform(lambda:self.session.step(action,self.types[self.target.get()] if action=='switch' else None))

    def perform(self, operation):
        from tkinter import messagebox
        try:
            operation()
        except (OSError,ValueError,TypeError,KeyError,RuntimeError) as error:
            messagebox.showerror('操作を完了できませんでした',str(error),parent=self.root)
        self.refresh()

    def refresh(self):
        core=self.session.core
        self.status.set(f'{core.day}日目 · 営業 {core.tick}/{core.config.opening_ticks} tick · '+('閉店' if core.closed else '営業中')+
                        f' · 資金 {core.funds:g} · 猫 {self.session.cat_name}（{core.cat.id}） · 体力 {core.cat.stamina:g}')
        self.queue.configure(values=tuple(core.queue))
        if self.customer.get() not in core.queue:
            self.customer.set(core.queue[0] if core.queue else '')
        pending=bool(self.session.pending)
        active=core.active
        enabled=not core.closed and not pending
        self.wait_button.state(['!disabled'] if enabled and not active else ['disabled'])
        self.start_button.state(['!disabled'] if enabled and not active and core.queue and not core.cat.cannot_continue else ['disabled'])
        self.finish_button.state(['!disabled'] if active and not pending else ['disabled'])
        self.retry_button.state(['!disabled'] if pending else ['disabled'])
        for action,button in self.buttons.items():
            button.state(['!disabled'] if enabled and active and action in active.valid_actions() else ['disabled'])
        if active:
            state=active.summary()
            self.details.set(greeting_text(active)+f"\nお客 {active.customer_id} · {active.type_map[active.state['mode']].name} · 残り {active.state['remaining_ticks']} 行動 · 関心 {state['engagement']:g} · テンション {state['tension']:g} · 親しみ {state['affinity_before']:g} → {state['affinity_after']:g}（見込み）")
        else:
            self.details.set('交流するお客を選んでください。' if not core.closed else '本日の営業は終了しました。')
        self.notice.set('会計・体力は反映済みです。関係保存が未完了のため、保存を再試行してください。' if pending else
                        '交流終了時に会計と親しみを保存します。体力は次のお客にも引き継ぎます。')
        for event in core.events[self.logged:]:
            kind=event['kind']
            if kind=='human_cat_action':
                row=history_row(event['record'])
                text=f'{row[1]} / {row[2]}'
            elif kind=='health_enabled':
                text='病気・療養ルールを開始'
            elif kind=='cat_health':
                name=self.session.profiles.get(event['cat_id'],{}).get('name',event['cat_id'])
                text=f"{name}：{health_result_text(event)}"
            elif kind=='goal_enabled':
                text='人気目標への挑戦を開始'
            elif kind=='popularity_earned':
                text=f"接客による人気 ＋{event['gain']:g}（対象{event['qualified']}件）"
            elif kind=='goal_result':
                text='人気目標クリア' if event['status']=='cleared' else '人気目標は期限内未達'
            elif kind=='goal_continued':
                text='目標結果を確認し、継続営業を選択'
            elif kind=='management_enabled':
                text=f"経営ルール開始 · 開始時資金補充 {event['grant']:g}"
            elif kind=='recruitment_opened':
                text='保護猫の受け入れ候補を確認'
            elif kind=='cat_recruited':
                text=f"保護猫 {event['name']}（{event['cat_id']}）を受け入れ · 初期費用 {event['cost']:g} · 休養予定"
            elif kind=='cat_missing':
                text=f"家出 {event['cat_id']} · 店の人気 {event['popularity']:g}"
            elif kind=='missing_return_waiting':
                text=f"家出猫の帰還確認待ち {event['cat_id']}"
            elif kind=='missing_returned':
                text=f"帰還 {event['cat_id']} · 子猫の引き渡し費用 {event['cost']:g}"
            elif kind=='game_over':
                text='ゲームオーバー：'+('資金が0以下' if event['reason']=='funds' else '店の人気が0')
            elif kind=='adoption_configured':
                text='譲渡イベント：'+('ON' if event['enabled'] else 'OFF')
            elif kind=='adoption_offered':
                text=f"譲渡の申し出 {event['cat_id']} → {event['customer_id']} · 派遣・イベント画面で回答してください"
            elif kind=='adoption_resolved':
                text=f"譲渡{'成立' if event['choice']=='accept' else '見送り'} {event['cat_id']} → {event['customer_id']}"
            elif kind=='player_started':
                text=f"プレイヤー交流開始 {event['cat_id']} · 本日あと{event['remaining']}セット"
            elif kind=='player_action':
                row=history_row(event['record'])
                text=f"プレイヤー交流 {row[1]} / {row[2]}"
            elif kind=='player_completed':
                result=event['result']
                text=f"プレイヤー交流終了 {event['cat_id']} · 好感度 {result['affinity_before']:g} → {result['affinity_after']:g}"
            elif kind=='player_played':
                text=f"猫と遊びました {event['cat_id']} · プレイヤー好感度 {event['before']} → {event['after']} · 残り{event['remaining']}回"
            elif kind=='dispatch_started':
                text=f"派遣出発 {event['cat_id']} → {event['destination']}"
            elif kind=='activity_event_waiting':
                text=f"帰還確認待ち {event['cat_id']} · 派遣・イベント画面で確認してください"
            elif kind=='activity_event_resolved':
                text=f"帰還 {event['cat_id']} · 派遣報酬 {event['reward']:g}"
            elif kind=='shifts_set':
                text='出勤・休養を設定 · 出勤 '+('、'.join(event['working_cats']) or 'なし')
            elif kind=='day_off':
                text=f"{event['day']}日目は休業 · 来客なしで在店猫を休養"
            elif kind=='next_day':
                text=f"{event['day']}日目の準備 · 在店猫の体力が全回復しました"
            elif kind=='departure':
                reasons={'interaction_manual':'切り上げ', 'interaction_time_limit':'交流時間終了', 'interaction_exhausted':'体力切れ', 'closing':'閉店', 'queue_full':'待機列満員', 'wait_timeout':'待機時間終了'}
                text=f"退店 {event['customer_id']} · {reasons.get(event['reason'],event['reason'])} · 会計 {event['bill']:g}（時間 {event['base_charge']:g}＋ボーナス {event['bonus']:g}）"
            elif kind=='interaction_completed':
                r=event['result'];text=f"親しみ {r['affinity_before']:g} → {r['affinity_after']:g} · 残り体力 {r['stamina']:g}"
            else:
                names={'arrival':'来店','assigned':'着席','interaction_started':'交流開始','closed':'閉店'}
                text=f"{names.get(kind,kind)} {event.get('customer_id','')}"
            item=self.history.insert('','end',values=(event['tick'],(event.get('seat_id','')+' '+text).strip()));self.history.see(item)
        self.logged=len(core.events)

    def save_log(self):
        from tkinter import filedialog
        path=filedialog.asksaveasfilename(parent=self.root,defaultextension='.json',title='営業ログを保存')
        if path:self.perform(lambda:self.session.save_log(path))

    def close(self):
        from tkinter import messagebox
        if self.session.core.active or self.session.pending:
            answer=messagebox.askyesnocancel('営業を終了', '交流を切り上げ、親しみを保存して終了しますか？\n「いいえ」は未保存の交流を破棄します。',parent=self.root)
            if answer is None:return
            if answer:
                self.perform(self.session.finish)
                if self.session.pending or self.session.core.active:return
        self.root.destroy()


class CafeInteractionWindow(ManualCafeInteractionWindow):
    """通常営業。プレイヤーは割り当てと進行・一時停止だけを操作する。"""
    interval_ms = 700

    def __init__(self, root, session):
        import tkinter as tk
        from tkinter import ttk
        self.running = False
        self.timer = None
        super().__init__(root, session)
        self.instructions.configure(text='担当猫を割り当てると交流は自動で進みます。「営業を保存」で中断し、後で続きから開けます。')
        self.actions_frame.grid_remove()
        self.wait_button.pack_forget()
        self.finish_button.pack_forget()
        self.save_button=ttk.Button(self.file_controls,text='営業を保存…',command=self.save_game)
        self.save_button.pack(side='left')
        self.open_button=ttk.Button(self.file_controls,text='続きから開く…',command=self.open_game)
        self.open_button.pack(side='left',padx=6)
        self.day_button=ttk.Button(self.file_controls,text='閉店結果・翌日へ',command=self.show_day_result)
        self.day_button.pack(side='left',padx=6)
        self.history_button=ttk.Button(self.file_controls,text='営業結果を比較…',command=self.show_history)
        self.history_button.pack(side='left',padx=6)
        self.new_game_directory = 'saves/games'
        self.new_game_button = ttk.Button(self.file_controls, text='新規ゲーム…', command=self.new_game)
        self.new_game_button.pack(side='left',padx=4)
        self.auto_assign = tk.BooleanVar(value=False)
        self.cat_labels = {f"{row['name']}（{row['cat_id']}）":row['cat_id'] for row in session.cat_choices()}
        self.cat_choice = tk.StringVar(value=next(iter(self.cat_labels)))
        self.cat_selector = ttk.Combobox(self.controls,textvariable=self.cat_choice,
                                       values=tuple(self.cat_labels),state='readonly',width=18)
        self.cat_selector.pack(side='left',before=self.start_button,padx=4)
        self.start_button.configure(text='担当猫を割り当てる',command=self.assign)
        automation = ttk.Frame(self.actions_frame.master)
        automation.grid(row=4,sticky='ew',pady=6)
        buttons = self.automation_buttons = ttk.Frame(automation)
        buttons.pack(fill='x')
        self.run_button = ttk.Button(buttons,text='営業を開始・再開',command=self.toggle)
        self.run_button.pack(side='left',padx=4)
        self.assignment_button = ttk.Checkbutton(buttons,text='自動割り当て',variable=self.auto_assign,command=self.refresh)
        self.assignment_button.pack(side='left')
        ttk.Label(buttons,text='割り当て先').pack(side='left',padx=6)
        self.seat_choice=tk.StringVar(value=session.free_seats[0] if session.free_seats else '')
        self.seat_selector=ttk.Combobox(buttons,textvariable=self.seat_choice,values=tuple(session.free_seats),state='readonly',width=10)
        self.seat_selector.pack(side='left')
        self.shift_button=ttk.Button(buttons,text='出勤・休養…',command=self.show_shifts)
        self.shift_button.pack(side='left',padx=6)
        self.day_off_button=ttk.Button(buttons,text='今日は休業する',command=self.take_day_off)
        self.day_off_button.pack(side='left',padx=4)
        self.goal_button=ttk.Button(buttons,text='目標・結果…',command=self.show_goal)
        self.goal_button.pack(side='left',padx=4)
        roster_frame = ttk.Frame(automation)
        roster_frame.pack(fill='x',pady=4)
        self.cat_details_button = ttk.Button(roster_frame, text='猫の詳細…', command=self.show_cat_details)
        self.cat_details_button.pack(side='right', padx=4)
        self.activity_button = ttk.Button(roster_frame, text='派遣・イベント…', command=self.show_activities)
        self.activity_button.pack(side='right')
        self.roster = ttk.Treeview(roster_frame,columns=('cat','personality','stamina','affinity','status','fatigue','health','stress'),
                                   displaycolumns=('cat','personality','stamina','affinity','status','fatigue','stress','health'),show='headings',height=3)
        for key,title,width in (('cat','営業中の猫',170),('personality','個性',100),('stamina','体力',60),('affinity','選んだお客への親しみ',170),('status','状態',80),('fatigue','疲労',60),('health','体調',115),('stress','ストレス',75)):
            self.roster.heading(key,text=title)
            self.roster.column(key,width=width,minwidth=70 if key=='stress' else 50)
        scrollbar=ttk.Scrollbar(roster_frame,orient='vertical',command=self.roster.yview)
        scrollbar.pack(side='right',fill='y')
        self.roster.configure(yscrollcommand=scrollbar.set)
        self.roster.pack(fill='x')
        self.cat_selector.bind('<<ComboboxSelected>>', lambda event:self.refresh())
        self.queue.bind('<<ComboboxSelected>>', lambda event:self.refresh())
        self.refresh()

    def stop(self):
        self.running = False
        if self.timer is not None:
            self.root.after_cancel(self.timer)
            self.timer = None

    def schedule(self):
        if self.running and self.timer is None:
            self.timer = self.root.after(self.interval_ms, self.advance)

    def toggle(self):
        if self.running:
            self.stop()
        elif not self.session.pending and not self.session.core.closed:
            self.running = True
            self.schedule()
        self.refresh()

    def assign(self):
        self.stop()
        before = len(self.session.active_interactions)
        self.perform(lambda:self.session.start(self.customer.get(),self.cat_labels.get(self.cat_choice.get(),''),self.seat_choice.get()))
        if len(self.session.active_interactions) > before:
            self.running = True
            self.schedule()
        self.refresh()

    def advance(self):
        from tkinter import messagebox
        self.timer = None
        if not self.running:
            return
        try:
            progressed = self.session.automatic_step(auto_assign=self.auto_assign.get())
            from .core.cafe_activities import waiting_events
            if not progressed or self.session.core.closed or waiting_events(self.session.core):
                self.stop()
        except (OSError,ValueError,TypeError,KeyError,RuntimeError) as error:
            self.stop()
            messagebox.showerror('営業を一時停止しました',str(error),parent=self.root)
        self.refresh()
        self.schedule()

    def refresh(self):
        super().refresh()
        if not hasattr(self,'run_button'):
            return
        core = self.session.core
        from .core.cafe_activities import waiting_events, ACTIVITY_LABELS
        from .core.cafe_player import active as player_active
        playing = bool(player_active(core))
        from .core.cafe_management import is_over
        ended=is_over(core)
        self.new_game_button.configure(text='結果・再開始…' if ended else '新規ゲーム…')
        from .core.cafe_goal import pending as goal_pending
        from .cafe_goal_gui import progress
        self.instructions.configure(text=progress(core))
        goal_waiting=goal_pending(core)
        events_waiting=bool(waiting_events(core)) or playing or ended or goal_waiting
        if core.management:
            self.status.set(self.status.get()+f" · 人気 {core.management['popularity']:g}")
        self.day_off_button.state(['!disabled'] if core.can_set_shifts and not self.session.pending and not events_waiting else ['disabled'])
        self.shift_button.state(['!disabled'] if core.can_set_shifts and not self.session.pending and not events_waiting else ['disabled'])
        self.day_button.state(['!disabled'] if core.closed and not self.session.pending and not events_waiting else ['disabled'])
        blocked = bool(self.session.pending) or core.closed or events_waiting
        self.run_button.configure(text='一時停止' if self.running else '営業を開始・再開')
        self.run_button.state(['disabled'] if blocked else ['!disabled'])
        manual = not self.auto_assign.get() and bool(self.session.free_seats) and not blocked
        self.queue.configure(state='readonly' if manual else 'disabled')
        self.cat_selector.configure(state='readonly' if manual else 'disabled')
        self.seat_selector.configure(values=tuple(self.session.free_seats),state='readonly' if manual else 'disabled')
        if self.seat_choice.get() not in self.session.free_seats:
            self.seat_choice.set(self.session.free_seats[0] if self.session.free_seats else '')
        rows = self.session.cat_choices(self.customer.get())
        self.cat_labels = {f"{row['name']}（{row['cat_id']}）": row['cat_id'] for row in rows}
        self.cat_selector.configure(values=tuple(self.cat_labels))
        if self.cat_choice.get() not in self.cat_labels:
            self.cat_choice.set(next(iter(self.cat_labels)))
        selected = next((row for row in rows if row['cat_id']==self.cat_labels.get(self.cat_choice.get())),None)
        self.start_button.state(['!disabled'] if manual and core.queue and selected and selected['available'] else ['disabled'])
        roster_selected = self.roster.selection()
        self.roster.delete(*self.roster.get_children())
        for row in rows:
            state = '療養' if row['health_status']=='sick' else '休養' if not row['working'] else '交流中' if any(active.cat_id==row['cat_id'] for active in self.session.active_interactions.values()) else '担当可能' if row['available'] else '交流不可'
            if core.activity(row['cat_id'])!='cafe':state=ACTIVITY_LABELS[core.activity(row['cat_id'])]
            self.roster.insert('','end',iid=row['cat_id'],values=(f"{row['name']}（{row['cat_id']}）",row['personality'],f"{row['stamina']:g}",
                                               f"{row['affinity']:g}" if self.customer.get() else '—',state,f"{row['fatigue']:g}",health_text(row['health_status'],row['recovery_days_remaining']), '未導入' if row['stress'] is None else f"{row['stress']:g}"))
        if roster_selected and self.roster.exists(roster_selected[0]):
            self.roster.selection_set(roster_selected[0])
        if hasattr(core,'seats'):
            lines=[]
            for seat_id in core.seats:
                active=self.session.active_interactions.get(seat_id)
                if active:
                    r=active.summary()
                    name=self.session.profiles.get(active.cat_id,{}).get('name',active.cat_id)
                    lines.append(f"{seat_id}：{active.customer_id} / {name} · 体力 {r['stamina']:g} · 関心 {r['engagement']:g} · テンション {r['tension']:g} · 親しみ {r['affinity_after']:g} · 資金 {r['bonus_funds']:g}（見込み）")
                else:
                    last=next((event for event in reversed(core.events) if event['kind']=='departure' and event.get('seat_id')==seat_id),None)
                    lines.append(f"{seat_id}：空席"+(f" · 直近の会計 {last['bill']:g}" if last else ''))
            self.details.set('\n'.join(lines))
        if not self.session.pending:
            self.notice.set('自動進行中：交流コマンドは自動で選ばれます。' if self.running else
                            '一時停止中。担当猫を割り当てるか、営業を再開してください。' if not core.closed else '本日の営業は終了しました。')

        if core.can_set_shifts and not core.working_cats and not self.session.pending:
            self.notice.set('在店猫は全猫が休養予定です。「今日は休業する」で来客なしに1日休めます。')

        if ended:
            self.notice.set('ゲームオーバー：'+('資金が0以下になりました。' if core.management['game_over']['reason']=='funds' else '店の人気が0になりました。')+' 閲覧・保存はできます。'+(' 接客結果の保存を再試行してください。' if self.session.pending else ''))
        elif playing:
            self.notice.set('プレイヤー交流の途中です。「猫の詳細…」から再開・終了してください。')
        elif goal_waiting and not waiting_events(core):
            self.notice.set('目標の結果が出ました。「目標・結果…」で確認し、継続営業を選べます。')
        elif events_waiting:
            self.notice.set('帰還・譲渡・家出イベントの確認待ちです。「派遣・イベント…」で対応してください。')

    def show_goal(self):
        from .cafe_goal_gui import CafeGoalWindow
        self.stop();self.refresh()
        self.goal_window=CafeGoalWindow(self.root,self.session,self.refresh)

    def show_activities(self):
        from .cafe_activity_gui import CafeActivityWindow
        self.stop()
        self.refresh()
        self.activity_window = CafeActivityWindow(self.root,self.session,self.refresh)

    def take_day_off(self):
        from tkinter import messagebox
        self.stop()
        self.refresh()
        if not self.session.core.can_set_shifts or self.session.pending:
            return
        if not messagebox.askyesno('今日は休業する',
                '来客なしで在店猫を1日休ませ、翌日の準備へ進みます。派遣中の猫の期間も1日進みます。休業しますか？',parent=self.root):
            return
        self.perform(self.session.day_off)
        self.refresh()

    def show_shifts(self):
        from .cafe_shift_gui import CafeShiftWindow
        self.stop()
        self.refresh()
        if self.session.core.can_set_shifts and not self.session.pending:
            self.shift_window = CafeShiftWindow(self.root, self.session, self.refresh)

    def show_cat_details(self):
        from .cafe_cat_details import CafeCatDetailsWindow
        selected = self.roster.selection()
        cat_id = selected[0] if selected else self.cat_labels.get(self.cat_choice.get(), next(iter(self.session.core.cats)))
        self.stop()
        self.refresh()
        self.cat_details_window = CafeCatDetailsWindow(self.root, self.session, cat_id, self.refresh)

    def show_history(self):
        from .cafe_history import CafeHistoryWindow
        self.stop()
        self.refresh()
        self.history_window = CafeHistoryWindow(self.root, self.session)

    def show_day_result(self):
        from tkinter import messagebox
        self.stop()
        try:
            result=self.session.core.day_result()
            summary=result['summary']
            lines=[f"{result['day']}日目の営業結果", f"売上 {summary['revenue']:g}（ボーナス {summary['interaction_bonus']:g}）",
                   f"所持金 {summary['funds']:g}", "", "猫の体力（開始からの消耗）"]
            for key,row in result['cats'].items():
                name=self.session.profiles.get(key,{}).get('name',key)
                lines.append(f"{name}：残り {row['stamina']:g} / 消耗 {row['spent']:g}")
                if 'shift' in row:
                    from .core.cafe_activities import ACTIVITY_LABELS
                    label=ACTIVITY_LABELS[row['activity']] if row.get('activity','cafe')!='cafe' else ('出勤' if row['shift']=='work' else '休養')
                    lines.append(f"  {label} · 疲労 {row['fatigue_before']:g} → {row['fatigue_after']:g}")
                if 'health' in row:
                    lines.append('  '+health_result_text(row['health']))
            if 'popularity' in summary:
                lines.append(f"店の人気：{summary['popularity']:g} / 子猫の引き渡し費用：{summary['kitten_expenses']:g}")
            if 'dispatch_income' in summary:
                lines.append(f"派遣収入（売上とは別）：{summary['dispatch_income']:g}")
            lines.append("\n親しみの変化")
            for row in result['affinity_changes']:
                name=self.session.profiles.get(row['cat_id'],{}).get('name',row['cat_id'])
                lines.append(f"{name} → {row['customer_id']}：{row['change']:+g}")
            if not result['affinity_changes']:
                lines.append('交流なし')
            lines.append("\n在店猫は一晩休むと体力が全回復します。療養中の猫は復帰まで接客できません。翌日へ進みますか？")
            if messagebox.askyesno('閉店結果', '\n'.join(lines),parent=self.root):
                self.session.next_day()
                self.customer.set('')
        except (ValueError, OSError) as exc:
            messagebox.showerror('翌日へ進めません',str(exc),parent=self.root)
        self.refresh()

    def save_game(self):
        from pathlib import Path
        from tkinter import filedialog,messagebox
        from .storage.cafe_saves import save_game
        self.stop()
        self.refresh()
        current=self.session.checkpoint_path or Path('saves/cafe_day.json')
        path=filedialog.asksaveasfilename(parent=self.root,title='営業を保存',defaultextension='.json',
                                         initialdir=str(current.parent),initialfile=current.name)
        if not path:
            return False
        try:
            saved=save_game(self.session,path,auto_assign=self.auto_assign.get())
        except (OSError,ValueError,TypeError,KeyError,RuntimeError) as error:
            messagebox.showerror('営業を保存できませんでした',str(error),parent=self.root)
            return False
        self.notice.set(f'営業を保存しました：{saved}（一時停止中）')
        return True

    def open_game(self):
        from tkinter import filedialog,messagebox
        from .storage.cafe_saves import load_game
        self.stop()
        self.refresh()
        path=filedialog.askopenfilename(parent=self.root,title='営業の続きから開く',filetypes=[('営業セーブ','*.json')])
        if not path:
            return
        try:
            candidate,auto_assign=load_game(path)
            if self.session.core.operations:
                answer=messagebox.askyesnocancel('現在の営業', '現在の営業を保存してから開きますか？\n「いいえ」は現在の営業を保存せず切り替えます。',parent=self.root)
                if answer is None or (answer and not self.save_game()):
                    return
                candidate,auto_assign=load_game(path)
        except (OSError,ValueError,TypeError,KeyError,RuntimeError) as error:
            messagebox.showerror('営業を開けませんでした',str(error),parent=self.root)
            return
        self.replace_game(candidate, auto_assign)
        from .core.cafe_management import is_over
        if not is_over(candidate.core):
            self.notice.set('営業を復元しました。未保存の交流結果があるため、先に結果保存を再試行してください。' if candidate.pending else
                            '営業を復元しました。一時停止中です。「営業を開始・再開」で続けられます。')

    def replace_game(self, candidate, auto_assign=False):
        self.stop()
        self.session=candidate
        self.logged=0
        self.history.delete(*self.history.get_children())
        self.types={t.name:t.id for t in candidate.interaction_config.types}
        self.target.set(next(iter(self.types)))
        self.cat_labels={f"{row['name']}（{row['cat_id']}）":row['cat_id'] for row in candidate.cat_choices()}
        self.cat_selector.configure(values=tuple(self.cat_labels))
        self.cat_choice.set(next(iter(self.cat_labels)))
        self.customer.set('')
        self.auto_assign.set(auto_assign)
        self.refresh()

    def new_game(self):
        from tkinter import messagebox
        from .cafe_start_gui import NewGameWindow
        self.stop()
        self.refresh()
        try:
            self.new_game_window = NewGameWindow(self.root, self.replace_game,
                before_start=self.save_before_new_game, previous=self.session.core, directory=self.new_game_directory)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            messagebox.showerror('初期条件を読み込めません',str(exc),parent=self.root)

    def save_before_new_game(self):
        from tkinter import messagebox
        if self.session.core.operations or self.session.pending:
            answer = messagebox.askyesnocancel('現在のゲーム',
                '現在のゲームを保存してから新しく始めますか？\n「いいえ」は現在の営業状態を保存せず切り替えます。', parent=self.new_game_window.window)
            if answer is None or (answer and not self.save_game()):
                return False
        return True

    def save_log(self):
        self.stop()
        self.refresh()
        super().save_log()

    def close(self):
        from tkinter import messagebox
        self.stop()
        self.refresh()
        if self.session.core.operations:
            answer=messagebox.askyesnocancel('営業を終了', '営業途中の状態を保存して終了しますか？\n「いいえ」は今回の営業状態を保存せず終了します。',parent=self.root)
            if answer is None or (answer and not self.save_game()):
                return
        self.root.destroy()
