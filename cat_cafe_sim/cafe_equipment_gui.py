"""休養スペースの費用と効果を確認して購入する。"""
from .core.cafe_equipment import rules, reason, upgrade_rules, upgrade_reason, recovery_bonus, soundproof_rules, soundproof_reason


class CafeEquipmentWindow:
    def __init__(self, parent, session, on_changed):
        import tkinter as tk
        from tkinter import ttk
        self.session, self.on_changed = session, on_changed
        self.selected = rules()
        self.upgrade_selected = upgrade_rules()
        self.soundproof_selected=soundproof_rules()
        self.window = tk.Toplevel(parent)
        self.window.title('休養設備')
        self.window.geometry('560x460')
        self.window.minsize(500, 440)
        self.window.transient(parent)
        self.window.grab_set()
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        footer = ttk.Frame(frame)
        footer.pack(side='bottom', fill='x')
        self.soundproof_button=ttk.Button(footer,text='休養スペースを防音改修',command=self.soundproof)
        self.soundproof_button.pack(anchor='w',pady=(0,6))
        controls=ttk.Frame(footer);controls.pack(fill='x')
        self.purchase_button = ttk.Button(controls, text='休養スペースを購入・設置', command=self.purchase)
        self.purchase_button.pack(side='left')
        self.upgrade_button = ttk.Button(controls, text='休養スペースを強化', command=self.upgrade)
        self.upgrade_button.pack(side='left', padx=6)
        self.close_button = ttk.Button(controls, text='閉じる', command=self.window.destroy)
        self.close_button.pack(side='right')
        self.status, self.details, self.notice = tk.StringVar(), tk.StringVar(), tk.StringVar()
        for var in (self.status, self.details, self.notice):
            ttk.Label(frame, textvariable=var, wraplength=460).pack(anchor='w', pady=8)
        self.window.bind('<Escape>', lambda event: self.window.destroy())
        self.refresh()

    def refresh(self):
        core = self.session.core
        owned = core.rest_space
        selected = owned['rules'] if owned else self.selected
        state='強化済み' if owned and 'upgrade' in owned else '設置済み' if owned else '未購入'
        self.status.set(f"休養スペース：{state} / 所持金：{core.funds:g}")
        payment = f"{owned['day']}日目に購入 / 支払額：{selected['cost']:g}" if owned else f"費用：{selected['cost']:g} / 購入後の所持金：{core.funds-selected['cost']:g}"
        if owned:
            if 'upgrade' in owned:
                row=owned['upgrade']
                payment+=f"\n{row['day']}日目に強化 / 支払額：{row['rules']['cost']:g}"
            else:
                payment+=f"\n強化費用：{self.upgrade_selected['cost']:g} / 強化後の所持金：{core.funds-self.upgrade_selected['cost']:g}\n設備の追加回復：＋{selected['recovery_bonus']:g} → ＋{self.upgrade_selected['recovery_bonus']:g}"
        if owned and 'soundproof' in owned:
            row=owned['soundproof'];payment+=f"\n{row['day']}日目に防音改修 / 支払額：{row['rules']['cost']:g} / ストレス回復＋{row['rules']['stress_recovery_bonus']:g}"
        else:
            payment+=f"\n防音改修：人気第2段階達成後 / 費用 {self.soundproof_selected['cost']:g} / ストレス回復＋{self.soundproof_selected['stress_recovery_bonus']:g}"
        amount=recovery_bonus(core) if owned else selected['recovery_bonus']
        self.details.set(f"{payment}\n在店して休養・療養した猫の疲労回復＋{amount:g}。特性の倍率を適用した後に加算します。\n購入した日の閉店・休業から有効。購入時には回復しません。\n出勤中・不在の猫には適用しません。防音改修は休養ストレス回復のみ加算し、療養日数は変えません。")
        problem = '先に接客結果の保存を再試行してください。' if self.session.pending else reason(core, self.selected)
        upgrade_problem='先に接客結果の保存を再試行してください。' if self.session.pending else upgrade_reason(core,self.upgrade_selected)
        soundproof_problem='先に接客結果の保存を再試行してください。' if self.session.pending else soundproof_reason(core,self.soundproof_selected)
        self.soundproof_button.state(['disabled'] if soundproof_problem else ['!disabled'])
        self.upgrade_button.state(['disabled'] if upgrade_problem else ['!disabled'])
        purchase_problem=problem
        if owned:problem=upgrade_problem
        if owned and 'soundproof' not in owned:problem=soundproof_problem
        self.notice.set(problem or ('準備中に一度だけ強化できます。強化後は「出勤・休養…」で回復予測を確認できます。' if owned else '準備中に一度だけ購入できます。支払い後に資金が残る必要があります。購入後は「出勤・休養…」で回復予測を確認できます。'))
        if owned and 'soundproof' not in owned and not soundproof_problem:
            self.notice.set('準備中に一度だけ防音改修できます。ストレス回復予測は出勤・休養画面で確認できます。')
        self.purchase_button.state(['disabled'] if purchase_problem else ['!disabled'])

    def purchase(self):
        from tkinter import messagebox
        core = self.session.core
        selected = self.selected
        if not messagebox.askyesno('休養スペースの購入', f"費用{selected['cost']:g}で購入・設置しますか？\n購入後の所持金：{core.funds-selected['cost']:g}\n在店休養時の疲労回復＋{selected['recovery_bonus']:g}（特性補正後に加算）\n一度だけ購入でき、取り消し・返金はできません。", parent=self.window):
            return
        try:
            self.session.purchase_rest_space(selected)
        except (ValueError, OSError) as exc:
            messagebox.showerror('設備を購入できません', str(exc), parent=self.window)
        self.on_changed()
        self.refresh()

    def upgrade(self):
        from tkinter import messagebox
        core=self.session.core; selected=self.upgrade_selected
        if not messagebox.askyesno('休養スペースの強化',
                f"費用{selected['cost']:g}で強化しますか？\n強化後の所持金：{core.funds-selected['cost']:g}\n設備の疲労回復：＋{recovery_bonus(core):g} → ＋{selected['recovery_bonus']:g}\n当日の休養・休業から有効です。",parent=self.window):return
        try:self.session.upgrade_rest_space(selected)
        except (ValueError,OSError) as exc:messagebox.showerror('設備を強化できません',str(exc),parent=self.window)
        self.on_changed(); self.refresh()


    def soundproof(self):
        from tkinter import messagebox
        core=self.session.core;selected=self.soundproof_selected
        if not messagebox.askyesno('休養スペースの防音改修',
                f"費用{selected['cost']:g}で防音改修しますか？\n改修後の所持金：{core.funds-selected['cost']:g}\n在店休養・療養時のストレス回復＋{selected['stress_recovery_bonus']:g}\n当日の閉店・休業から有効。疲労回復と療養日数は変わりません。",parent=self.window):return
        try:self.session.soundproof_rest_space(selected)
        except (ValueError,OSError) as exc:messagebox.showerror('防音改修できません',str(exc),parent=self.window)
        self.on_changed();self.refresh()
