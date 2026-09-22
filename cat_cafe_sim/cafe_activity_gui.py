"""派遣の出発と帰還イベントを確認する画面。"""
from .core.cafe_activities import destinations, dispatch_reason, ACTIVITY_LABELS, reward
from .core.cafe_traits import trait, dispatch_terms


class CafeActivityWindow:
    def __init__(self, parent, session, on_changed, *, show_navigation=True):
        import tkinter as tk
        from tkinter import ttk
        from .cafe_history import CafeHistoryWindow
        self.session, self.on_changed = session, on_changed
        self.window = tk.Toplevel(parent)
        self.window.title('派遣・帰還')
        self.show_navigation = show_navigation
        self.window.geometry('800x520')
        self.window.minsize(500,400)
        self.window.transient(parent)
        self.window.grab_set()
        frame=ttk.Frame(self.window,padding=12);frame.pack(fill='both',expand=True)
        footer=ttk.Frame(frame);footer.pack(side='bottom',fill='x')
        self.selection_info = tk.StringVar()
        ttk.Label(footer, textvariable=self.selection_info, wraplength=460).pack(side='top', anchor='w')
        self.send_button=ttk.Button(footer,text='選んだ猫を派遣',command=self.send)
        self.send_button.pack(side='left')
        self.receive_button=ttk.Button(footer,text='帰還・報酬を受け取る',command=self.receive)
        self.receive_button.pack(side='left',padx=4)
        self.close_button=ttk.Button(footer,text='閉じる',command=self.window.destroy)
        self.close_button.pack(side='right')
        event_controls=ttk.Frame(frame)
        if show_navigation:
            event_controls.pack(fill='x',pady=(0,4))
        self.adoption_button=ttk.Button(event_controls,text='譲渡の設定・申し出…',command=self.show_adoption)
        self.adoption_button.pack(side='left')
        self.management_button=ttk.Button(event_controls,text='ストレス・家出・経営…',command=self.show_management)
        self.management_button.pack(side='left',padx=4)
        extra_controls = ttk.Frame(frame)
        if show_navigation:
            extra_controls.pack(fill='x', pady=(0,4))
        self.patron_button = ttk.Button(extra_controls, text='有力者目標・結果…', command=self.show_patron)
        self.patron_button.pack(side='right')
        self.recruitment_button=ttk.Button(extra_controls,text='保護猫の受け入れ…',command=self.show_recruitment)
        self.recruitment_button.pack(side='left')
        self.base_destinations = destinations()
        self.destinations = list(self.base_destinations)
        self.destination_choice = ttk.Combobox(frame, state='readonly', values=[row['name'] for row in self.destinations])
        self.destination_choice.pack(fill='x')
        self.destination_choice.current(0)
        self.rules = self.destinations[0]
        self.destination_info = tk.StringVar()
        ttk.Label(frame, textvariable=self.destination_info, wraplength=460).pack(anchor='w')
        self.destination_choice.bind('<<ComboboxSelected>>', lambda event: self.select_destination())
        ttk.Label(frame,text='準備中に出発します。店内の席数を超える担当可能な猫が必要です。帰還後は出勤設定を確認してください。',wraplength=460).pack(anchor='w')
        self.notice=tk.StringVar()
        ttk.Label(frame,textvariable=self.notice,wraplength=460).pack(anchor='w')
        tables = ttk.Frame(frame)
        tables.pack(fill='both', expand=True)
        tables.columnconfigure(0, weight=1)
        for row in (0, 1):
            tables.rowconfigure(row, weight=1, uniform='tables')
        cats_frame = ttk.Frame(tables)
        cats_frame.grid(row=0, column=0, sticky='nsew')
        events_frame = ttk.Frame(tables)
        events_frame.grid(row=1, column=0, sticky='nsew')
        self.cats=CafeHistoryWindow.table(cats_frame,('猫','活動','体調','疲労','特性','参加条件'))
        self.events=CafeHistoryWindow.table(events_frame,('対象猫','派遣先','状態','残り日数','報酬','帰還ストレス増加'))
        self.cats.bind('<<TreeviewSelect>>', lambda event: self.buttons())
        self.events.bind('<<TreeviewSelect>>',lambda event:self.buttons())
        self.window.bind('<Escape>',lambda event:self.window.destroy())
        self.refresh()

    def select_destination(self):
        self.rules = self.destinations[self.destination_choice.current()]
        self.refresh()

    def buttons(self):
        from .core.cafe_activities import waiting_events
        core=self.session.core
        from .core.cafe_player import active
        from .core.cafe_management import is_over
        cats = self.cats.selection()
        reason = dispatch_reason(core, cats[0], self.rules) if cats else '猫を選んでください。'
        self.send_button.state(['!disabled'] if not reason and not self.session.pending else ['disabled'])
        if self.session.pending:
            self.selection_info.set('交流結果の保存を再試行してください。')
        elif reason:
            self.selection_info.set(reason)
        else:
            terms = dispatch_terms(core, cats[0], self.rules['reward'])
            self.selection_info.set(f"参加できます：報酬 {terms['reward']:g} / 帰還時ストレス ＋{terms['stress']:g}")
        selected=self.events.selection()
        can_receive=bool(selected) and core.activities['events'][selected[0]]['status']=='waiting' and not self.session.pending and not is_over(core)
        from .core.cafe_dispatch_encounters import pending as choice_pending, selected as answered
        event = core.activities['events'][selected[0]] if selected else None
        if event and choice_pending(event):
            self.receive_button.configure(text='出来事に回答…')
            self.receive_button.state(['!disabled'] if not self.session.pending and not is_over(core) else ['disabled'])
        elif event and answered(event) and event['status']!='waiting':
            self.receive_button.configure(text='出来事の記録…')
            self.receive_button.state(['!disabled'])
        else:
            self.receive_button.configure(text='帰還・報酬を受け取る')
            self.receive_button.state(['!disabled'] if can_receive else ['disabled'])
        can_open = core.recruitment is not None or (core.can_set_shifts and not is_over(core) and not active(core) and not self.session.pending and not waiting_events(core))
        self.recruitment_button.state(['!disabled'] if can_open else ['disabled'])

    def refresh(self):
        from .cafe_health_text import health_text
        from .core.cafe_activities import waiting_events
        core=self.session.core
        selected_id = self.rules['id']
        self.destinations = list(self.base_destinations)
        if core.patron:
            self.destinations.append(core.patron['rules']['destination'])
        self.destination_choice.configure(values=[row['name'] for row in self.destinations])
        index = next((i for i, row in enumerate(self.destinations) if row['id'] == selected_id), 0)
        self.destination_choice.current(index)
        self.rules = self.destinations[index]
        self.patron_button.configure(text=(f"有力者 {core.patron['satisfaction']:g}/{core.patron['rules']['target']:g}・結果…" if core.patron else '有力者目標・結果…'))
        required = self.rules.get('required_trait_name', '指定なし')
        self.destination_info.set(f"{self.rules['days']}日 / 基本報酬 {self.rules['reward']:g} / 疲労{self.rules['max_fatigue']:g}以下 / 必要特性：{required}")
        selected=self.cats.selection()
        self.cats.delete(*self.cats.get_children());self.events.delete(*self.events.get_children())
        for key,cat in core.cats.items():
            self.cats.insert('','end',iid=key,values=(self.session.profiles.get(key,{}).get('name',key),ACTIVITY_LABELS[core.activity(key)],health_text(cat.health_status,cat.recovery_days_remaining),f'{cat.fatigue:g}',(trait(core,key) or {}).get('name','なし'), dispatch_reason(core,key,self.rules) or '参加できます'))
        if selected:self.cats.selection_set(selected[0])
        elif core.cats:self.cats.selection_set(next(iter(core.cats)))
        labels={'travelling':'派遣中','waiting':'帰還・確認待ち','resolved':'受取済み'}
        if core.activities:
            for key,e in core.activities['events'].items():
                self.events.insert('','end',iid=key,values=(self.session.profiles.get(e['cat_id'],{}).get('name',e['cat_id']),e['destination']['name'],('派遣中・回答待ち' if e.get('encounter',{}).get('status')=='waiting' else labels[e['status']]),e['remaining'],f"{reward(core,e):g}", f"{dispatch_terms(core,e['cat_id'],e['destination']['reward'])['stress']:g}" if e['status']!='resolved' else '確定済み'))
        waiting=waiting_events(core)
        dispatch_waiting=[event for event in waiting if event.get('kind')=='dispatch_return']
        if dispatch_waiting:self.events.selection_set(dispatch_waiting[0]['id'])
        from .core.cafe_adoption import waiting as adoption_waiting
        offers=adoption_waiting(core)
        from .core.cafe_management import waiting as return_waiting, is_over
        returns=return_waiting(core)
        self.management_button.configure(text=f'家出猫の帰還…（{len(returns)}件）' if returns else 'ストレス・家出・経営…')
        self.adoption_button.configure(text=f'譲渡の設定・申し出…（回答待ち{len(offers)}件）' if offers else '譲渡の設定・申し出…')
        self.notice.set('ゲームオーバーです。「ストレス・家出・経営…」で結果を確認できます。' if is_over(core) else
                        '家出猫が帰還しています。経営画面で帰還・費用を確認してください。' if returns else
                        '交流結果の保存を再試行してから操作してください。' if self.session.pending else
                        '譲渡の申し出があります。上の「譲渡の設定・申し出…」で回答してください。' if offers else
                        '帰還結果の確認待ちです。受け取るまで営業・翌日への進行は停止します。' if waiting else
                        '派遣は閉店・休業で1日進みます。画面を閉じた後も営業は一時停止します。')
        from .core.cafe_dispatch_encounters import waiting as choice_waiting
        if choice_waiting(core) and not is_over(core) and not self.session.pending:
            self.notice.set('派遣中の出来事が回答待ちです。対象を選び「出来事に回答…」から回答してください。')
        if not self.show_navigation and (returns or offers):
            self.notice.set('家出・譲渡の確認待ちです。この画面を閉じ、営業画面の「確認する」から対応できます。')
        self.buttons()

    def show_patron(self):
        from .cafe_patron_gui import CafePatronWindow
        self.patron_window = CafePatronWindow(self.window, self.session, self.changed)

    def show_management(self):
        from .cafe_management_gui import CafeManagementWindow
        self.management_window = CafeManagementWindow(self.window,self.session,self.changed)

    def show_recruitment(self):
        from tkinter import messagebox
        from .cafe_recruitment_gui import CafeRecruitmentWindow
        try:
            self.session.open_recruitment()
        except (ValueError,OSError) as exc:
            messagebox.showerror('受け入れ候補を表示できません',str(exc),parent=self.window)
            return
        self.changed()
        self.recruitment_window = CafeRecruitmentWindow(self.window,self.session,self.changed)

    def show_adoption(self):
        from .cafe_adoption_gui import CafeAdoptionWindow
        self.adoption_window = CafeAdoptionWindow(self.window, self.session, self.changed)

    def changed(self):
        self.on_changed()
        if self.window.winfo_exists():
            self.refresh()

    def send(self):
        from tkinter import messagebox
        selected=self.cats.selection()
        if not selected:return
        terms=dispatch_terms(self.session.core,selected[0],self.rules['reward'])
        from .core.cafe_dispatch_encounters import for_destination
        encounter=for_destination(self.rules)
        note=f"\n1日目終了時に選択イベント：{encounter['title']}" if encounter else ''
        if not messagebox.askyesno('派遣の出発', f"{self.rules['name']}：{self.rules['days']}日間\n報酬 {terms['reward']:g} / 帰還時ストレス ＋{terms['stress']:g}（現在の経営ルール）\n今から派遣し、帰還まで店内接客から外します。出発しますか？{note}",parent=self.window):return
        self.perform(lambda:self.session.dispatch(selected[0],self.rules))

    def receive(self):
        selected=self.events.selection()
        if not selected:return
        event=self.session.core.activities['events'][selected[0]]
        if event.get('encounter') and event['status']!='waiting':
            from .cafe_dispatch_choice_gui import CafeDispatchChoiceWindow
            self.choice_window=CafeDispatchChoiceWindow(self.window,self.session,selected[0],self.changed)
        else:
            self.perform(lambda:self.session.resolve_activity(selected[0]))

    def perform(self, action):
        from tkinter import messagebox
        try:action()
        except (ValueError,OSError) as exc:messagebox.showerror('派遣・イベントを処理できません',str(exc),parent=self.window)
        self.on_changed();self.refresh()
