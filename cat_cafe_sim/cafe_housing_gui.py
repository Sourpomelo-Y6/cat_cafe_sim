"""飼育枠と購入後の維持費を確認する画面。"""
from .core.cafe_housing import reason, status, capacity, upgrade_rules, upgrade_reason, daily_cost


class CafeHousingWindow:
    def __init__(self, parent, session, on_changed, on_closed=None):
        import tkinter as tk
        from tkinter import ttk
        self.session, self.on_changed = session, on_changed
        self.parent, self.on_closed = parent, on_closed
        self.upgrade_selected=upgrade_rules()
        self.window = tk.Toplevel(parent)
        self.window.title('飼育スペースの拡張')
        self.window.geometry('580x420')
        self.window.minsize(500, 320)
        self.window.transient(parent)
        self.window.grab_set()
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        footer = ttk.Frame(frame)
        footer.pack(side='bottom', fill='x')
        self.purchase_button = ttk.Button(footer, text='飼育スペースを拡張する', command=self.purchase)
        self.purchase_button.pack(side='left')
        self.upgrade_button=ttk.Button(footer,text='2段階目へ拡張',command=self.upgrade)
        self.upgrade_button.pack(side='left',padx=6)
        self.close_button = ttk.Button(footer, text='閉じる', command=self.close)
        self.close_button.pack(side='right')
        self.details, self.notice = tk.StringVar(), tk.StringVar()
        ttk.Label(frame, textvariable=self.details, wraplength=470).pack(anchor='w', pady=8)
        ttk.Label(frame, text='派遣中・家出中も在籍に含み、譲渡済みは除きます。接客席数は変わりません。',
                  wraplength=470).pack(anchor='w')
        ttk.Label(frame, textvariable=self.notice, wraplength=470).pack(anchor='w', pady=8)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.window.bind('<Escape>', lambda event: self.close())
        self.refresh()

    def close(self):
        self.window.destroy()
        if self.parent.winfo_exists() and self.parent.master is not None:
            self.parent.grab_set()
        if self.on_closed:
            self.on_closed()

    def refresh(self):
        core = self.session.core
        data = core.housing
        details = status(core)
        if data:
            selected = data['rules']
            if data['purchase']:
                details += f"\n拡張済み（{data['purchase']['day']}日目・費用 {data['purchase']['cost']:g}）\n日次維持費：＋{daily_cost(core):g}"
            else:
                from .core.cafe_operating_cost import estimate
                details += (f"\n上限：{capacity(core)} → {capacity(core)+selected['capacity_bonus']}匹"
                            f"\n購入費：{selected['cost']:g} / 購入後の所持金：{core.funds-selected['cost']:g}"
                            f"\n日次運営費：{estimate(core):g} → {estimate(core)+selected['daily_cost']:g}（休業日も精算）")
            upgraded=data.get('upgrade')
            if upgraded:
                details+=f"\n追加拡張済み（{upgraded['day']}日目・費用 {upgraded['rules']['cost']:g}）"
            elif data['purchase']:
                from .core.cafe_operating_cost import estimate
                extra=self.upgrade_selected
                details+=(f"\n追加拡張：{capacity(core)} → {capacity(core)+extra['capacity_bonus']}匹 / 費用 {extra['cost']:g}"
                          f"\n追加拡張後の所持金：{core.funds-extra['cost']:g}"
                          f"\n日次運営費：{estimate(core):g} → {estimate(core)-daily_cost(core)+extra['daily_cost']:g}（飼育維持費合計{extra['daily_cost']:g}）")
        self.details.set(details)
        problem = '先に接客結果の保存を再試行してください。' if self.session.pending else reason(core)
        upgrade_problem='先に接客結果の保存を再試行してください。' if self.session.pending else upgrade_reason(core,self.upgrade_selected)
        self.notice.set(('購入当日から有効です。各段階を1回ずつ利用できます。' if not problem or not upgrade_problem else upgrade_problem if data and data['purchase'] else problem))
        self.upgrade_button.state(['disabled'] if upgrade_problem else ['!disabled'])
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

    def upgrade(self):
        from tkinter import messagebox
        core=self.session.core
        if self.session.pending or upgrade_reason(core,self.upgrade_selected):
            self.refresh();return
        selected=self.upgrade_selected
        if not messagebox.askyesno('飼育スペースの追加拡張',
                f"上限{capacity(core)}から{capacity(core)+selected['capacity_bonus']}匹へ拡張しますか？\n費用：{selected['cost']:g}\n追加拡張後の所持金：{core.funds-selected['cost']:g}\n飼育維持費合計：{selected['daily_cost']:g}",parent=self.window):return
        try:self.session.upgrade_housing(selected)
        except (ValueError,OSError) as exc:messagebox.showerror('拡張できません',str(exc),parent=self.window)
        self.on_changed();self.refresh()


def add_introduction_housing(owner, footer):
    """紹介の回答画面に共通の拡張導線を付ける。"""
    from tkinter import ttk

    def changed():
        owner.on_changed()
        owner.refresh()

    def open_housing():
        child = getattr(owner, 'housing_window', None)
        if child and child.window.winfo_exists():
            child.window.lift()
            child.window.grab_set()
            return
        owner.housing_window = CafeHousingWindow(owner.window, owner.session, changed, owner.refresh)

    owner.housing_button = ttk.Button(footer, text='飼育スペースを拡張…', command=open_housing)
    owner.housing_button.pack(side='left')


def refresh_introduction_housing(owner, waiting):
    problem = owner.session.pending or not waiting or (reason(owner.session.core) and upgrade_reason(owner.session.core,upgrade_rules()))
    owner.housing_button.state(['disabled'] if problem else ['!disabled'])
