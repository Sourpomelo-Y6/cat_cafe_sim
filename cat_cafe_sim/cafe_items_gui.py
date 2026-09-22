"""所持品と在店猫を選び、準備中にケア用品を使う。"""
from .core.cafe_items import inventory, unavailable_reason


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
        self.use_button = ttk.Button(footer, text='選んだ猫に1個使う', command=self.use)
        self.use_button.pack(side='left')
        self.close_button = ttk.Button(footer, text='閉じる', command=self.window.destroy)
        self.close_button.pack(side='right')
        ttk.Label(frame, text='近所のお店への訪問でケア用品を入手できます。\n帰還報酬を受け取った後、準備中に在店猫へ使えます。', wraplength=540).pack(anchor='w', pady=(0, 8))
        pages = ttk.Notebook(frame)
        pages.pack(fill='both', expand=True)
        use_page = ttk.Frame(pages)
        history_page = ttk.Frame(pages)
        pages.add(use_page, text='所持品と対象猫')
        pages.add(history_page, text='使用履歴')
        use_page.columnconfigure(0, weight=1)
        for i in (0, 1):
            use_page.rowconfigure(i, weight=1, uniform='tables')
        item_frame = ttk.Frame(use_page)
        item_frame.grid(row=0, column=0, sticky='nsew')
        cat_frame = ttk.Frame(use_page)
        cat_frame.grid(row=1, column=0, sticky='nsew', pady=(8, 0))
        self.items = CafeHistoryWindow.table(item_frame, ('アイテム', '所持数', '効果'))
        self.cats = CafeHistoryWindow.table(cat_frame, ('猫', '活動', 'ストレス'))
        self.history = CafeHistoryWindow.table(history_page, ('使用日', '猫', 'アイテム', 'ストレス'))
        self.items.bind('<<TreeviewSelect>>', lambda event: self.selection_changed())
        self.cats.bind('<<TreeviewSelect>>', lambda event: self.selection_changed())
        self.window.bind('<Escape>', lambda event: self.window.destroy())
        self.refresh()

    def refresh(self):
        from .core.cafe_activities import ACTIVITY_LABELS
        core = self.session.core
        previous_items, previous_cats = self.items.selection(), self.cats.selection()
        self.items.delete(*self.items.get_children())
        self.cats.delete(*self.cats.get_children())
        self.history.delete(*self.history.get_children())
        groups = {}
        for source, item in inventory(core).items():
            key = (item['id'], item['name'], item['stress_relief'])
            groups.setdefault(key, []).append(source)
        for (_, name, relief), sources in groups.items():
            self.items.insert('', 'end', iid=sources[0], values=(name, len(sources), f'ストレス −{relief:g}'))
        for key in core.cats:
            self.cats.insert('', 'end', iid=key, values=(self.session.profiles.get(key, {}).get('name', key),
                ACTIVITY_LABELS[core.activity(key)], f"{core.management['stress'][key]:g}" if core.management else '未導入'))
        for row in reversed(core.item_uses):
            item = core.activities['events'][row['source']]['item_reward']
            self.history.insert('', 'end', values=(f"{row['day']}日目", self.session.profiles.get(row['cat_id'], {}).get('name', row['cat_id']),
                item['name'], f"{row['before']:g} → {row['after']:g}"))
        for table, previous in ((self.items, previous_items), (self.cats, previous_cats)):
            keys = table.get_children()
            if keys:
                table.selection_set(previous[0] if previous and previous[0] in keys else keys[0])
        self.selection_changed()

    def selection_changed(self):
        self.use_button.state(['disabled'])
        sources, cats = self.items.selection(), self.cats.selection()
        if not sources:
            self.notice.set('所持品はありません。派遣の帰還報酬を受け取ると追加されます。')
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
        before = self.session.core.management['stress'][cats[0]]
        self.notice.set(f"1個消費：ストレス {before:g} → {max(0, before-item['stress_relief']):g}。体力・疲労・好感度は変わりません。")
        self.use_button.state(['!disabled'])

    def use(self):
        from tkinter import messagebox
        sources, cats = self.items.selection(), self.cats.selection()
        if not sources or not cats:
            return
        if not messagebox.askyesno('ケア用品の使用', self.notice.get()+'\nこの猫に使いますか？', parent=self.window):
            return
        try:
            self.session.use_item(sources[0], cats[0])
        except (ValueError, OSError) as exc:
            messagebox.showerror('アイテムを使えません', str(exc), parent=self.window)
        else:
            row = self.session.core.item_uses[-1]
            name = self.session.profiles.get(cats[0], {}).get('name', cats[0])
            self.result.set(f"{name}に使用しました。ストレス {row['before']:g} → {row['after']:g}")
        self.on_changed()
        self.refresh()
