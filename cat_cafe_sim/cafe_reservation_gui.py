"""特別予約の依頼と公開条件。"""
class CafeReservationWindow:
    def __init__(self,parent,session,on_changed):
        import tkinter as tk
        from tkinter import ttk
        self.session,self.on_changed=session,on_changed
        self.window=tk.Toplevel(parent);self.window.title('翌日の特別予約');self.window.geometry('620x300');self.window.minsize(500,280);self.window.transient(parent);self.window.grab_set()
        frame=ttk.Frame(self.window,padding=12);frame.pack(fill='both',expand=True)
        footer=ttk.Frame(frame);footer.pack(side='bottom',fill='x')
        self.accept=ttk.Button(footer,text='予約を受け入れる',command=lambda:self.resolve('accept'));self.accept.pack(side='left')
        self.decline=ttk.Button(footer,text='見送る',command=lambda:self.resolve('decline'));self.decline.pack(side='left',padx=4)
        ttk.Button(footer,text='閉じる',command=self.close).pack(side='right')
        from .core.cafe_reservation import NAME
        rules=session.core.reservation['rules'];request=session.core.reservation['request']
        self.details=tk.StringVar(value=f"{NAME}\n来店日：{request['visit_day']}日目 / 長毛の猫を担当 / 心を開く {rules['open_up_count']}回以上\n条件達成：追加料金＋{rules['bonus']:g}、人気＋{rules['popularity_bonus']:g}\n見送ってもペナルティはありません。受け入れると来店日は休業できません。")
        ttk.Label(frame,textvariable=self.details,wraplength=570).pack(anchor='w',pady=8)
        self.window.protocol('WM_DELETE_WINDOW',self.close);self.window.bind('<Escape>',lambda e:self.close())
    def resolve(self,choice):
        from tkinter import messagebox
        try:self.session.resolve_reservation(choice)
        except (ValueError,OSError) as exc:messagebox.showerror('予約へ回答できません',str(exc),parent=self.window);return
        self.close()
    def close(self):
        self.window.destroy();self.on_changed()
