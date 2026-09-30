"""常連から紹介された猫の条件と回答履歴。"""
class CafeRegularIntroductionWindow:
    def __init__(self,parent,session,on_changed):
        import tkinter as tk
        from tkinter import ttk
        from .cafe_history import CafeHistoryWindow
        self.session,self.on_changed=session,on_changed
        self.window=tk.Toplevel(parent)
        self.window.title('常連からの猫紹介')
        self.window.geometry('680x540'); self.window.minsize(560,420)
        self.window.transient(parent); self.window.grab_set()
        frame=ttk.Frame(self.window,padding=12); frame.pack(fill='both',expand=True)
        footer=ttk.Frame(frame); footer.pack(side='bottom',fill='x',pady=(10,0))
        self.accept_button=ttk.Button(footer,text='迎える',command=lambda:self.respond('accept'))
        self.accept_button.pack(side='left')
        self.decline_button=ttk.Button(footer,text='見送る',command=lambda:self.respond('decline'))
        self.decline_button.pack(side='left',padx=8)
        self.close_button=ttk.Button(footer,text='閉じる',command=self.window.destroy)
        self.close_button.pack(side='right')
        self.title,self.notice=tk.StringVar(),tk.StringVar()
        ttk.Label(frame,textvariable=self.title,font=('',12,'bold'),wraplength=520).pack(anchor='w')
        ttk.Label(frame,text='常連のお客さんが、新しい居場所を探している猫を紹介してくれます。\n見送りによる費用・人気・常連度の変化はありません。紹介は一度だけです。',wraplength=520).pack(anchor='w',pady=6)
        ttk.Label(frame,textvariable=self.notice,wraplength=520).pack(anchor='w',pady=6)
        self.details=CafeHistoryWindow.table(frame,('項目','内容'))
        self.details.column('項目',width=190); self.details.column('内容',width=330)
        self.window.bind('<Escape>',lambda event:self.window.destroy())
        self.refresh()

    def refresh(self):
        from .core.cafe_regular_introduction import response_reason,admission_reason
        from .core.cafe_housing import status as housing_status
        from .core.cafe_preferences import feature_text
        from .core.cafe_traits import description
        from .core.human_cat_types import Personality
        from .cafe_customers import customer_name
        core=self.session.core; data=core.regular_introduction; row=data['rules']['candidate']
        personality=Personality.from_dict(row['personality'])
        preset=next((name for name,value in self.session.presets.items() if value==personality),'カスタム')
        self.title.set(f"{customer_name(data['customer_id'])}から {row['name']}の紹介" if data['customer_id'] else '常連からの猫紹介 · まだ届いていません')
        values=[('名前 / 個性',f"{row['name']} / {preset}"),('特徴',feature_text(row.get('features',[]))),
                ('飼育スペース',housing_status(core)),('初期費用',f"{row['cost']:g}"),
                ('所持金 / 受け入れ後',f"{core.funds:g} / {core.funds-row['cost']:g}"),
                ('加入時の状態','健康・体力全回復・休養予定'),('疲労 / ストレス / 好感度','0 / 0 / 0（未交流）')]
        values+=description(row.get('trait'))
        values += [(f'好み：{kind.name}',f'{value:g}') for kind,value in zip(self.session.interaction_config.types,personality.type_preferences)]
        self.details.delete(*self.details.get_children())
        for value in values:self.details.insert('','end',values=value)
        self.accept_button.state(['disabled']);self.decline_button.state(['disabled'])
        if data['status']=='untriggered':
            self.notice.set(f"常連度{core.customer_loyalty['rules']['threshold']:g}に達したお客さんから、翌日の準備中に一度だけ紹介が届きます。")
            return
        if data['status'] in ('accepted','declined'):
            self.notice.set(f"{data['resolved_day']}日目に"+('迎えました。現在の状態は猫の詳細で確認できます。' if data['status']=='accepted' else '見送りました。この紹介は再発生しません。'))
            return
        problem='先に交流結果の保存を再試行してください。' if self.session.pending else response_reason(core)
        if problem:self.notice.set(problem);return
        self.decline_button.state(['!disabled'])
        problem=admission_reason(core)
        self.accept_button.state(['disabled'] if problem else ['!disabled'])
        self.notice.set(problem+' 見送ることができます。' if problem else '迎えるか見送るかを選ぶと営業準備を続けられます。')

    def respond(self,choice):
        from tkinter import messagebox
        row=self.session.core.regular_introduction['rules']['candidate']
        prompt=(f"{row['name']}を迎えますか？\n初期費用：{row['cost']:g}\n加入時は休養予定です。" if choice=='accept'
                else f"{row['name']}の受け入れを見送りますか？\n費用・人気・常連度への影響はありません。この紹介は再発生しません。")
        if not messagebox.askyesno('常連からの猫紹介',prompt,parent=self.window):return
        try:self.session.resolve_regular_introduction(choice)
        except (ValueError,OSError) as exc:messagebox.showerror('回答できません',str(exc),parent=self.window)
        self.on_changed();self.refresh()
