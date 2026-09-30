"""所持品と在店猫を選び、準備中にケア用品を使う。"""
from .core.cafe_items import inventory, unavailable_reason, stat, relief, current, effect_text,after_value,change_text


class CafeItemsWindow:
    def __init__(self, parent, session, on_changed):
        import tkinter as tk
        from tkinter import ttk
        from .cafe_history import CafeHistoryWindow
        self.session, self.on_changed = session, on_changed
        self.window = tk.Toplevel(parent)
        self.window.title('所持品・猫のケア')
        self.window.geometry('740x560')
        self.window.minsize(580, 460)
        self.window.transient(parent)
        self.window.grab_set()
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        footer = ttk.Frame(frame)
        footer.pack(side='bottom', fill='x', pady=(8, 0))
        self.notice = tk.StringVar()
        self.result = tk.StringVar()
        ttk.Label(footer, textvariable=self.result, wraplength=540).pack(anchor='w')
        ttk.Label(footer, textvariable=self.notice, wraplength=540).pack(anchor='w', pady=4)
        from .core.cafe_item_shop import catalog
        self.shop_catalog = catalog()
        self.shop_rules = self.shop_catalog[0]
        self.shop_choice = ttk.Combobox(frame, state='readonly', values=[row['item']['name'] for row in self.shop_catalog])
        self.shop_choice.pack(fill='x')
        self.shop_choice.current(0)
        self.shop_choice.bind('<<ComboboxSelected>>', lambda event: self.select_shop())
        self.shop_note=tk.StringVar()
        ttk.Label(frame,textvariable=self.shop_note,wraplength=540).pack(anchor='w')
        from .core.cafe_item_sales import prices
        self.sale_prices = prices()
        sale_controls = ttk.Frame(footer)
        sale_controls.pack(fill='x', pady=(0, 4))
        self.sale_notice = tk.StringVar()
        self.sell_button = ttk.Button(sale_controls, text='選んだ用品を1個売却', command=self.sell)
        self.sell_button.pack(side='left')
        ttk.Label(sale_controls, textvariable=self.sale_notice, wraplength=340).pack(side='left', padx=8)
        self.buy_button=ttk.Button(footer,text='ケア用品を1個購入',command=self.buy)
        self.buy_button.pack(side='left',padx=(0,8))
        self.use_button = ttk.Button(footer, text='選んだ猫に1個使う', command=self.use)
        self.use_button.pack(side='left')
        self.close_button = ttk.Button(footer, text='閉じる', command=self.window.destroy)
        self.close_button.pack(side='right')
        ttk.Label(frame, text='ケア用品は購入または近所のお店への訪問、栄養おやつ・特製ケアセットは購入で入手できます。\n準備中に在店猫へ使えます。', wraplength=540).pack(anchor='w', pady=(0, 8))
        pages = ttk.Notebook(frame)
        pages.pack(fill='both', expand=True)
        use_page = ttk.Frame(pages)
        history_page = ttk.Frame(pages)
        pages.add(use_page, text='所持品と対象猫')
        pages.add(history_page, text='使用履歴')
        sale_page = ttk.Frame(pages)
        pages.add(sale_page, text='売却履歴')
        self.sale_history = CafeHistoryWindow.table(sale_page, ('売却日', 'アイテム', '金額'))
        use_page.columnconfigure(0, weight=1)
        for i in (0, 1):
            use_page.rowconfigure(i, weight=1, uniform='tables')
        item_frame = ttk.Frame(use_page)
        item_frame.grid(row=0, column=0, sticky='nsew')
        cat_frame = ttk.Frame(use_page)
        cat_frame.grid(row=1, column=0, sticky='nsew', pady=(8, 0))
        self.items = CafeHistoryWindow.table(item_frame, ('アイテム', '所持数', '効果'))
        self.cats = CafeHistoryWindow.table(cat_frame, ('猫', '活動', 'ストレス', '疲労'))
        self.history = CafeHistoryWindow.table(history_page, ('使用日', '猫', 'アイテム', '変化'))
        self.items.bind('<<TreeviewSelect>>', lambda event: self.selection_changed())
        self.cats.bind('<<TreeviewSelect>>', lambda event: self.selection_changed())
        self.window.bind('<Escape>', lambda event: self.window.destroy())
        self.refresh()

    def select_shop(self):
        self.shop_rules = self.shop_catalog[self.shop_choice.current()]
        self.refresh()

    def refresh(self):
        from .core.cafe_activities import ACTIVITY_LABELS
        core = self.session.core
        from .core.cafe_item_shop import reason
        selected=self.shop_rules
        count=sum(item==selected['item'] for item in inventory(core).values())
        problem=reason(core,selected)
        if self.session.pending:problem='先に交流結果の保存を再試行してください。'
        self.shop_note.set(f"資金 {core.funds:g} / {selected['item']['name']} 1個 {selected['cost']:g} / 所持 {count}個 / {effect_text(selected['item'])}"+(f'\n{problem}' if problem else ''))
        self.buy_button.configure(text=selected['item']['name']+'を1個購入')
        self.buy_button.state(['disabled'] if problem else ['!disabled'])
        previous_items, previous_cats = self.items.selection(), self.cats.selection()
        self.items.delete(*self.items.get_children())
        self.cats.delete(*self.cats.get_children())
        self.history.delete(*self.history.get_children())
        self.sale_history.delete(*self.sale_history.get_children())
        from .core.cafe_items import reward_for_source
        for row in reversed(core.item_sales):
            item = reward_for_source(core, row['source'])['item']
            self.sale_history.insert('', 'end', values=(f"{row['day']}日目", item['name'], f"{row['price']:g}"))
        groups = {}
        for source, item in inventory(core).items():
            amount=relief(item)
            key = (item['id'], item['name'], tuple(amount.items()) if isinstance(amount,dict) else amount)
            groups.setdefault(key, []).append(source)
        for (_, name, _), sources in groups.items():
            self.items.insert('', 'end', iid=sources[0], values=(name, len(sources), effect_text(inventory(core)[sources[0]])))
        for key in core.cats:
            self.cats.insert('', 'end', iid=key, values=(self.session.profiles.get(key, {}).get('name', key),
                ACTIVITY_LABELS[core.activity(key)], f"{core.management['stress'][key]:g}" if core.management else '未導入', f'{core.cats[key].fatigue:g}'))
        for row in reversed(core.item_uses):
            from .core.cafe_items import reward_for_source
            item = reward_for_source(core,row['source'])['item']
            self.history.insert('', 'end', values=(f"{row['day']}日目", self.session.profiles.get(row['cat_id'], {}).get('name', row['cat_id']),
                item['name'], change_text(item,row['before'],row['after'])))
        for table, previous in ((self.items, previous_items), (self.cats, previous_cats)):
            keys = table.get_children()
            if keys:
                table.selection_set(previous[0] if previous and previous[0] in keys else keys[0])
        self.selection_changed()

    def selection_changed(self):
        self.use_button.state(['disabled'])
        sources, cats = self.items.selection(), self.cats.selection()
        from .core.cafe_item_sales import reason as sale_reason
        problem = '先に接客結果の保存を再試行してください。' if self.session.pending else sale_reason(self.session.core, sources[0] if sources else '')
        self.sell_button.state(['disabled'] if problem else ['!disabled'])
        item = inventory(self.session.core).get(sources[0]) if sources else None
        self.sale_notice.set(problem if problem else f"1個売却：{self.sale_prices[item['id']]:g}を受け取ります。")
        if not sources:
            self.notice.set('所持品はありません。購入や派遣の帰還報酬で入手できます。')
            return
        if not cats:
            self.notice.set('対象の猫を選んでください。')
            return
        reason = unavailable_reason(self.session.core, sources[0], cats[0])
        if self.session.pending:
            reason = '先に交流結果の保存を再試行してください。'
        if reason:
            self.notice.set(reason)
            return
        item = inventory(self.session.core)[sources[0]]
        before = current(self.session.core, item, cats[0])
        note = '体力・ストレス・好感度、病気の療養日数は変わりません。' if stat(item)=='fatigue' else '体力・疲労・好感度は変わりません。'
        if stat(item)=='both':note='体力・好感度、病気の状態・療養日数は変わりません。'
        self.notice.set('1個消費：'+change_text(item,before,after_value(item,before))+'。'+note)
        self.use_button.state(['!disabled'])

    def use(self):
        from tkinter import messagebox
        sources, cats = self.items.selection(), self.cats.selection()
        if not sources or not cats:
            return
        if not messagebox.askyesno('アイテムの使用', self.notice.get()+'\nこの猫に使いますか？', parent=self.window):
            return
        try:
            self.session.use_item(sources[0], cats[0])
        except (ValueError, OSError) as exc:
            messagebox.showerror('アイテムを使えません', str(exc), parent=self.window)
        else:
            row = self.session.core.item_uses[-1]
            name = self.session.profiles.get(cats[0], {}).get('name', cats[0])
            from .core.cafe_items import reward_for_source
            item = reward_for_source(self.session.core, sources[0])['item']
            self.result.set(f"{name}に使用しました。"+change_text(item,row['before'],row['after']))
        self.on_changed()
        self.refresh()

    def buy(self):
        from tkinter import messagebox
        selected=self.shop_rules
        warning='\n資金が0になりゲームオーバーになります。' if self.session.core.funds==selected['cost'] and self.session.core.management else ''
        if not messagebox.askyesno('アイテムの購入',f"{selected['item']['name']}を1個、{selected['cost']:g}で購入しますか？"+warning,parent=self.window):return
        try:self.session.purchase_item(selected)
        except (ValueError,OSError) as exc:
            messagebox.showerror('購入できません',str(exc),parent=self.window)
        else:self.result.set(f"{selected['item']['name']}を1個購入しました。")
        self.on_changed();self.refresh()


    def sell(self):
        from tkinter import messagebox
        from .core.cafe_item_sales import reason
        sources = self.items.selection()
        if not sources:
            return
        source = sources[0]
        if self.session.pending or reason(self.session.core, source):
            self.refresh()
            return
        item = inventory(self.session.core)[source]
        price = self.sale_prices[item['id']]
        if not messagebox.askyesno('アイテムの売却',
                f"{item['name']}を1個、{price:g}で売却しますか？\n売却後の所持金：{self.session.core.funds+price:g}", parent=self.window):
            return
        try:
            self.session.sell_item(source, price)
        except (ValueError, OSError) as exc:
            messagebox.showerror('売却できません', str(exc), parent=self.window)
        else:
            self.result.set(f"{item['name']}を1個売却しました。収入 {price:g}")
        self.on_changed()
        self.refresh()
