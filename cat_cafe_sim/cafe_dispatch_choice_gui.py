"""派遣中の出来事への回答と、回答済み記録の閲覧。"""
from .core.cafe_dispatch_encounters import pending, selected
from .core.cafe_activities import reward
from .core.cafe_management import is_over


class CafeDispatchChoiceWindow:
    def __init__(self,parent,session,event_id,on_changed):
        import tkinter as tk
        from tkinter import ttk
        self.session,self.event_id,self.on_changed=session,event_id,on_changed
        self.window=tk.Toplevel(parent)
        self.window.title('派遣中の出来事')
        self.window.geometry('640x380')
        self.window.minsize(560,360)
        self.window.transient(parent)
        self.window.grab_set()
        self.parent=parent
        frame=ttk.Frame(self.window,padding=12)
        frame.pack(fill='both',expand=True)
        ttk.Button(frame,text='閉じる',command=self.close).pack(side='bottom',anchor='e')
        event=session.core.activities['events'][event_id]
        data=event['encounter']
        name=session.profiles.get(event['cat_id'],{}).get('name',event['cat_id'])
        ttk.Label(frame,text=f"{name} / {event['destination']['name']}").pack(anchor='w',pady=5)
        ttk.Label(frame,text=data['rules']['title'],font=('',12,'bold'),wraplength=530).pack(anchor='w',pady=5)
        self.notice=tk.StringVar()
        ttk.Label(frame,textvariable=self.notice,wraplength=530).pack(anchor='w',pady=5)
        self.buttons={}
        for row in data['rules']['choices']:
            label=f"{row['label']}\n帰還報酬 {row['reward']:+g} / 疲労 {row['fatigue']:+g} / ストレス {row['stress']:+g}"
            button=ttk.Button(frame,text=label,command=lambda key=row['id']:self.answer(key))
            button.pack(fill='x',pady=5)
            self.buttons[row['id']]=button
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        self.window.bind('<Escape>',lambda event:self.close())
        self.refresh()

    def refresh(self):
        core=self.session.core
        event=core.activities['events'][self.event_id]
        data=event['encounter']
        row=selected(event)
        if row:
            change=data['changes']
            stress='未導入・適用なし' if change['stress_before'] is None else f"{change['stress_before']:g} → {change['stress_after']:g}"
            self.notice.set(f"{data['resolved_day']}日目に回答：{row['label']}\n疲労 {change['fatigue_before']:g} → {change['fatigue_after']:g} / ストレス {stress}\n帰還報酬：{reward(core,event):g}。回答内容は変更できません。")
        else:
            self.notice.set('ゲームオーバーのため回答できません。' if is_over(core) else
                            '先に接客結果の保存を再試行してください。' if self.session.pending else
                            '回答まで進行を停止します。疲労・ストレスは回答時に変更し、報酬は帰還時に精算します。派遣期間は変わりません。'+(' ストレスは未導入のため適用しません。' if not core.management else ''))
        for button in self.buttons.values():
            button.state(['!disabled'] if pending(event) and not self.session.pending and not is_over(core) else ['disabled'])

    def answer(self,choice):
        from tkinter import messagebox
        try:
            self.session.resolve_dispatch_choice(self.event_id,choice)
        except (ValueError,OSError) as exc:
            messagebox.showerror('派遣イベントに回答できません',str(exc),parent=self.window)
        self.on_changed()
        self.refresh()

    def close(self):
        self.window.destroy()
        if self.parent.winfo_exists() and self.parent.winfo_class()=='Toplevel':
            self.parent.grab_set()
