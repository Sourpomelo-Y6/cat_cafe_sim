"""経験条件を満たした猫の得意分野選択。"""


class CafeCatGrowthWindow:
    def __init__(self,parent,session,on_changed):
        import tkinter as tk
        from tkinter import ttk
        from .core.cafe_growth import pending,mastery_pending,mastery_choices,GROUP_LABELS
        self.session,self.on_changed=session,on_changed
        regular=pending(session.core);self.mastery_mode=not bool(regular)
        self.cat_id=(regular or mastery_pending(session.core))[0]
        name=session.profiles.get(self.cat_id,{}).get('name',self.cat_id)
        selected=session.core.growth['rules'];row=session.core.growth['cats'][self.cat_id]
        self.window=tk.Toplevel(parent);self.window.title('猫の得意分野')
        self.window.geometry('650x330');self.window.minsize(540,300);self.window.transient(parent);self.window.grab_set()
        frame=ttk.Frame(self.window,padding=12);frame.pack(fill='both',expand=True)
        if self.mastery_mode:
            counts=row['mastery_groups']
            text=(f"{name}が接客に習熟しました。得意な交流を1つ選んでください。\n"
                  f"親しみが増えた接客の実績：遊び {counts['play']:g} / 触れ合い {counts['contact']:g} / 静かな交流 {counts['quiet']:g}\n\n"
                  f"選んだ分類では、関心の通常増加が{selected['mastery_engagement_multiplier']:g}倍になります。")
            buttons=tuple((GROUP_LABELS[value]+'を得意にする',value) for value in mastery_choices(session.core,self.cat_id))
        else:
            text=(f"{name}が成長できるようになりました。得意分野を1つ選んでください。\n"
                  f"経験：接客 {row['service']:g} / 休養 {row['rest']:g} / 派遣 {row['dispatch']:g}\n\n"
                  f"接客：接客終了時、消費した体力の{selected['service_stamina_refund']*100:g}%を回復\n"
                  f"休養：在店休養時の疲労回復＋{selected['rest_recovery_bonus']:g}\n"
                  f"派遣：派遣報酬を{selected['dispatch_reward_multiplier']:g}倍")
            buttons=(('接客を得意にする','service'),('休養を得意にする','rest'),('派遣を得意にする','dispatch'))
        ttk.Label(frame,text=text,wraplength=600,justify='left').pack(anchor='w',pady=8)
        footer=ttk.Frame(frame);footer.pack(side='bottom',fill='x')
        self.choice_buttons={}
        for index,(label,choice) in enumerate(buttons):
            button=ttk.Button(footer,text=label,command=lambda value=choice:self.resolve(value))
            button.pack(side='left',padx=(0 if index==0 else 4,0));self.choice_buttons[choice]=button
        ttk.Button(footer,text='閉じる',command=self.close).pack(side='right')
        self.window.protocol('WM_DELETE_WINDOW',self.close);self.window.bind('<Escape>',lambda e:self.close())

    def resolve(self,choice):
        from tkinter import messagebox
        try:
            if self.mastery_mode:self.session.resolve_growth_mastery(self.cat_id,choice)
            else:self.session.resolve_growth(self.cat_id,choice)
        except (ValueError,OSError) as exc:messagebox.showerror('得意分野を選べません',str(exc),parent=self.window);return
        self.close()

    def close(self):
        self.window.destroy();self.on_changed()
