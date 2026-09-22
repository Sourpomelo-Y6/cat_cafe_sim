"""増設前に費用・残金・席数を確認する。"""
from .core.cafe_expansion import rules, reason


class CafeExpansionWindow:
    def __init__(self, parent, session, on_changed):
        import tkinter as tk
        from tkinter import ttk
        self.session, self.on_changed = session, on_changed
        self.selected = rules()
        self.window = tk.Toplevel(parent)
        self.window.title('店の増設')
        self.window.geometry('540x320')
        self.window.minsize(500, 300)
        self.window.transient(parent)
        self.window.grab_set()
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        footer = ttk.Frame(frame)
        footer.pack(side='bottom', fill='x')
        self.purchase_button = ttk.Button(footer, text='3席に増設する', command=self.purchase)
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
        seats = len(core.seats) if hasattr(core, 'seats') else 1
        self.status.set(f'現在の席数：{seats}席 / 所持金：{core.funds:g}')
        if core.expansion:
            self.details.set(f"{core.expansion['day']}日目に3席へ増設済み。支払額：{core.expansion['cost']:g}")
        else:
            self.details.set(f"2席 → 3席 / 増設費用：{self.selected['cost']:g}\n増設後の所持金：{core.funds-self.selected['cost']:g}\n準備中に一度だけ購入できます。支払い後に資金が残る必要があります。\n派遣は店内の3席を超える担当可能な猫がいる場合に出発できます。")
        problem = '先に接客結果の保存を再試行してください。' if self.session.pending else reason(core, self.selected)
        self.notice.set(problem or '増設した席は今日から使用できます。来客数・猫の出勤予定はそのままです。')
        self.purchase_button.state(['disabled'] if problem else ['!disabled'])

    def purchase(self):
        from tkinter import messagebox
        core = self.session.core
        if not messagebox.askyesno('席の増設', f"2席から3席へ増設しますか？\n費用：{self.selected['cost']:g}\n増設後の所持金：{core.funds-self.selected['cost']:g}\n購入後の取り消し・返金はできません。", parent=self.window):
            return
        try:
            self.session.expand_seats(self.selected)
        except (ValueError, OSError) as exc:
            messagebox.showerror('増設できません', str(exc), parent=self.window)
        self.on_changed()
        self.refresh()
