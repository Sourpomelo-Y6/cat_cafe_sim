"""営業中のお客を選び、版4交流の成果を営業へ戻す試遊画面。"""
from .human_cat_gui import ACTION_NAMES, history_row
from .relationship_presentation import greeting_text


class CafeInteractionWindow:
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
        ttk.Label(frame,text='「営業を1tick進める」で来客を待ち、お客を選んで交流を開始します。営業状態はこの画面を開いている間だけ保持します。',wraplength=820).grid(row=1,sticky='w')
        controls = ttk.Frame(frame); controls.grid(row=2,sticky='ew',pady=8)
        self.customer = tk.StringVar()
        self.queue = ttk.Combobox(controls,textvariable=self.customer,state='readonly',width=18)
        self.queue.pack(side='left')
        self.start_button=ttk.Button(controls,text='選んだお客と交流',command=lambda:self.perform(lambda:session.start(self.customer.get())))
        self.start_button.pack(side='left',padx=6)
        self.wait_button=ttk.Button(controls,text='営業を1tick進める',command=lambda:self.perform(session.step))
        self.wait_button.pack(side='left')
        self.finish_button=ttk.Button(controls,text='切り上げて会計',command=lambda:self.perform(session.finish))
        self.finish_button.pack(side='left',padx=6)
        self.retry_button=ttk.Button(controls,text='結果保存を再試行',command=lambda:self.perform(session.persist))
        self.retry_button.pack(side='left')
        ttk.Label(frame,textvariable=self.details,wraplength=820).grid(row=3,sticky='w',pady=6)
        actions=ttk.Frame(frame); actions.grid(row=4,sticky='ew')
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
        ttk.Button(frame,text='営業ログを保存…',command=self.save_log).grid(row=7,sticky='e')
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
        self.status.set(f'営業 {core.tick}/{core.config.opening_ticks} tick · '+('閉店' if core.closed else '営業中')+
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
            elif kind=='departure':
                reasons={'interaction_manual':'切り上げ', 'interaction_time_limit':'交流時間終了', 'interaction_exhausted':'体力切れ', 'closing':'閉店', 'queue_full':'待機列満員', 'wait_timeout':'待機時間終了'}
                text=f"退店 {event['customer_id']} · {reasons.get(event['reason'],event['reason'])} · 会計 {event['bill']:g}（時間 {event['base_charge']:g}＋ボーナス {event['bonus']:g}）"
            elif kind=='interaction_completed':
                r=event['result'];text=f"親しみ {r['affinity_before']:g} → {r['affinity_after']:g} · 残り体力 {r['stamina']:g}"
            else:
                names={'arrival':'来店','assigned':'着席','interaction_started':'交流開始','closed':'閉店'}
                text=f"{names.get(kind,kind)} {event.get('customer_id','')}"
            item=self.history.insert('','end',values=(event['tick'],text));self.history.see(item)
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
