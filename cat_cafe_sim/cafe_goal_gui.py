"""人気目標の進捗、導入、結果確認と継続営業。"""
from .core.cafe_goal import progression_rules as rules, pending, current_rules, current_start, next_rules, advance_reason
from .core.cafe_management import is_over


def progress(core):
    data=core.goal
    if not data:
        return '人気目標：未導入（準備中に「目標・結果…」から開始できます）'
    selected = current_rules(data)
    deadline=current_start(data)+selected['days']-1
    remaining=min(selected['days'], max(0,deadline-core.day+int(not core.closed)))
    label={'active':'挑戦中','cleared':'クリア','expired':'期限内未達'}[data['status']]
    if data['continued']:
        label += '・自由営業'
    stage = f"第{len(data.get('history', []))+1}/3段階 · " if 'stages' in data['rules'] else ''
    return stage+f"人気目標 {core.management['popularity']:g} / {selected['target']:g} · {deadline}日目まで（残り{remaining}日） · {label}"


class CafeGoalWindow:
    def __init__(self,parent,session,on_changed):
        import tkinter as tk
        from tkinter import ttk
        self.session,self.on_changed=session,on_changed
        self.window=tk.Toplevel(parent)
        self.window.title('人気目標・結果')
        self.window.geometry('680x500');self.window.minsize(500,400)
        self.window.transient(parent);self.window.grab_set()
        frame=ttk.Frame(self.window,padding=16);frame.pack(fill='both',expand=True)
        footer=ttk.Frame(frame);footer.pack(side='bottom',fill='x')
        self.enable_button=ttk.Button(footer,text='目標を開始',command=self.enable);self.enable_button.pack(side='left')
        self.continue_button=ttk.Button(footer,text='自由に営業を続ける',command=self.resume);self.continue_button.pack(side='left',padx=4)
        self.next_button=ttk.Button(footer,text='次の目標へ挑戦',command=self.advance)
        self.next_button.pack(side='left',padx=4)
        ttk.Button(footer,text='閉じる',command=self.window.destroy).pack(side='right')
        self.status=tk.StringVar();self.notice=tk.StringVar();self.details=tk.StringVar()
        for var in (self.status,self.details,self.notice):
            ttk.Label(frame,textvariable=var,wraplength=460).pack(anchor='w',pady=8)
        from .cafe_history import CafeHistoryWindow
        self.history = CafeHistoryWindow.table(frame, ('段階', '人気目標', '開始・期限', '結果'))
        self.window.bind('<Escape>',lambda event:self.window.destroy())
        self.refresh()

    def refresh(self):
        from .core.cafe_activities import waiting_events
        from .core.cafe_player import active
        core=self.session.core;data=core.goal
        selected=current_rules(data) if data else rules()
        base=data['rules'] if data else selected
        self.status.set(progress(core))
        self.details.set(f"開始日を含む{selected['days']}日以内に人気{selected['target']:g}が目標です。\n好感度につながる反応合計がプラスの接客1件につき＋{base['gain_per_success']:g}。閉店時に加算（上限{base['cap']:g}）し、家出の減少を反映後に判定します。休業も日数に含みます。")
        self.history.delete(*self.history.get_children())
        stages = [base] + base.get('stages', [])
        attempts = (data.get('history', []) + [dict(started_day=current_start(data), status=data['status'], resolved_day=data['resolved_day'])]) if data else []
        for index, row in enumerate(stages):
            attempt = attempts[index] if index < len(attempts) else None
            result = {'active':'挑戦中','cleared':'達成','expired':'期限内未達'}[attempt['status']] if attempt else '未開始'
            if attempt and attempt['resolved_day'] is not None:
                result += f"（{attempt['resolved_day']}日目）"
            period = f"{attempt['started_day']}〜{attempt['started_day']+row['days']-1}日目" if attempt else f"開始から{row['days']}日間"
            self.history.insert('', 'end', values=(index+1, f"{row['target']:g}", period, result))
        if data:
            self.enable_button.pack_forget()
        else:
            self.enable_button.pack(side='left')
        can_next = data and data['status']=='cleared' and next_rules(data)
        if can_next:
            self.next_button.pack(side='left',padx=4)
        else:
            self.next_button.pack_forget()
        self.next_button.state(['disabled'] if self.session.pending or advance_reason(core) else ['!disabled'])
        blocked=bool(self.session.pending) or bool(waiting_events(core)) or is_over(core)
        self.enable_button.state(['!disabled'] if not data and core.management and core.can_set_shifts and not blocked and not active(core) else ['disabled'])
        self.continue_button.state(['!disabled'] if pending(core) and not blocked else ['disabled'])
        self.notice.set('ゲームオーバーです。営業画面の「結果・再開始…」から新しく始められます。' if is_over(core) else
            '先に接客結果の保存・帰還・譲渡イベントの確認を完了してください。' if blocked else
            '先に経営ルールを開始してください。' if not core.management else
            f"{data['resolved_day']}日目に"+('目標達成！' if data['status']=='cleared' else '期限内未達でした。')+(' 次の目標へ挑戦するか、自由営業を選べます。' if can_next else ' 結果を記録し、期限なしで営業を続けられます。') if data and data['status']!='active' else
            '結果は閉店時に判定します。ゲームオーバーを優先します。')

    def perform(self,action):
        from tkinter import messagebox
        try:action()
        except (ValueError,OSError) as exc:messagebox.showerror('目標を操作できません',str(exc),parent=self.window)
        self.on_changed();self.refresh()

    def enable(self):
        from tkinter import messagebox
        selected=rules()
        if messagebox.askyesno('人気目標を開始',f"今日を含む{selected['days']}日以内に人気{selected['target']:g}を目指します。開始後の取消・やり直しはできません。開始しますか？",parent=self.window):
            self.perform(lambda:self.session.enable_goal(selected))

    def advance(self):
        from tkinter import messagebox
        core = self.session.core
        selected = next_rules(core.goal)
        if selected is None:
            return
        start = core.day+int(core.closed)
        if messagebox.askyesno('次の人気目標', f"{start}日目から{selected['days']}日以内に人気{selected['target']:g}を目指します。挑戦を開始しますか？", parent=self.window):
            self.perform(self.session.advance_goal)

    def resume(self):
        self.perform(self.session.continue_goal)
