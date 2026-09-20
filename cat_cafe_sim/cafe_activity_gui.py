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
        self.send_button.state(['!disabled'] if core.can_set_shifts and not active(core) and not self.session.pending and not waiting_events(core) else ['disabled'])
        selected=self.events.selection()
        can_receive=bool(selected) and core.activities['events'][selected[0]]['status']=='waiting' and not self.session.pending
        self.receive_button.state(['!disabled'] if can_receive else ['disabled'])

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
        if waiting:self.events.selection_set(waiting[0]['id'])
        self.notice.set('交流結果の保存を再試行してから操作してください。' if self.session.pending else
                        '帰還結果の確認待ちです。受け取るまで営業・翌日への進行は停止します。' if waiting else
                        '派遣は閉店・休業で1日進みます。画面を閉じた後も営業は一時停止します。')
        self.buttons()

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
