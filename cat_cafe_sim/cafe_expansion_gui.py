"""増設前に費用・残金・席数を確認する。"""
from .core.cafe_expansion import rules, reason, next_step, purchases, first_popularity_cleared,second_popularity_cleared


class CafeExpansionWindow:
    def __init__(self, parent, session, on_changed, *, show_navigation=True):
        import tkinter as tk
        from tkinter import ttk
        self.session, self.on_changed = session, on_changed
        self.selected = rules()
        self.window = tk.Toplevel(parent)
        self.window.title('席の増設')
        self.window.geometry('540x320')
        self.window.minsize(500, 300)
        self.window.transient(parent)
        self.window.grab_set()
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        footer = ttk.Frame(frame)
        footer.pack(side='bottom', fill='x')
        self.purchase_button = ttk.Button(footer, text='席を増設する', command=self.purchase)
        self.purchase_button.pack(side='left')
        self.equipment_button = ttk.Button(footer, text='休養設備…', command=self.show_equipment)
        if show_navigation:
            self.equipment_button.pack(side='left', padx=6)
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
        step = next_step(core, self.selected) if hasattr(core, 'seats') else None
        history = ' / '.join(f"{row['day']}日目：{row['seats']}席（{row['cost']:g}）" for row in purchases(core))
        if step:
            unlocked=(step['to_seats']==3 or step['to_seats']==4 and first_popularity_cleared(core)
                      or step['to_seats']==5 and second_popularity_cleared(core))
            unlock='' if unlocked else f"\n{step['to_seats']}席は人気目標の第{step['to_seats']-3}段階達成後に解放されます。"
            visitors = '\n購入翌日から通常のお客さんが営業日ごとに1人増えます。' if step['to_seats'] in (4,5) else '\n来客数はまだ変わりません。'
            from .core.cafe_operating_cost import estimate
            running=('' if core.operating_cost is None else
                     f"\n日次運営費：{estimate(core):g} → {estimate(core,step['to_seats']):g}（毎日）")
            self.details.set((history+'\n' if history else '') +
                f"{step['from_seats']}席 → {step['to_seats']}席 / 増設費用：{step['cost']:g}\n増設後の所持金：{core.funds-step['cost']:g}"
                f"\n増設した席は購入当日から使えます。{visitors}{running}{unlock}\n派遣には店内の席数を超える担当可能な猫が必要です。")
            self.purchase_button.configure(text=f"{step['to_seats']}席に増設する")
        else:
            self.details.set((history+'\n' if history else '')+'現在予定されている席の増設はすべて購入済みです。')
            self.purchase_button.configure(text='増設済み')
        problem = '先に接客結果の保存を再試行してください。' if self.session.pending else reason(core, self.selected)
        self.notice.set(problem or ('増設した席は今日から使用できます。追加のお客さんは翌日から来店します。' if step and step['to_seats'] in (4,5) else '増設した席は今日から使用できます。'))
        self.purchase_button.state(['disabled'] if problem else ['!disabled'])

    def show_equipment(self):
        from .cafe_equipment_gui import CafeEquipmentWindow
        self.equipment_window = CafeEquipmentWindow(self.window, self.session, self.changed)

    def changed(self):
        self.on_changed()
        self.refresh()

    def purchase(self):
        from tkinter import messagebox
        core = self.session.core
        step = next_step(core, self.selected)
        if not step or not messagebox.askyesno('席の増設', f"{step['from_seats']}席から{step['to_seats']}席へ増設しますか？\n費用：{step['cost']:g}\n増設後の所持金：{core.funds-step['cost']:g}\n購入後の取り消し・返金はできません。", parent=self.window):
            return
        try:
            self.session.expand_seats(self.selected)
        except (ValueError, OSError) as exc:
            messagebox.showerror('増設できません', str(exc), parent=self.window)
        self.on_changed()
        self.refresh()
