"""達成時点の成果、継続営業、別の新規ゲームへの入口。"""
from .core.cafe_clear_results import goals, completed, metric

LABELS={'popularity':'人気目標', 'patron':'有力者の満足度', 'bond':'猫との好感度'}


class CafeClearResultsWindow:
    def __init__(self,parent,session,on_changed,on_new_game,mode=None):
        import tkinter as tk
        from tkinter import ttk
        from .cafe_history import CafeHistoryWindow
        self.session,self.on_changed,self.on_new_game=session,on_changed,on_new_game
        self.window=tk.Toplevel(parent)
        self.window.title('クリア結果・記録')
        self.window.geometry('640x480');self.window.minsize(540,400)
        self.window.transient(parent);self.window.grab_set()
        frame=ttk.Frame(self.window,padding=12);frame.pack(fill='both',expand=True)
        footer=ttk.Frame(frame);footer.pack(side='bottom',fill='x',pady=(8,0))
        self.continue_button=ttk.Button(footer,text='この店で営業を続ける',command=self.resume)
        self.continue_button.pack(side='left')
        self.new_button=ttk.Button(footer,text='別の目標で始める…',command=self.restart)
        self.new_button.pack(side='left',padx=6)
        self.close_button=ttk.Button(footer,text='閉じる',command=self.window.destroy)
        self.close_button.pack(side='right')
        self.modes=[m for m in LABELS if completed(session.core,m)]
        self.selector=ttk.Combobox(frame,state='readonly',values=[LABELS[m] for m in self.modes])
        self.selector.pack(fill='x')
        if self.modes:self.selector.current(self.modes.index(mode) if mode in self.modes else 0)
        self.status=tk.StringVar();self.notice=tk.StringVar()
        ttk.Label(frame,textvariable=self.status,font=('',12,'bold'),wraplength=500).pack(anchor='w',pady=8)
        ttk.Label(frame,textvariable=self.notice,wraplength=500).pack(anchor='w',pady=4)
        self.table=CafeHistoryWindow.table(frame,('項目','達成時の記録'))
        self.table.column('項目',width=180);self.table.column('達成時の記録',width=320)
        self.selector.bind('<<ComboboxSelected>>',lambda event:self.refresh())
        self.window.bind('<Escape>',lambda event:self.window.destroy())
        self.refresh()

    def refresh(self):
        from .core.cafe_management import is_over
        from .core.cafe_activities import waiting_events
        core=self.session.core
        self.table.delete(*self.table.get_children())
        self.continue_button.state(['disabled'])
        if not self.modes:
            self.status.set('クリア記録はまだありません')
            self.notice.set('人気の最終段階・有力者・猫との好感度の達成結果を、ここで見返せます。')
            return
        mode=self.modes[self.selector.current()]
        goal=goals(core)[mode]
        saved=(core.clear_results or {}).get(mode)
        target,_=metric(core,mode)
        self.status.set(LABELS[mode]+' クリア！')
        value=saved['value'] if saved else len(goal['achieved_cats']) if mode=='bond' else goal['rules']['target'] if mode=='patron' else None
        achieved=f'{value:g} / {target:g}' if value is not None else f'目標 {target:g} 達成（達成時の実数は記録なし）'
        if mode=='bond':achieved+='匹'
        rows=[('達成日',f"{goal['resolved_day']}日目"),('目標の達成値',achieved)]
        for field,label in (('funds','所持金'),('popularity','店の人気'),('cats','在籍猫数'),('revenue','累計接客売上')):
            rows.append((label,f'{saved[field]:g}'+('匹' if field=='cats' else '') if saved else '記録なし'))
        for row in rows:self.table.insert('','end',values=row)
        blocked=bool(self.session.pending) or bool(waiting_events(core)) or is_over(core)
        self.continue_button.state(['disabled'] if blocked or goal['continued'] else ['!disabled'])
        notice='達成した瞬間の記録です。継続営業後も数値は変わりません。' if saved else '旧セーブには達成時の詳しい成果がありません。現在値では補いません。'
        if is_over(core):notice+=' 現在はゲームオーバーです。'
        elif self.session.pending:notice+=' 先に交流結果の保存を再試行してください。'
        elif waiting_events(core):notice+=' 先に帰還・譲渡などを確認してください。'
        elif goal['continued']:notice+=' この目標の結果は確認済みです。'
        self.notice.set(notice)

    def resume(self):
        from tkinter import messagebox
        if not self.modes:return
        mode=self.modes[self.selector.current()]
        action={'popularity':self.session.continue_goal,'patron':self.session.continue_patron,'bond':self.session.continue_bond_goal}[mode]
        try:action()
        except (ValueError,OSError) as exc:
            messagebox.showerror('営業を続けられません',str(exc),parent=self.window)
        self.on_changed();self.refresh()

    def restart(self):
        self.window.destroy()
        self.on_new_game()
