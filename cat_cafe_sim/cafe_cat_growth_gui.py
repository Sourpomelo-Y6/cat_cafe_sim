"""経験条件を満たした猫の得意分野選択。"""


class CafeCatGrowthWindow:
    def __init__(self,parent,session,on_changed):
        import tkinter as tk
        from tkinter import ttk
        from .core.cafe_growth import pending,mastery_pending,mastery_choices,GROUP_LABELS,type_mastery_pending,type_mastery_choices,type_label
        self.session,self.on_changed=session,on_changed
        regular=pending(session.core);groups=mastery_pending(session.core)
        self.type_mastery_mode=not bool(regular or groups)
        self.mastery_mode=not bool(regular) and not self.type_mastery_mode
        self.cat_id=(regular or groups or type_mastery_pending(session.core))[0]
        name=session.profiles.get(self.cat_id,{}).get('name',self.cat_id)
        selected=session.core.growth['rules'];row=session.core.growth['cats'][self.cat_id]
        self.window=tk.Toplevel(parent);self.window.title('猫の得意分野')
        self.window.geometry('650x330');self.window.minsize(540,300);self.window.transient(parent);self.window.grab_set()
        frame=ttk.Frame(self.window,padding=12);frame.pack(fill='both',expand=True)
        if self.type_mastery_mode:
            choices=type_mastery_choices(session.core,self.cat_id)
            second=row['type_mastery'] is not None
            actions=row['second_type_mastery_actions'] if second else row['type_mastery_actions']
            practice=' / '.join(f"{type_label(key)} {actions[key]:g}回" for key in choices)
            stage='2つ目の得意な行動' if second else '得意な行動'
            period='初回習得後、未習得行動で' if second else '分類習得後、'
            text=(f"{name}の{stage}を1つ選んでください。\n"
                  f"{period}親しみが増えた接客の対象実績：{practice}\n\n"
                  f"選んだ行動では、関心の通常増加が追加で{selected['type_mastery_engagement_multiplier']:g}倍になります。")
            buttons=tuple((type_label(value)+'を得意にする',value) for value in choices)
        elif self.mastery_mode:
            second=row['mastery'] is not None
            counts=row['second_mastery_groups'] if second else row['mastery_groups']
            stage='2つ目の得意な交流' if second else '得意な交流'
            period='最初の分類習得後、各分類で' if second else ''
            text=(f"{name}が接客に習熟しました。{stage}を1つ選んでください。\n"
                  f"{period}親しみが増えた接客の実績：遊び {counts['play']:g} / 触れ合い {counts['contact']:g} / 静かな交流 {counts['quiet']:g}\n\n"
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
        choices_frame=ttk.Frame(footer);choices_frame.pack(side='left',fill='x',expand=True)
        choices_frame.columnconfigure((0,1),weight=1)
        self.choice_buttons={}
        for index,(label,choice) in enumerate(buttons):
            button=ttk.Button(choices_frame,text=label,command=lambda value=choice:self.resolve(value))
            button.grid(row=index//2,column=index%2,sticky='ew',padx=2,pady=2);self.choice_buttons[choice]=button
        ttk.Button(footer,text='閉じる',command=self.close).pack(side='right')
        self.window.protocol('WM_DELETE_WINDOW',self.close);self.window.bind('<Escape>',lambda e:self.close())

    def resolve(self,choice):
        from tkinter import messagebox
        try:
            if self.type_mastery_mode:self.session.resolve_growth_type_mastery(self.cat_id,choice)
            elif self.mastery_mode:self.session.resolve_growth_mastery(self.cat_id,choice)
            else:self.session.resolve_growth(self.cat_id,choice)
        except (ValueError,OSError) as exc:messagebox.showerror('得意分野を選べません',str(exc),parent=self.window);return
        self.close()

    def close(self):
        self.window.destroy();self.on_changed()
