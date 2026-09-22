"""休養スペースの費用と効果を確認して購入する。"""
from .core.cafe_equipment import rules, reason


class CafeEquipmentWindow:
    def __init__(self, parent, session, on_changed):
        import tkinter as tk
        from tkinter import ttk
        self.session, self.on_changed = session, on_changed
        self.selected = rules()
        self.window = tk.Toplevel(parent)
        self.window.title('休養設備')
        self.window.geometry('560x380')
        self.window.minsize(500, 340)
        self.window.transient(parent)
        self.window.grab_set()
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        footer = ttk.Frame(frame)
        footer.pack(side='bottom', fill='x')
        self.purchase_button = ttk.Button(footer, text='休養スペースを購入・設置', command=self.purchase)
        self.purchase_button.pack(side='left')
        self.close_button = ttk.Button(footer, text='閉じる', command=self.window.destroy)
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
        self.status.set(f"休養スペース：{'設置済み' if owned else '未購入'} / 所持金：{core.funds:g}")
        payment = f"{owned['day']}日目に購入 / 支払額：{selected['cost']:g}" if owned else f"費用：{selected['cost']:g} / 購入後の所持金：{core.funds-selected['cost']:g}"
        self.details.set(f"{payment}\n在店して休養・療養した猫の疲労回復＋{selected['recovery_bonus']:g}。特性の倍率を適用した後に加算します。\n購入した日の閉店・休業から有効。購入時には回復しません。\n出勤中・不在の猫には適用しません。ストレス回復や療養日数は変わりません。")
        problem = '先に接客結果の保存を再試行してください。' if self.session.pending else reason(core, self.selected)
        self.notice.set(problem or '準備中に一度だけ購入できます。支払い後に資金が残る必要があります。購入後は「出勤・休養…」で回復予測を確認できます。')
        self.purchase_button.state(['disabled'] if problem else ['!disabled'])

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
