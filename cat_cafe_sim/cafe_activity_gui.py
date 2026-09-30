"""派遣の出発と帰還イベントを確認する画面。"""
from .core.cafe_activities import destinations, dispatch_reason, ACTIVITY_LABELS, reward
from .core.cafe_traits import trait, dispatch_terms
from .core.cafe_items import for_destination as item_reward


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
        self.result_button=ttk.Button(footer,text='派遣結果・内訳…',command=self.show_result)
        self.result_button.pack(side='left',padx=4)
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
        self.base_destinations = destinations(session.core)
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
        self.cats=CafeHistoryWindow.table(cats_frame,('猫','活動','体調','疲労','特性','経験・得意','参加条件'))
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
        if cats and self.rules['id'] == 'mountain_lodge_visit' and core.dispatch_trouble:
            from .core.cafe_dispatch_trouble import probability
            self.selection_info.set(self.selection_info.get()+f'\nこの猫のトラブル発生率：{probability(core,cats[0])*100:g}%（出発時に固定）')
        if cats:
            from .core.cafe_dispatch_match import description,terms as welcome_terms
            self.selection_info.set(self.selection_info.get()+'\n'+description(core,cats[0],self.rules))
            if not reason:
                bonus=(welcome_terms(core,cats[0],self.rules) or {}).get('reward_bonus',0)
                self.selection_info.set(self.selection_info.get()+f'\n報酬見込み {terms["reward"]+bonus:g}（歓迎ボーナス込み）')
            from .core.cafe_growth import description as growth_description
            self.selection_info.set(self.selection_info.get()+'\n'+growth_description(core,cats[0]))
        selected=self.events.selection()
        self.result_button.state(['!disabled'] if selected else ['disabled'])
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
        if event and event.get('trouble', {}).get('missing_day') is not None:
            from .core.cafe_dispatch_trouble import pending as trouble_pending
            if trouble_pending(event):
                self.receive_button.configure(text='家出トラブルに対応…')
                self.receive_button.state(['!disabled'] if not self.session.pending and not is_over(core) else ['disabled'])
            elif event['status'] not in ('waiting',):
                self.receive_button.configure(text='トラブルの記録…')
                self.receive_button.state(['!disabled'])
            else:
                self.receive_button.configure(text='帰還を確認する（報酬なし）')
                self.receive_button.state(['!disabled'] if can_receive else ['disabled'])
        introduction = event.get('introduction') if event else None
        if introduction and event['status']=='resolved':
            self.receive_button.configure(text='猫の紹介…' if introduction['status']=='waiting' else '猫紹介の記録…')
            self.receive_button.state(['!disabled'])
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
        from .core.cafe_dispatch_match import description as welcome_description
        self.destination_info.set(f"{self.rules['days']}日 / 基本報酬 {self.rules['reward']:g} / 疲労{self.rules['max_fatigue']:g}以下 / 必要特性：{required}")
        from .core.cafe_dispatch_unlocks import description as unlock_description
        self.destination_info.set(self.destination_info.get()+'\n'+unlock_description(core,self.rules['id']))
        item = item_reward(self.rules)
        if item:
            self.destination_info.set(self.destination_info.get()+f" / {item['name']} ×1（ストレス −{item['stress_relief']:g}）")
        if self.rules['id'] == 'mountain_lodge_visit' and core.dispatch_trouble:
            rule = core.dispatch_trouble
            self.destination_info.set(self.destination_info.get()+f"\n1日目に家出トラブル：確率{rule['base_probability']*100:g}〜{(rule['base_probability']+rule['stress_probability'])*100:g}%（ストレスによる）。中断報酬0・捜索費{rule['search_cost']:g}、または{rule['missing_days']}日後の帰還待ち。")
        selected=self.cats.selection()
        previous_events=self.events.selection()
        self.cats.delete(*self.cats.get_children());self.events.delete(*self.events.get_children())
        from .core.cafe_growth import summary as growth_summary
        for key,cat in core.cats.items():
            self.cats.insert('','end',iid=key,values=(self.session.profiles.get(key,{}).get('name',key),ACTIVITY_LABELS[core.activity(key)],health_text(cat.health_status,cat.recovery_days_remaining),f'{cat.fatigue:g}',(trait(core,key) or {}).get('name','なし'),growth_summary(core,key),(dispatch_reason(core,key,self.rules) or '参加できます')+' / '+welcome_description(core,key,self.rules)))
        if selected:self.cats.selection_set(selected[0])
        elif core.cats:self.cats.selection_set(next(iter(core.cats)))
        labels={'missing':'派遣中断・行方不明','travelling':'派遣中','waiting':'帰還・確認待ち','resolved':'受取済み'}
        if core.activities:
            for key,e in core.activities['events'].items():
                self.events.insert('','end',iid=key,values=(self.session.profiles.get(e['cat_id'],{}).get('name',e['cat_id']),e['destination']['name'],('家出トラブル・回答待ち' if e.get('trouble',{}).get('status')=='waiting' else '猫紹介・回答待ち' if e.get('introduction',{}).get('status')=='waiting' else '派遣中・回答待ち' if e.get('encounter',{}).get('status')=='waiting' else labels[e['status']]),e['remaining'],f"{reward(core,e):g}" + (f" + {e['item_reward']['name']} ×1" if 'item_reward' in e else ''), f"{dispatch_terms(core,e['cat_id'],e['destination']['reward'])['stress']:g}" if e['status']!='resolved' else '確定済み'))
        waiting=waiting_events(core)
        dispatch_waiting=[event for event in waiting if event.get('kind')=='dispatch_return']
        if previous_events and previous_events[0] in self.events.get_children():self.events.selection_set(previous_events[0])
        elif dispatch_waiting:self.events.selection_set(dispatch_waiting[0]['id'])
        elif self.events.get_children():self.events.selection_set(self.events.get_children()[-1])
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
        from .core.cafe_dispatch_introduction import waiting as introduction_waiting
        if introduction_waiting(core) and not is_over(core) and not self.session.pending:
            self.notice.set('派遣先からの猫紹介が回答待ちです。対象を選び「猫の紹介…」から迎えるか見送るか選んでください。')
        from .core.cafe_dispatch_trouble import waiting as trouble_waiting
        if trouble_waiting(core) and not is_over(core) and not self.session.pending:
            self.notice.set('山あいの宿で家出トラブルが起きています。対象を選び「家出トラブルに対応…」から対応してください。')
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
        from .core.cafe_dispatch_match import description
        welcome_note='\n'+description(self.session.core,selected[0],self.rules)
        note=f"\n1日目終了時に選択イベント：{encounter['title']}" if encounter else ''
        from .core.cafe_dispatch_introduction import for_departure
        if for_departure(self.session.core,self.rules,set()) is not None:
            note += '\n帰還報酬を受け取った後、準備中に保護猫の紹介を確認できます。'
        if self.rules['id'] == 'mountain_lodge_visit' and self.session.core.dispatch_trouble:
            from .core.cafe_dispatch_trouble import probability
            rule = self.session.core.dispatch_trouble
            note += f"\n1日目の家出トラブル発生率 {probability(self.session.core,selected[0])*100:g}%。中断時は報酬0。捜索費{rule['search_cost']:g}で連れ戻すか、費用なしで{rule['missing_days']}日後の帰還を待ちます。"
        item = item_reward(self.rules)
        if item:
            note += f"\n帰還時に {item['name']} ×1（準備中に在店猫のストレス −{item['stress_relief']:g}）"
        if not messagebox.askyesno('派遣の出発', f"{self.rules['name']}：{self.rules['days']}日間\n報酬 {terms['reward']:g} / 帰還時ストレス ＋{terms['stress']:g}（現在の経営ルール）\n今から派遣し、帰還まで店内接客から外します。出発しますか？{welcome_note}{note}",parent=self.window):return
        self.perform(lambda:self.session.dispatch(selected[0],self.rules))

    def receive(self):
        selected=self.events.selection()
        if not selected:return
        event=self.session.core.activities['events'][selected[0]]
        if event.get('trouble',{}).get('missing_day') is not None and event['status']!='waiting':
            from .cafe_dispatch_trouble_gui import CafeDispatchTroubleWindow
            self.trouble_window = CafeDispatchTroubleWindow(self.window, self.session, selected[0], self.changed)
        elif event.get('introduction') and event['status']=='resolved':
            from .cafe_dispatch_introduction_gui import CafeDispatchIntroductionWindow
            self.introduction_window = CafeDispatchIntroductionWindow(self.window, self.session, selected[0], self.changed)
        elif event.get('encounter') and event['status']!='waiting':
            from .cafe_dispatch_choice_gui import CafeDispatchChoiceWindow
            self.choice_window=CafeDispatchChoiceWindow(self.window,self.session,selected[0],self.changed)
        else:
            self.perform(lambda:self.session.resolve_activity(selected[0]))

    def perform(self, action):
        from tkinter import messagebox
        try:action()
        except (ValueError,OSError) as exc:messagebox.showerror('派遣・イベントを処理できません',str(exc),parent=self.window)
        self.on_changed();self.refresh()

    def show_result(self):
        selected=self.events.selection()
        if not selected:return
        import tkinter as tk
        from tkinter import ttk
        from .cafe_dispatch_results import result_text
        event=self.session.core.activities['events'][selected[0]]
        window=tk.Toplevel(self.window);self.result_window=window
        window.title('派遣結果・報酬内訳');window.geometry('560x440');window.minsize(400,300)
        window.transient(self.window)
        frame=ttk.Frame(window,padding=12);frame.pack(fill='both',expand=True)
        ttk.Button(frame,text='閉じる',command=window.destroy).pack(side='bottom',anchor='e')
        ttk.Label(frame,text=event['destination']['name']).pack(anchor='w')
        body=ttk.Frame(frame);body.pack(fill='both',expand=True)
        text=tk.Text(body,wrap='word',width=40,height=10);self.result_text=text
        scroll=ttk.Scrollbar(body,orient='vertical',command=text.yview)
        text.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');text.pack(fill='both',expand=True)
        text.insert('1.0',result_text(self.session.core,event));text.configure(state='disabled')
        window.bind('<Escape>',lambda event:window.destroy())
