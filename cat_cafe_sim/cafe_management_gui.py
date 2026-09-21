"""ストレス・家出・帰還と経営終了の確認画面。"""
from .core.cafe_management import rules, waiting, is_over
from .core.cafe_activities import ACTIVITY_LABELS, waiting_events


class CafeManagementWindow:
    def __init__(self, parent, session, on_changed):
        import tkinter as tk
        from tkinter import ttk
        from .cafe_history import CafeHistoryWindow
        self.session, self.on_changed = session, on_changed
        self.window = tk.Toplevel(parent)
        self.window.title('ストレス・家出・経営')
        self.window.geometry('800x560')
        self.window.minsize(500, 440)
        self.window.transient(parent)
        self.window.grab_set()
        frame = ttk.Frame(self.window,padding=12)
        frame.pack(fill='both',expand=True)
        footer = ttk.Frame(frame)
        footer.pack(side='bottom',fill='x')
        self.enable_button = ttk.Button(footer,text='経営ルールを開始',command=self.enable)
        self.enable_button.pack(side='left')
        self.return_button = ttk.Button(footer,text='帰還・費用を確定',command=self.receive)
        self.return_button.pack(side='left',padx=4)
        self.close_button = ttk.Button(footer,text='閉じる',command=self.close)
        self.close_button.pack(side='right')
        self.status = tk.StringVar()
        self.notice = tk.StringVar()
        self.detail = tk.StringVar()
        ttk.Label(frame,textvariable=self.status,wraplength=460).pack(anchor='w')
        ttk.Label(frame,textvariable=self.notice,wraplength=460).pack(anchor='w',pady=4)
        self.cats = CafeHistoryWindow.table(frame,('猫','活動','ストレス'))
        ttk.Label(frame,textvariable=self.detail,wraplength=460).pack(anchor='w',pady=4)
        self.events = CafeHistoryWindow.table(frame,('家出日','猫','状態','残り日数','子猫の引き渡し費用'))
        self.events.bind('<<TreeviewSelect>>',lambda event:self.selection())
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        self.window.bind('<Escape>',lambda event:self.close())
        self.refresh()

    def close(self):
        parent=self.window.master
        self.window.destroy()
        if parent.winfo_exists():
            parent.grab_set()
        self.on_changed()

    def refresh(self):
        from .core.cafe_player import active
        core=self.session.core
        data=core.management
        selected=self.events.selection()
        self.cats.delete(*self.cats.get_children())
        self.events.delete(*self.events.get_children())
        for key in core.cats:
            self.cats.insert('','end',iid=key,values=(self.session.profiles.get(key,{}).get('name',key),
                ACTIVITY_LABELS[core.activity(key)],f"{data['stress'][key]:g}" if data else '未導入'))
        self.enable_button.state(['!disabled'] if not data and core.can_set_shifts and core.health_rules
                                 and not self.session.pending and not waiting_events(core) and not active(core) else ['disabled'])
        self.status.set(f"所持金 {core.funds:g} · 人気 {data['popularity']:g} / 100" if data else
                        '未導入：開始するとストレス・家出・人気・費用・ゲームオーバーが有効になります。')
        if data:
            for key,event in data['events'].items():
                label={'missing':'行方不明','waiting':'帰還・確認待ち','resolved':'帰還済み'}[event['status']]
                cost = data['rules']['kitten_cost'] if event['kitten'] else 0
                self.events.insert('','end',iid=key,values=(event['departed_day'],
                    self.session.profiles.get(event['cat_id'],{}).get('name',event['cat_id']),label,
                    event['remaining'],f'{cost:g}' if event['status']!='missing' else '帰還時に判明'))
        pending=waiting(core)
        if selected and self.events.exists(selected[0]):
            self.events.selection_set(selected[0])
        elif pending:
            self.events.selection_set(pending[0]['id'])
        elif self.events.get_children():
            self.events.selection_set(self.events.get_children()[-1])
        if is_over(core):
            reason='資金が0以下になりました。' if data['game_over']['reason']=='funds' else '店の人気が0になりました。'
            self.notice.set('ゲームオーバー：'+reason+' 閲覧・保存はできますが進行はできません。')
        elif not core.health_rules:
            self.notice.set('先に「出勤・休養…」で設定を保存し、健康ルールを有効にしてください。')
        elif self.session.pending:
            self.notice.set('接客結果の保存を先に再試行してください。')
        elif pending:
            self.notice.set('帰還を確認してください。子猫は外部に引き渡し、費用だけを精算します。')
        else:
            self.notice.set('接客でストレス増加、休養や好結果の交流で回復。高ストレスの猫が家出すると人気が下がります。')
        self.selection()

    def selection(self):
        selected=self.events.selection()
        data=self.session.core.management
        event=data['events'][selected[0]] if selected and data else None
        can_resolve=event and event['status']=='waiting' and not self.session.pending and not is_over(self.session.core)
        self.return_button.state(['!disabled'] if can_resolve else ['disabled'])
        self.detail.set('子猫を連れて帰還します。子猫を管理する必要はありません。' if event and event['status']!='missing' and event['kitten'] else
                        '帰還後は出勤設定を確認してください。不在期間は閉店・休業で進みます。')

    def enable(self):
        from tkinter import messagebox
        selected=rules()
        if not messagebox.askyesno('経営ルールの開始',
            f"所持金を最低{selected['starting_funds']:g}まで一度だけ補充します。\n"
            '以降、家出で人気が下がり、子猫の引き渡し費用が発生します。資金または人気が0以下ならゲームオーバーです。\n開始後は解除できません。開始しますか？',
            parent=self.window):
            return
        self.perform(lambda:self.session.enable_management(selected))

    def receive(self):
        from tkinter import messagebox
        selected=self.events.selection()
        if not selected:return
        event=self.session.core.management['events'][selected[0]]
        cost=self.session.core.management['rules']['kitten_cost'] if event['kitten'] else 0
        if not messagebox.askyesno('帰還と費用の確定',f"猫の帰還を確定します。引き渡し費用は{cost:g}です。\n"
            '精算後の資金が0以下ならゲームオーバーになります。確定しますか？',parent=self.window):
            return
        self.perform(lambda:self.session.resolve_missing(selected[0]))

    def perform(self, action):
        from tkinter import messagebox
        try:action()
        except (ValueError,OSError) as exc:
            messagebox.showerror('経営イベントを処理できません',str(exc),parent=self.window)
        self.on_changed()
        self.refresh()
