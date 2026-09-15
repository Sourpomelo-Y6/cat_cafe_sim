"""保存済みの営業履歴から表示用の比較データを作る。営業状態は変更しない。"""
import copy
from .cafe_health_text import health_result_text


def comparison_rows(core):
    days = copy.deepcopy(core.day_results)
    if core.closed:
        days.append(core.day_result())
    counts = {}
    day = 1
    for event in core.events:
        if event['kind'] == 'next_day':
            day = event['day']
        elif event['kind'] == 'interaction_completed':
            key = (day, event['result']['cat_id'])
            counts[key] = counts.get(key, 0) + 1
    for result in days:
        for cat_id, cat in result['cats'].items():
            cat['interactions'] = cat.get('interactions', counts.get((result['day'], cat_id), 0))
            cat['affinity_delta'] = sum(row['change'] for row in result['affinity_changes']
                                        if row['cat_id'] == cat_id)
    return days


class CafeHistoryWindow:
    def __init__(self, parent, session):
        import tkinter as tk
        from tkinter import ttk
        self.window = tk.Toplevel(parent)
        self.window.title('営業結果の比較')
        self.window.geometry('820x560')
        self.window.minsize(640, 420)
        self.window.transient(parent)
        self.window.grab_set()
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        rows = comparison_rows(session.core)
        ttk.Label(frame, text='閉店した日の確定結果を比較します。営業途中の日は含みません。').pack(anchor='w')
        if session.pending:
            ttk.Label(frame, text='関係データへの保存が未完了です。営業画面で保存を再試行してください。').pack(anchor='w')
        if not rows:
            ttk.Label(frame, text='まだ閉店した営業日がありません。').pack(anchor='w', pady=8)
        self.days = self.table(frame, ('日目', '売上', 'うちボーナス', '交流件数', '閉店時所持金'))
        ttk.Label(frame, text='猫ごとの比較（体力消耗は営業開始時からの差、親しみは各お客への実増減の合計）',
                  wraplength=600).pack(anchor='w', pady=(10, 0))
        self.cats = self.table(frame, ('日目', '猫', '接客回数', '体力消耗', '残り体力', '親しみ増減', '出勤・休養', '疲労変化', '体調・療養'))
        for result in rows:
            summary = result['summary']
            self.days.insert('', 'end', values=(result['day'], f"{summary['revenue']:g}",
                f"{summary['interaction_bonus']:g}", summary['completed_interactions'], f"{summary['funds']:g}"))
            for cat_id, cat in result['cats'].items():
                name = session.profiles.get(cat_id, {}).get('name', cat_id)
                self.cats.insert('', 'end', values=(result['day'], f'{name}（{cat_id}）', cat['interactions'],
                    f"{cat['spent']:g}", f"{cat['stamina']:g}", f"{cat['affinity_delta']:+g}",
                    {'work': '出勤', 'rest': '休養'}.get(cat.get('shift'), '記録なし'),
                    f"{cat['fatigue_before']:g} → {cat['fatigue_after']:g}" if 'fatigue_before' in cat else '記録なし',
                    health_result_text(cat['health']) if 'health' in cat else '記録なし'))
        ttk.Button(frame, text='閉じる', command=self.window.destroy).pack(anchor='e', pady=(8, 0))
        self.window.bind('<Escape>', lambda event: self.window.destroy())

    @staticmethod
    def table(parent, columns):
        from tkinter import ttk
        frame = ttk.Frame(parent)
        frame.pack(fill='both', expand=True, pady=4)
        tree = ttk.Treeview(frame, columns=columns, show='headings', height=5)
        for column in columns:
            tree.heading(column, text=column)
            tree.column(column, width=210 if column in ('猫','体調・療養') else 105, minwidth=70)
        vertical = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
        horizontal = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        tree.grid(row=0, column=0, sticky='nsew')
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        return tree
