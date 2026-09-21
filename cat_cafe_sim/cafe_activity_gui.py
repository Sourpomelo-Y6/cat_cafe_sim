"""派遣の出発と帰還イベントを確認する画面。"""
from .core.cafe_activities import destination, ACTIVITY_LABELS


class CafeActivityWindow:
    def __init__(self, parent, session, on_changed):
        import tkinter as tk
        from tkinter import ttk
        from .cafe_history import CafeHistoryWindow
        self.session, self.on_changed = session, on_changed
        self.window = tk.Toplevel(parent)
        self.window.title('派遣・イベント')
        self.window.geometry('800x520')
        self.window.minsize(500,400)
        self.window.transient(parent)
        self.window.grab_set()
        frame=ttk.Frame(self.window,padding=12);frame.pack(fill='both',expand=True)
        footer=ttk.Frame(frame);footer.pack(side='bottom',fill='x')
        self.send_button=ttk.Button(footer,text='選んだ猫を派遣',command=self.send)
        self.send_button.pack(side='left')
        self.receive_button=ttk.Button(footer,text='帰還・報酬を受け取る',command=self.receive)
        self.receive_button.pack(side='left',padx=4)
        self.close_button=ttk.Button(footer,text='閉じる',command=self.window.destroy)
        self.close_button.pack(side='right')
        event_controls=ttk.Frame(frame)
        event_controls.pack(fill='x',pady=(0,4))
        self.adoption_button=ttk.Button(event_controls,text='譲渡の設定・申し出…',command=self.show_adoption)
        self.adoption_button.pack(side='left')
        self.management_button=ttk.Button(event_controls,text='ストレス・家出・経営…',command=self.show_management)
        self.management_button.pack(side='left',padx=4)
        self.recruitment_button=ttk.Button(frame,text='保護猫の受け入れ…',command=self.show_recruitment)
        self.recruitment_button.pack(anchor='w',pady=(0,4))
        self.rules=destination()
        ttk.Label(frame,text=f"{self.rules['name']}：{self.rules['days']}日 / 報酬 {self.rules['reward']:g} / 疲労 {self.rules['max_fatigue']:g}以下の健康な猫",wraplength=460).pack(anchor='w')
        ttk.Label(frame,text='準備中に出発します。店内の席数を超える担当可能な猫が必要です。帰還後は出勤設定を確認してください。',wraplength=460).pack(anchor='w')
        self.notice=tk.StringVar()
        ttk.Label(frame,textvariable=self.notice,wraplength=460).pack(anchor='w')
        self.cats=CafeHistoryWindow.table(frame,('猫','活動','体調','疲労'))
        self.events=CafeHistoryWindow.table(frame,('対象猫','派遣先','状態','残り日数','報酬'))
        self.events.bind('<<TreeviewSelect>>',lambda event:self.buttons())
        self.window.bind('<Escape>',lambda event:self.window.destroy())
        self.refresh()

    def buttons(self):
        from .core.cafe_activities import waiting_events
        core=self.session.core
        from .core.cafe_player import active
        from .core.cafe_management import is_over
        self.send_button.state(['!disabled'] if core.can_set_shifts and not is_over(core) and not active(core) and not self.session.pending and not waiting_events(core) else ['disabled'])
        selected=self.events.selection()
        can_receive=bool(selected) and core.activities['events'][selected[0]]['status']=='waiting' and not self.session.pending and not is_over(core)
        self.receive_button.state(['!disabled'] if can_receive else ['disabled'])
        can_open = core.recruitment is not None or (core.can_set_shifts and not is_over(core) and not active(core) and not self.session.pending and not waiting_events(core))
        self.recruitment_button.state(['!disabled'] if can_open else ['disabled'])

    def refresh(self):
        from .cafe_health_text import health_text
        from .core.cafe_activities import waiting_events
        core=self.session.core
        selected=self.cats.selection()
        self.cats.delete(*self.cats.get_children());self.events.delete(*self.events.get_children())
        for key,cat in core.cats.items():
            self.cats.insert('','end',iid=key,values=(self.session.profiles.get(key,{}).get('name',key),ACTIVITY_LABELS[core.activity(key)],health_text(cat.health_status,cat.recovery_days_remaining),f'{cat.fatigue:g}'))
        if selected:self.cats.selection_set(selected[0])
        elif core.cats:self.cats.selection_set(next(iter(core.cats)))
        labels={'travelling':'派遣中','waiting':'帰還・確認待ち','resolved':'受取済み'}
        if core.activities:
            for key,e in core.activities['events'].items():
                self.events.insert('','end',iid=key,values=(self.session.profiles.get(e['cat_id'],{}).get('name',e['cat_id']),e['destination']['name'],labels[e['status']],e['remaining'],f"{e['destination']['reward']:g}"))
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
        self.buttons()

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
        if not messagebox.askyesno('派遣の出発', '今から派遣し、帰還まで店内接客から外します。出発しますか？',parent=self.window):return
        self.perform(lambda:self.session.dispatch(selected[0],self.rules))

    def receive(self):
        selected=self.events.selection()
        if selected:self.perform(lambda:self.session.resolve_activity(selected[0]))

    def perform(self, action):
        from tkinter import messagebox
        try:action()
        except (ValueError,OSError) as exc:messagebox.showerror('派遣・イベントを処理できません',str(exc),parent=self.window)
        self.on_changed();self.refresh()
