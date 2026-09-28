"""お客さんの名簿・本日の来店予定と猫別の親しみ。"""
from .cafe_customers import directory, cat_rows, customer_label
from .core.cafe_activities import ACTIVITY_LABELS
from .core.cafe_weekdays import day_label


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
        ttk.Label(frame, text=f'{day_label(core)}のお客さんの名簿', font=('',12,'bold')).pack(anchor='w')
        ttk.Label(frame, text='予定は営業した場合の進行時点（0＝開店時）です。休業すると来店しません。\n来店回数はこの営業セーブの記録内で集計し、接客できなかった来店も含みます。', wraplength=620).pack(anchor='w', pady=5)
        self.view_day = tk.StringVar(value='今日：' + day_label(core))
        self.day_choices = ('今日：' + day_label(core), '翌日：' + day_label(core, core.day + 1))
        self.day_selector = ttk.Combobox(frame, textvariable=self.view_day, values=self.day_choices, state='readonly')
        self.day_selector.pack(anchor='w', pady=(0,4))
        self.day_selector.bind('<<ComboboxSelected>>', lambda event: self.fill())
        self.customers = CafeHistoryWindow.table(frame, ('お客さん','好み','来店回数','常連度','累積不満','予定の進行','本日の状態'))
        self.customers.column('お客さん', width=145)
        self.customers.column('好み', width=65)
        self.customers.column('来店回数', width=55)
        self.customers.column('常連度', width=90)
        self.customers.column('累積不満', width=80)
        self.customers.column('予定の進行', width=70)
        self.customers.column('本日の状態', width=105)
        self.details = tk.StringVar(value='お客さんを選ぶと、猫別の親しみと相性を表示します。')
        ttk.Label(frame, textvariable=self.details, wraplength=620).pack(anchor='w', pady=4)
        self.cats = CafeHistoryWindow.table(frame, ('猫','猫から客への親しみ','好みとの相性','予定・状態'))
        self.cats.column('猫', width=150)
        self.cats.column('予定・状態', width=155)
        self.cats.column('猫から客への親しみ', width=150)
        self.cats.column('好みとの相性', width=120)
        self.customers.bind('<<TreeviewSelect>>', lambda event: self.select())
        self.window.bind('<Escape>', lambda event: self.window.destroy())
        self.fill()

    def fill(self):
        selected = self.customers.selection()
        self.customers.delete(*self.customers.get_children())
        tomorrow = self.view_day.get() == self.day_choices[1]
        self.customers.heading('本日の状態', text='翌日の予定' if tomorrow else '本日の状態')
        for row in directory(self.session):
            tick = row['tomorrow_tick'] if tomorrow else row['arrival_tick']
            status = (f"来店停止（{row['tomorrow_suspended_until']}日目まで）" if tomorrow and row['tomorrow_suspended_until'] is not None else
                      '来店予定' if tomorrow and tick is not None else '予定なし' if tomorrow else row['status'])
            self.customers.insert('', 'end', iid=row['customer_id'], values=(customer_label(row['customer_id']),
                row['preference_text'], row['visits'], '未導入' if row['loyalty'] is None else
                f"{row['loyalty']:g}/{row['loyalty_target']:g}"+('・常連' if row['regular_day'] is not None else ''),
                '未導入' if row['discontent'] is None else f"{row['discontent']:g}/{row['discontent_target']:g}",
                '—' if tick is None else tick, status))
        if self.customers.get_children():
            self.customers.selection_set(selected[0] if selected and self.customers.exists(selected[0]) else self.customers.get_children()[0])
            self.select()

    def select(self):
        selection = self.customers.selection()
        self.cats.delete(*self.cats.get_children())
        if not selection:
            return
        key = selection[0]
        row = next(row for row in directory(self.session) if row['customer_id'] == key)
        loyalty = ('常連度：未導入' if row['loyalty'] is None else
                   f"常連度：{row['loyalty']:g}/{row['loyalty_target']:g}" +
                   (f"・{row['regular_day']}日目に常連化" if row['regular_day'] is not None else '・接客で親しみが増えると上昇'))
        discontent = ('累積不満：未導入' if row['discontent'] is None else
                      f"累積不満：{row['discontent']:g}/{row['discontent_target']:g}"+
                      (f"・{row['suspended_until']}日目まで来店停止、翌日から不満{row['discontent_return']:g}で復帰" if row['suspended_until'] is not None else ''))
        satisfaction = ('直近の接客評価：記録なし' if row['satisfaction'] is None else
                        f"直近の接客評価：{row['satisfaction']['label']}（点数 {row['satisfaction']['score']:g}"
                        f"・{('、'.join(row['satisfaction']['reasons']) or '加点要素なし')}）")
        trust_labels={'stable':'通常','waiting':'回答待ち','recovery':'信頼回復中','departed':'永久離脱'}
        trust='信頼状態：未導入' if row['trust'] is None else '信頼状態：'+trust_labels[row['trust']['status']]
        self.details.set(customer_label(key) + '・来店曜日：' + row['weekdays'] + '\n' + loyalty +
                         '\n' + discontent + '・' + trust + '\n' + satisfaction +
                         (' 接客結果の保存待ちがあります。' if self.session.pending else ''))
        from .core.cafe_advanced_customers import CUSTOMER_ID, description, result_text
        if key == CUSTOMER_ID and self.session.core.advanced_customers is not None:
            from .core.cafe_checkpoint import outcome_result
            latest = next((outcome_result(value) for value in reversed(list(self.session.core.outcomes.values()))
                           if outcome_result(value)['customer_id'] == key), None)
            self.details.set(description(self.session.core) + '\n' +
                             ('直近の接客：' + result_text(self.session.core, latest) if latest else '接客結果はまだありません。')+
                             '\n'+self.details.get())
        from .core.cafe_reservation import CUSTOMER_ID as RESERVATION_ID
        if key==RESERVATION_ID and self.session.core.reservation is not None:
            rules=self.session.core.reservation['rules'];request=self.session.core.reservation['request']
            state='依頼前' if request is None else {'waiting':'回答待ち','accepted':'受け入れ','declined':'見送り'}[request['status']]
            self.details.set(f"特別予約：{state}。長毛の猫を担当し、心を開く{rules['open_up_count']}回以上で追加料金＋{rules['bonus']:g}・人気＋{rules['popularity_bonus']:g}。\n"+self.details.get())
        for row in cat_rows(self.session, key):
            status = ACTIVITY_LABELS[row['activity']] if row['activity'] != 'cafe' else ('出勤予定' if row['working'] else '休養予定')
            from .cafe_health_text import health_text
            status += '・' + health_text(row['health_status'], row['recovery_days_remaining'])
            self.cats.insert('', 'end', iid=row['cat_id'], values=(row['name'], f"{row['affinity']:g}", row['match_text'], status))
