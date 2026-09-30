"""店先に通う猫の情報・交流進捗と任意の加入。"""
class CafeVisitingCatWindow:
    def __init__(self,parent,session,on_changed):
        import tkinter as tk
        from tkinter import ttk
        from .cafe_history import CafeHistoryWindow
        self.session,self.on_changed=session,on_changed
        self.window=tk.Toplevel(parent); self.window.title('店先に通う猫')
        self.window.geometry('680x540'); self.window.minsize(560,420)
        self.window.transient(parent); self.window.grab_set()
        frame=ttk.Frame(self.window,padding=12); frame.pack(fill='both',expand=True)
        footer=ttk.Frame(frame); footer.pack(side='bottom',fill='x',pady=(8,0))
        actions=ttk.Frame(footer); actions.pack(fill='x',pady=(0,6))
        self.interact_button=ttk.Button(actions,text='交流する',command=lambda:self.respond('interact'))
        self.interact_button.pack(side='left')
        self.skip_button=ttk.Button(actions,text='今日は見送る',command=lambda:self.respond('skip'))
        self.skip_button.pack(side='left',padx=8)
        self.accept_button=ttk.Button(actions,text='迎える',command=lambda:self.respond('accept'))
        self.accept_button.pack(side='left')
        navigation=ttk.Frame(footer); navigation.pack(fill='x')
        from .cafe_housing_gui import add_introduction_housing
        add_introduction_housing(self,navigation)
        self.close_button=ttk.Button(navigation,text='閉じる',command=self.window.destroy)
        self.close_button.pack(side='right')
        self.title,self.notice=tk.StringVar(),tk.StringVar()
        ttk.Label(frame,textvariable=self.title,font=('',12,'bold'),wraplength=520).pack(anchor='w')
        ttk.Label(frame,text='店先で1日1回交流できます。交流や見送りに費用はかかりません。\n交流しない日も営業を進められ、これまでの進捗は残ります。',wraplength=520).pack(anchor='w',pady=6)
        ttk.Label(frame,textvariable=self.notice,wraplength=520).pack(anchor='w',pady=6)
        self.details=CafeHistoryWindow.table(frame,('項目','内容'))
        self.details.column('項目',width=190); self.details.column('内容',width=330)
        self.window.bind('<Escape>',lambda event:self.window.destroy()); self.refresh()

    def refresh(self):
        from .core.cafe_visiting_cat import progress,response_reason,daily_reason,admission_reason
        from .core.cafe_housing import status as housing_status
        from .core.cafe_preferences import feature_text
        from .core.cafe_traits import description
        from .core.human_cat_types import Personality
        from .cafe_housing_gui import refresh_introduction_housing
        core=self.session.core; data=core.visiting_cat; row=data['rules']['candidate']
        count=progress(core); required=data['rules']['interactions_required']
        self.title.set(f"{row['name']} · 店先での交流 {count}/{required}回")
        personality=Personality.from_dict(row['personality'])
        preset=next((name for name,value in self.session.presets.items() if value==personality),'カスタム')
        values=[('名前 / 個性',f"{row['name']} / {preset}"),('特徴',feature_text(row.get('features',[]))),
            ('飼育スペース',housing_status(core)),('迎える費用',f"{row['cost']:g}"),
            ('所持金 / 迎えた後',f"{core.funds:g} / {core.funds-row['cost']:g}"),
            ('加入時の状態','健康・体力全回復・休養予定'),('疲労 / ストレス / 好感度','0 / 0 / 0（加入時）')]
        values+=description(row.get('trait'))
        values += [(f'好み：{kind.name}',f'{value:g}') for kind,value in zip(self.session.interaction_config.types,personality.type_preferences)]
        values += [(f"{action['day']}日目の店先",'交流した' if action['choice']=='interact' else '今日は見送った') for action in data['actions']]
        self.details.delete(*self.details.get_children())
        for value in values:self.details.insert('','end',values=value)
        for button in (self.interact_button,self.skip_button,self.accept_button):button.state(['disabled'])
        refresh_introduction_housing(self,data['status'] in ('visiting','ready'))
        if data['status']=='untriggered':
            self.notice.set('人気第1段階を達成すると、翌日の準備から店先に通うようになります。'); return
        if data['status']=='accepted':
            self.notice.set(f"{data['accepted_day']}日目に迎えました。現在の状態は猫の詳細で確認できます。"); return
        problem='先に交流結果の保存を再試行してください。' if self.session.pending else response_reason(core)
        if problem:self.notice.set(problem); return
        daily=daily_reason(core)
        self.skip_button.state(['disabled'] if daily else ['!disabled'])
        if data['status']=='visiting':
            self.interact_button.state(['disabled'] if daily else ['!disabled'])
            self.notice.set(daily or f'あと{required-count}回交流すると迎えられます。今日は交流するか、見送ることができます。')
        else:
            problem=admission_reason(core)
            self.accept_button.state(['disabled'] if problem else ['!disabled'])
            self.notice.set(problem+' 進捗を保ったまま、後日の準備中に迎えられます。' if problem else '十分に慣れています。迎えるか、後日の準備中まで待つことができます。')

    def respond(self,choice):
        from tkinter import messagebox
        row=self.session.core.visiting_cat['rules']['candidate']
        prompt=(f"{row['name']}を迎えますか？\n費用：{row['cost']:g}\n加入時は休養予定です。" if choice=='accept' else
                f"今日は{row['name']}と交流しますか？\n費用はかかりません。" if choice=='interact' else
                f"今日は{row['name']}との交流を見送りますか？\nこれまでの進捗は残り、翌日以降にまた会えます。")
        if not messagebox.askyesno('店先に通う猫',prompt,parent=self.window):return
        try:self.session.resolve_visiting_cat(choice)
        except (ValueError,OSError) as exc:messagebox.showerror('操作できません',str(exc),parent=self.window)
        self.on_changed(); self.refresh()
