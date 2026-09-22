"""来店済みのお客さんの好みと猫ごとの相性を比較する。"""
from .core.cafe_preferences import FEATURES, match


class CafePreferencesWindow:
    def __init__(self, parent, session, customer_id=''):
        import tkinter as tk
        from tkinter import ttk
        from .cafe_history import CafeHistoryWindow
        self.session = session
        self.window = tk.Toplevel(parent)
        self.window.title('お客さんの好み・猫との相性')
        self.window.geometry('850x420')
        self.window.minsize(500, 320)
        self.window.transient(parent)
        self.window.grab_set()
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        self.close_button = ttk.Button(frame, text='閉じる', command=self.window.destroy)
        self.close_button.pack(side='bottom', anchor='e')
        core = session.core
        known = sorted(set(core.visits) | core.returning_customers)
        self.customer = tk.StringVar(value=customer_id if customer_id in known else next(iter(known), ''))
        self.customers = ttk.Combobox(frame, values=known, textvariable=self.customer, state='readonly')
        self.customers.pack(fill='x')
        self.notice = tk.StringVar()
        ttk.Label(frame, textvariable=self.notice, wraplength=460).pack(anchor='w', pady=6)
        self.cats = CafeHistoryWindow.table(frame, ('猫', '特徴', '相性', '現在の担当可否'))
        self.cats.column('相性', width=340)
        self.customers.bind('<<ComboboxSelected>>', lambda event: self.refresh())
        self.window.bind('<Escape>', lambda event: self.window.destroy())
        self.refresh()

    def refresh(self):
        core = self.session.core
        customer_id = self.customer.get()
        self.cats.delete(*self.cats.get_children())
        data = core.customer_preferences
        preferred = data['customers'].get(customer_id) if data else None
        self.notice.set('好みは未導入です。新規ゲームで利用できます。' if data is None else
                        '来店後にお客さんの好みを確認できます。' if not customer_id else
                        f"{customer_id}：{FEATURES[preferred][0]}好き。通常行動のテンション上昇×{data['rules']['tension_multiplier']:g}。特別行動やテンション減少には補正しません。")
        for row in self.session.cat_choices(customer_id):
            result = match(core, row['cat_id'], customer_id)
            self.cats.insert('', 'end', iid=row['cat_id'], values=(row['name'], result['features'], result['text'],
                             '担当可能' if row['available'] and customer_id in core.queue else '現在は割り当て不可'))
