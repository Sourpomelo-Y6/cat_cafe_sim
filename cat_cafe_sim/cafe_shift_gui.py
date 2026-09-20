"""営業開始前の出勤・休養設定画面。"""
from .cafe_health_text import health_text
from .core.cafe_shifts import fatigue_rest_schedule
from .cafe_shift_forecast import shift_forecast, estimate_text, forecast_note


class CafeShiftWindow:
    def __init__(self, parent, session, on_saved):
        import tkinter as tk
        from tkinter import ttk
        self.session = session
        self.on_saved = on_saved
        self.window = tk.Toplevel(parent)
        self.window.title('出勤・休養の設定')
        self.window.geometry('960x480')
        self.window.minsize(500, 400)
        self.window.transient(parent)
        self.window.grab_set()
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='営業開始前に設定してください。前日の設定を引き継ぎます。').pack(anchor='w')
        ttk.Label(frame, text='予測欄：閉店時の疲労 / 発症確率。出勤は前日の接客量を使った目安です。',
                  wraplength=460).pack(anchor='w')
        self.forecasts = {key: shift_forecast(session.core, key) for key in session.core.cats}
        self.forecast_note = tk.StringVar()
        footer = ttk.Frame(frame)
        footer.pack(side='bottom', fill='x')
        self.proposal_button = ttk.Button(frame, text='疲労が高い2匹を休養する案を作成', command=self.propose_rest)
        self.proposal_button.pack(anchor='w', pady=(6, 0))
        ttk.Label(frame, text='案は健康な猫を疲労順に最大2匹休養、残りを出勤にします。手動で変更できます。',
                  wraplength=460).pack(anchor='w')
        self.schedule_note = tk.StringVar()
        ttk.Label(frame, textvariable=self.schedule_note, wraplength=460).pack(anchor='w')
        body = ttk.Frame(frame)
        body.pack(fill='both', expand=True, pady=8)
        self.tree = ttk.Treeview(body, columns=('name', 'fatigue', 'shift', 'health', 'basis', 'work_forecast', 'rest_forecast'), show='headings', selectmode='browse')
        for key, label, width in (('name', '猫', 200), ('fatigue', '現在の疲労', 80), ('shift', '本日の予定', 80), ('health', '体調', 110),
                                   ('basis', '前日接客行動数', 110), ('work_forecast', '出勤予測：疲労 / 発症', 170),
                                   ('rest_forecast', '休養予測：疲労 / 発症', 170)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=70)
        horizontal = ttk.Scrollbar(body, orient='horizontal', command=self.tree.xview)
        self.tree.configure(xscrollcommand=horizontal.set)
        horizontal.pack(side='bottom',fill='x')
        scroll = ttk.Scrollbar(body, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        self.working = set(session.core.working_cats)
        for row in session.cat_choices():
            forecast=self.forecasts[row['cat_id']]
            self.tree.insert('', 'end', iid=row['cat_id'], values=(f"{row['name']}（{row['cat_id']}）",
                             f"{row['fatigue']:g}", '出勤' if row['working'] else '休養', health_text(row['health_status'],row['recovery_days_remaining']),
                             forecast['previous_actions'] if forecast['previous_actions'] is not None else '記録なし',
                             '出勤不可' if forecast['sick'] else estimate_text(forecast['work']), estimate_text(forecast['rest'])))
        self.tree.selection_set(next(iter(session.core.cats)))
        ttk.Label(footer, textvariable=self.forecast_note, wraplength=460).pack(anchor='w', pady=(0,8))
        controls = ttk.Frame(footer)
        controls.pack(fill='x')
        self.work_button=ttk.Button(controls, text='選択した猫を出勤', command=lambda: self.set_selected(True))
        self.work_button.pack(side='left')
        self.tree.bind('<<TreeviewSelect>>',lambda event:self.refresh_selection())
        self.refresh_selection()
        ttk.Button(controls, text='選択した猫を休養', command=lambda: self.set_selected(False)).pack(side='left', padx=4)
        self.save_button = ttk.Button(controls, text='設定を保存', command=self.save)
        self.save_button.pack(side='right')
        ttk.Button(controls, text='キャンセル', command=self.window.destroy).pack(side='right', padx=4)
        self.window.bind('<Escape>', lambda event: self.window.destroy())
        self.refresh_schedule()

    def refresh_selection(self):
        selected=self.tree.selection()
        available=bool(selected) and all(self.session.core.cats[key].health_status=='healthy' and self.session.core.activity(key)=='cafe' for key in selected)
        self.work_button.state(['!disabled'] if available else ['disabled'])
        self.forecast_note.set('在店していない猫は出勤・休養の対象外です。' if selected and self.session.core.activity(selected[0])!='cafe' else forecast_note(self.forecasts[selected[0]]) if selected else '猫を選ぶと予測の根拠を確認できます。')

    def set_selected(self, working):
        for key in self.tree.selection():
            if working:
                if self.session.core.cats[key].health_status != 'healthy' or self.session.core.activity(key)!='cafe':
                    return
                self.working.add(key)
            else:
                self.working.discard(key)
            self.tree.set(key, 'shift', '出勤' if working else '休養')
        self.refresh_schedule()

    def refresh_schedule(self):
        from .core.cafe_activities import ACTIVITY_LABELS
        for key in self.session.core.cats:
            location=self.session.core.activity(key)
            self.tree.set(key, 'shift', ACTIVITY_LABELS[location] if location!='cafe' else '出勤' if key in self.working else '休養')
            if location!='cafe':
                self.tree.set(key,'work_forecast','出勤不可')
                self.tree.set(key,'rest_forecast','在店していません')
        if not self.working:
            self.schedule_note.set('全員休養の予定です（不在猫は対象外）。保存後「今日は休業する」で在店猫を休ませます。')
        else:
            self.schedule_note.set(f'出勤 {len(self.working)}匹 / 休養 {sum(self.session.core.activity(key)=='cafe' for key in self.session.core.cats)-len(self.working)}匹。設定を保存するまで営業には反映されません。')

    def propose_rest(self):
        self.working = set(fatigue_rest_schedule({key:cat for key,cat in self.session.core.cats.items() if self.session.core.activity(key)=='cafe'}))
        self.refresh_schedule()

    def save(self):
        from tkinter import messagebox
        try:
            self.session.set_shifts(sorted(self.working))
        except (ValueError, OSError) as exc:
            messagebox.showerror('出勤・休養を設定できません', str(exc), parent=self.window)
            return
        self.on_saved()
        self.window.destroy()
