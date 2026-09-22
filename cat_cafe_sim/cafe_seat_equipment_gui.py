"""席の接客設備を購入・設置する画面。"""
from .core.cafe_seat_equipment import catalog, seats, owned, description, reason


class CafeSeatEquipmentWindow:
    def __init__(self, parent, session, on_changed):
        import tkinter as tk
        from tkinter import ttk
        self.session, self.on_changed = session, on_changed
        self.catalog = catalog()
        self.window = tk.Toplevel(parent)
        self.window.title('席の接客設備')
        self.window.geometry('700x480')
        self.window.minsize(620,460)
        self.window.transient(parent)
        self.window.grab_set()
        frame = ttk.Frame(self.window,padding=12)
        frame.pack(fill='both',expand=True)
        ttk.Button(frame,text='閉じる',command=self.window.destroy).pack(side='bottom',anchor='e')
        self.status, self.notice, self.layout = tk.StringVar(), tk.StringVar(), tk.StringVar()
        ttk.Label(frame,textvariable=self.status).pack(anchor='w',pady=4)
        self.seat = tk.StringVar(value=next(iter(seats(session.core))))
        self.seat_selector = ttk.Combobox(frame,textvariable=self.seat,values=tuple(seats(session.core)),state='readonly')
        self.seat_selector.pack(anchor='w',pady=4)
        self.seat_selector.bind('<<ComboboxSelected>>',lambda event:self.refresh())
        ttk.Label(frame,textvariable=self.layout,wraplength=590).pack(anchor='w',pady=2)
        buy = ttk.LabelFrame(frame,text='新しく購入して選択席へ設置',padding=8)
        buy.pack(fill='x',pady=5)
        self.kind = tk.StringVar(value=self.catalog[0]['name'])
        self.kind_selector = ttk.Combobox(buy,textvariable=self.kind,values=[r['name'] for r in self.catalog],state='readonly')
        self.kind_selector.pack(side='left',fill='x',expand=True)
        self.purchase_button = ttk.Button(buy,text='購入・設置…',command=self.purchase)
        self.purchase_button.pack(side='right',padx=5)
        self.kind_selector.bind('<<ComboboxSelected>>',lambda event:self.refresh())
        self.detail = tk.StringVar()
        ttk.Label(frame,textvariable=self.detail,wraplength=590).pack(anchor='w',pady=4)
        storage = ttk.LabelFrame(frame,text='購入済み設備の配置（無料）',padding=8)
        storage.pack(fill='x',pady=5)
        self.item = tk.StringVar()
        self.item_selector = ttk.Combobox(storage,textvariable=self.item,state='readonly')
        self.item_selector.pack(fill='x')
        controls=ttk.Frame(storage)
        controls.pack(fill='x',pady=(5,0))
        self.equip_button = ttk.Button(controls,text='選択席へ設置・移動',command=self.equip)
        self.equip_button.pack(side='left')
        self.remove_button = ttk.Button(controls,text='選択席から取り外す',command=self.remove)
        self.remove_button.pack(side='left',padx=5)
        ttk.Label(frame,textvariable=self.notice,wraplength=590).pack(anchor='w',pady=5)
        self.window.bind('<Escape>',lambda event:self.window.destroy())
        self.refresh()

    def selected(self):
        return next(row for row in self.catalog if row['name']==self.kind.get())

    def refresh(self):
        core=self.session.core
        self.status.set(f'所持金 {core.funds:g} / 準備中は1席に設備1つを設置できます。')
        self.layout.set('\n'.join(f'{key}：{description(core,key)}' for key in seats(core)))
        row=self.selected()
        self.detail.set(f"費用 {row['cost']:g} / 関心の通常上昇×{row['engagement']:g}・テンションの通常上昇×{row['tension']:g}。\n特別行動のテンション上昇・減少量・体力消費は変更しません。")
        self.items={f"{r['rules']['name']}（{r['id']}）":r['id'] for r in owned(core)}
        self.item_selector.configure(values=tuple(self.items))
        if self.item.get() not in self.items:
            self.item.set(next(iter(self.items),''))
        problem='接客結果の保存を再試行してください。' if self.session.pending else reason(core)
        self.purchase_button.state(['disabled'] if problem or core.funds<=row['cost'] else ['!disabled'])
        self.equip_button.state(['disabled'] if problem or not self.items else ['!disabled'])
        self.remove_button.state(['disabled'] if problem or seats(core)[self.seat.get()].equipment is None else ['!disabled'])
        self.notice.set(problem or '移動・取り外しは無料。取り外した設備は保管します。\n購入後に資金が残る必要があります。')

    def perform(self, action):
        from tkinter import messagebox
        try:
            action()
        except (ValueError,OSError) as exc:
            messagebox.showerror('設備を変更できません',str(exc),parent=self.window)
        self.on_changed()
        self.refresh()

    def purchase(self):
        from tkinter import messagebox
        row=self.selected()
        if messagebox.askyesno('接客設備を購入',f"{row['name']}を{row['cost']:g}で1個購入し、{self.seat.get()}に設置しますか？\n設置中の設備は保管します。購入後の資金：{self.session.core.funds-row['cost']:g}\n購入の取消・返金はできません。",parent=self.window):
            self.perform(lambda:self.session.purchase_seat_equipment(self.seat.get(),row))

    def equip(self):
        self.perform(lambda:self.session.equip_seat(self.seat.get(),self.items.get(self.item.get())))

    def remove(self):
        self.perform(lambda:self.session.equip_seat(self.seat.get()))
