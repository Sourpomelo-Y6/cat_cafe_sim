"""飼育枠と購入後の維持費を確認する画面。"""
from .core.cafe_housing import reason, status, capacity


class CafeHousingWindow:
    def __init__(self, parent, session, on_changed):
        import tkinter as tk
        from tkinter import ttk
        self.session, self.on_changed = session, on_changed
        self.window = tk.Toplevel(parent)
        self.window.title('飼育スペースの拡張')
        self.window.geometry('540x340')
        self.window.minsize(500, 320)
        self.window.transient(parent)
        self.window.grab_set()
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        footer = ttk.Frame(frame)
        footer.pack(side='bottom', fill='x')
        self.purchase_button = ttk.Button(footer, text='飼育スペースを拡張する', command=self.purchase)
        self.purchase_button.pack(side='left')
        self.close_button = ttk.Button(footer, text='閉じる', command=self.window.destroy)
        self.close_button.pack(side='right')
        self.details, self.notice = tk.StringVar(), tk.StringVar()
        ttk.Label(frame, textvariable=self.details, wraplength=470).pack(anchor='w', pady=8)
        ttk.Label(frame, text='派遣中・家出中も在籍に含み、譲渡済みは除きます。接客席数は変わりません。',
                  wraplength=470).pack(anchor='w')
        ttk.Label(frame, textvariable=self.notice, wraplength=470).pack(anchor='w', pady=8)
        self.window.bind('<Escape>', lambda event: self.window.destroy())
        self.refresh()

    def refresh(self):
        core = self.session.core
        data = core.housing
        details = status(core)
        if data:
            selected = data['rules']
            if data['purchase']:
                details += f"\n拡張済み（{data['purchase']['day']}日目・費用 {data['purchase']['cost']:g}）\n日次維持費：＋{selected['daily_cost']:g}"
            else:
                from .core.cafe_operating_cost import estimate
                details += (f"\n上限：{capacity(core)} → {capacity(core)+selected['capacity_bonus']}匹"
                            f"\n購入費：{selected['cost']:g} / 購入後の所持金：{core.funds-selected['cost']:g}"
                            f"\n日次運営費：{estimate(core):g} → {estimate(core)+selected['daily_cost']:g}（休業日も精算）")
        self.details.set(details)
        problem = '先に接客結果の保存を再試行してください。' if self.session.pending else reason(core)
        self.notice.set(problem or '購入当日から有効です。拡張は1回だけ利用できます。')
        self.purchase_button.state(['disabled'] if problem else ['!disabled'])

    def purchase(self):
        from tkinter import messagebox
        core = self.session.core
        problem = reason(core)
        if problem:
            self.refresh()
            return
        selected = core.housing['rules']
        if not messagebox.askyesno('飼育スペースの拡張',
                f"費用{selected['cost']:g}で拡張しますか？\n購入後の所持金：{core.funds-selected['cost']:g}\n日次維持費：＋{selected['daily_cost']:g}",
                parent=self.window):
            return
        try:
            self.session.purchase_housing()
        except (ValueError, OSError) as exc:
            messagebox.showerror('拡張できません', str(exc), parent=self.window)
        self.on_changed()
        self.refresh()
