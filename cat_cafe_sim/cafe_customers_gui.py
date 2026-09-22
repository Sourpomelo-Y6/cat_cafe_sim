"""お客さんの名簿・本日の来店予定と猫別の親しみ。"""
from .cafe_customers import directory, cat_rows, customer_label
from .core.cafe_activities import ACTIVITY_LABELS


class CafeCustomersWindow:
    def __init__(self, parent, session):
        import tkinter as tk
        from tkinter import ttk
        from .cafe_history import CafeHistoryWindow
        self.session = session
        self.window = tk.Toplevel(parent)
        self.window.title('お客さんの名簿・来店予定')
        self.window.geometry('900x620')
        self.window.minsize(660, 520)
        self.window.transient(parent)
        self.window.grab_set()
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        ttk.Button(frame, text='閉じる', command=self.window.destroy).pack(side='bottom', anchor='e', pady=(6,0))
        core = session.core
        ttk.Label(frame, text=f'{core.day}日目の来店予定とお客さんの名簿', font=('',12,'bold')).pack(anchor='w')
        ttk.Label(frame, text='予定は営業した場合の進行時点（0＝開店時）です。休業すると来店しません。\n来店回数はこの営業セーブの記録内で集計し、接客できなかった来店も含みます。', wraplength=620).pack(anchor='w', pady=5)
        self.customers = CafeHistoryWindow.table(frame, ('お客さん','好み','来店回数','予定の進行','本日の状態'))
        self.customers.column('お客さん', width=190)
        self.customers.column('好み', width=90)
        self.customers.column('来店回数', width=80)
        self.customers.column('予定の進行', width=90)
        self.customers.column('本日の状態', width=135)
        self.details = tk.StringVar(value='お客さんを選ぶと、猫別の親しみと相性を表示します。')
        ttk.Label(frame, textvariable=self.details, wraplength=620).pack(anchor='w', pady=4)
        self.cats = CafeHistoryWindow.table(frame, ('猫','猫から客への親しみ','好みとの相性','予定・状態'))
        self.cats.column('猫', width=150)
        self.cats.column('予定・状態', width=155)
        self.cats.column('猫から客への親しみ', width=150)
        self.cats.column('好みとの相性', width=120)
        for row in directory(session):
            self.customers.insert('', 'end', iid=row['customer_id'], values=(customer_label(row['customer_id']),
                row['preference_text'], row['visits'], '—' if row['arrival_tick'] is None else row['arrival_tick'], row['status']))
        self.customers.bind('<<TreeviewSelect>>', lambda event: self.select())
        self.window.bind('<Escape>', lambda event: self.window.destroy())
        if self.customers.get_children():
            self.customers.selection_set(self.customers.get_children()[0])
            self.select()

    def select(self):
        selection = self.customers.selection()
        self.cats.delete(*self.cats.get_children())
        if not selection:
            return
        key = selection[0]
        self.details.set(customer_label(key) + '：猫からこのお客さんへの親しみ（保存済みの値）です。' +
                         (' 接客結果の保存待ちがあります。' if self.session.pending else ''))
        for row in cat_rows(self.session, key):
            status = ACTIVITY_LABELS[row['activity']] if row['activity'] != 'cafe' else ('出勤予定' if row['working'] else '休養予定')
            from .cafe_health_text import health_text
            status += '・' + health_text(row['health_status'], row['recovery_days_remaining'])
            self.cats.insert('', 'end', iid=row['cat_id'], values=(row['name'], f"{row['affinity']:g}", row['match_text'], status))
