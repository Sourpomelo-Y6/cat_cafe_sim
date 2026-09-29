"""待合スペース強化の費用と効果を確認する画面。"""
from .core.cafe_waiting_area import reason,purchased,queue_capacity,max_wait_ticks


class CafeWaitingAreaWindow:
    def __init__(self,parent,session,on_changed):
        import tkinter as tk
        from tkinter import ttk
        self.session,self.on_changed=session,on_changed
        self.window=tk.Toplevel(parent);self.window.title('待合スペースの強化')
        self.window.geometry('520x300');self.window.minsize(480,280);self.window.transient(parent);self.window.grab_set()
        frame=ttk.Frame(self.window,padding=12);frame.pack(fill='both',expand=True)
        footer=ttk.Frame(frame);footer.pack(side='bottom',fill='x')
        self.purchase_button=ttk.Button(footer,text='待合スペースを強化する',command=self.purchase);self.purchase_button.pack(side='left')
        self.close_button=ttk.Button(footer,text='閉じる',command=self.window.destroy);self.close_button.pack(side='right')
        self.details=tk.StringVar();self.notice=tk.StringVar()
        ttk.Label(frame,textvariable=self.details,wraplength=470).pack(anchor='w',pady=8)
        ttk.Label(frame,textvariable=self.notice,wraplength=470).pack(anchor='w',pady=8)
        self.window.bind('<Escape>',lambda event:self.window.destroy());self.refresh()

    def refresh(self):
        core=self.session.core;selected=core.waiting_area['rules'];bought=purchased(core)
        if bought:
            self.details.set(f"強化済み（{bought['day']}日目・費用 {bought['cost']:g}）\n待機上限：{queue_capacity(core)}人 / 待機猶予：{max_wait_ticks(core)}tick\n日次運営費への追加：{selected['daily_cost']:g}")
            self.purchase_button.configure(text='強化済み')
        else:
            self.details.set(f"待機上限：{core.config.queue_capacity} → {core.config.queue_capacity+selected['queue_bonus']}人\n待機猶予：{core.config.max_wait_ticks} → {core.config.max_wait_ticks+selected['wait_bonus']}tick\n購入費：{selected['cost']:g} / 日次運営費：＋{selected['daily_cost']:g}\n購入後の所持金：{core.funds-selected['cost']:g}")
        problem='先に接客結果の保存を再試行してください。' if self.session.pending else reason(core)
        self.notice.set(problem or '強化は購入当日から有効です。購入後の取り消し・返金はできません。')
        self.purchase_button.state(['disabled'] if problem else ['!disabled'])

    def purchase(self):
        from tkinter import messagebox
        core=self.session.core;selected=core.waiting_area['rules']
        if not messagebox.askyesno('待合スペースの強化',f"費用{selected['cost']:g}で強化しますか？\n購入後の所持金：{core.funds-selected['cost']:g}",parent=self.window):return
        try:self.session.purchase_waiting_area()
        except (ValueError,OSError) as exc:messagebox.showerror('強化できません',str(exc),parent=self.window)
        self.on_changed();self.refresh()
