"""営業前に対応を選ぶ店舗イベント画面。"""


class CafeStoreEventWindow:
    def __init__(self,parent,session,on_changed):
        import tkinter as tk
        from tkinter import ttk
        self.session,self.on_changed=session,on_changed
        from .core.cafe_store_events import waiting
        event=waiting(session.core)
        self.window=tk.Toplevel(parent);self.window.title('店舗イベントへの対応')
        self.window.geometry('620x300');self.window.minsize(520,280);self.window.transient(parent);self.window.grab_set()
        frame=ttk.Frame(self.window,padding=12);frame.pack(fill='both',expand=True)
        selected=session.core.store_events['rules'];seat_count=len(session.core.seats) if hasattr(session.core,'seats') else 1
        if event['type']=='support':
            details=("保護団体から猫の保護活動への支援を求められました。\n\n"
                     f"支援する：資金 {selected['support_full_cost']:g} を使い、閉店時に人気＋{selected['support_full_popularity']:g}。\n"
                     f"少額支援する：資金 {selected['support_small_cost']:g} を使い、閉店時に人気＋{selected['support_small_popularity']:g}。\n"
                     "見送る：資金と人気は変化しません。")
            buttons=(('支援する','full'),('少額支援する','small'),('見送る','decline'))
        else:
            details=(f"店内設備に不調が見つかりました。今日の営業方法を選んでください。\n\n"
                     f"修理する：運営費に {selected['trouble_cost']:g} を追加し、全席で営業します。\n"
                     f"応急処置する：追加費用なし。今日は {min(selected['trouble_seat_loss'],seat_count)} 席を使用停止します。\n"
                     "休業する：来客なしで在店猫を休ませ、そのまま翌日へ進みます。")
            buttons=(('修理する','repair'),('応急処置する','patch'))
        ttk.Label(frame,text=details,wraplength=570,justify='left').pack(anchor='w',pady=8)
        footer=ttk.Frame(frame);footer.pack(side='bottom',fill='x')
        for index,(text,choice) in enumerate(buttons):
            ttk.Button(footer,text=text,command=lambda value=choice:self.resolve(value)).pack(side='left',padx=(0 if index==0 else 4,0))
        if event['type']=='trouble':ttk.Button(footer,text='休業する',command=self.close_day).pack(side='left',padx=4)
        ttk.Button(footer,text='閉じる',command=self.close).pack(side='right')
        self.window.protocol('WM_DELETE_WINDOW',self.close);self.window.bind('<Escape>',lambda e:self.close())

    def resolve(self,choice):
        from tkinter import messagebox
        try:self.session.resolve_store_event(choice)
        except (ValueError,OSError) as exc:messagebox.showerror('対応を決められません',str(exc),parent=self.window);return
        self.close()

    def close_day(self):
        from tkinter import messagebox
        if not messagebox.askyesno('設備トラブルで休業する','本日は休業し、翌日へ進みますか？',parent=self.window):return
        try:self.session.day_off()
        except (ValueError,OSError) as exc:messagebox.showerror('休業できません',str(exc),parent=self.window);return
        self.close()

    def close(self):
        self.window.destroy();self.on_changed()
