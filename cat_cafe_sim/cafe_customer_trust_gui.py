"""お客さんの信頼回復方針と永久離脱履歴。"""
from .core.cafe_customer_trust import waiting
from .cafe_customers import customer_name


class CafeCustomerTrustWindow:
    def __init__(self,parent,session,on_changed):
        import tkinter as tk
        from tkinter import ttk
        from .cafe_history import CafeHistoryWindow
        self.session,self.on_changed=session,on_changed
        self.window=tk.Toplevel(parent);self.window.title('お客さんの信頼回復')
        self.window.geometry('720x420');self.window.minsize(520,360);self.window.transient(parent);self.window.grab_set()
        frame=ttk.Frame(self.window,padding=12);frame.pack(fill='both',expand=True)
        footer=ttk.Frame(frame);footer.pack(side='bottom',fill='x')
        self.recover=ttk.Button(footer,text='信頼回復に取り組む',command=lambda:self.resolve('recover'));self.recover.pack(side='left')
        self.ignore=ttk.Button(footer,text='対応しない',command=lambda:self.resolve('ignore'));self.ignore.pack(side='left',padx=4)
        ttk.Button(footer,text='閉じる',command=self.close).pack(side='right')
        self.description=ttk.Label(frame,text='来店停止を繰り返したお客さんです。信頼回復を選ぶと、停止期間後の接客が「満足」なら回復し、「不満」なら永久離脱します。費用はかかりません。',wraplength=600)
        self.description.pack(anchor='w')
        self.notice=tk.StringVar();ttk.Label(frame,textvariable=self.notice,wraplength=600).pack(anchor='w',pady=6)
        self.events=CafeHistoryWindow.table(frame,('発生日','お客さん','停止回数','方針・結果'))
        self.refresh();self.window.protocol('WM_DELETE_WINDOW',self.close);self.window.bind('<Escape>',lambda e:self.close())

    def refresh(self):
        core=self.session.core;pending=waiting(core);self.events.delete(*self.events.get_children())
        labels={'waiting':'回答待ち','recovery':'信頼回復中','recovered':'回復','departed':'永久離脱'}
        for event in core.customer_trust['events'].values():
            result=event['outcome'] or event['status']
            self.events.insert('','end',iid=event['id'],values=(event['day'],customer_name(event['customer_id']),event['suspensions'],labels[result]))
        self.notice.set(f"{customer_name(pending[0]['customer_id'])}が離脱を考えています。方針を選んでください。" if pending else '回答待ちの信頼回復イベントはありません。')
        state=['!disabled'] if pending and not self.session.pending else ['disabled']
        self.recover.state(state);self.ignore.state(state)

    def resolve(self,choice):
        from tkinter import messagebox
        pending=waiting(self.session.core)
        if not pending:return
        try:self.session.resolve_customer_trust(pending[0]['id'],choice)
        except (ValueError,OSError) as exc:messagebox.showerror('信頼回復を確定できません',str(exc),parent=self.window)
        self.refresh();self.on_changed()

    def close(self):
        self.window.destroy();self.on_changed()
