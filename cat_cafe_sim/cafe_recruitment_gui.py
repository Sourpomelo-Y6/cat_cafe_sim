"""保護猫の候補・個性・費用を確認して受け入れる画面。"""
from .core.human_cat_types import Personality


class CafeRecruitmentWindow:
    def __init__(self, parent, session, on_changed, *, pet_shop=False):
        import tkinter as tk
        from tkinter import ttk
        from .cafe_history import CafeHistoryWindow
        self.session, self.on_changed = session, on_changed
        self.pet_shop = pet_shop
        self.title = 'ペットショップ' if pet_shop else '保護猫の受け入れ'
        self.action = '購入' if pet_shop else '受け入れ'
        self.status_label = '購入' if pet_shop else '受入'
        self.cost_label = '購入費' if pet_shop else '初期費用'
        self.window = tk.Toplevel(parent)
        self.window.title(self.title)
        self.window.geometry('800x560')
        self.window.minsize(500, 440)
        self.window.transient(parent)
        self.window.grab_set()
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        footer = ttk.Frame(frame)
        footer.pack(side='bottom', fill='x')
        self.receive_button = ttk.Button(footer, text='選んだ猫を購入する' if pet_shop else '選んだ猫を受け入れる', command=self.receive)
        self.receive_button.pack(side='left')
        if not pet_shop and session.core.intake_request:
            ttk.Button(footer, text='依頼・回答履歴…', command=self.show_request).pack(side='left', padx=6)
        self.close_button = ttk.Button(footer, text='閉じる', command=self.window.destroy)
        self.close_button.pack(side='right')
        self.funds = tk.StringVar()
        ttk.Label(frame, textvariable=self.funds).pack(anchor='w')
        ttk.Label(frame, text=('準備中に購入できます。加入時は健康・体力全回復・休養予定です。候補は固定で、各猫を1回だけ迎えられます。' if pet_shop else '準備中に受け入れます。加入時は健康・体力全回復・休養予定です。3日ごとに候補を3匹追加します。以前の候補も残ります。'), wraplength=460).pack(anchor='w')
        self.schedule = tk.StringVar()
        ttk.Label(frame, textvariable=self.schedule, wraplength=460).pack(anchor='w')
        self.show_accepted=tk.BooleanVar(value=False)
        if not pet_shop:
            self.show_accepted_button=ttk.Checkbutton(frame,text='受け入れ済みも表示',variable=self.show_accepted,command=self.refresh)
            self.show_accepted_button.pack(anchor='w')
        self.notice = tk.StringVar()
        ttk.Label(frame, textvariable=self.notice, wraplength=460).pack(anchor='w')
        self.cats = CafeHistoryWindow.table(frame, ('名前', '特徴', '個性', '特性', self.cost_label, '状態'))
        self.cats.tag_configure('accepted',foreground='#666666',background='#eeeeee')
        self.details = CafeHistoryWindow.table(frame, ('項目', '値'))
        self.details.column('項目', width=230)
        self.details.column('値', width=220)
        self.cats.bind('<<TreeviewSelect>>', lambda event: self.selection_changed())
        self.window.bind('<Escape>', lambda event: self.window.destroy())
        self.refresh()

    @property
    def data(self):
        return self.session.core.pet_shop if self.pet_shop else self.session.core.recruitment

    def show_request(self):
        from .cafe_intake_request_gui import CafeIntakeRequestWindow
        self.request_window = CafeIntakeRequestWindow(self.window, self.session, lambda: (self.on_changed(), self.refresh()))

    def refresh(self):
        core = self.session.core
        from .core.cafe_housing import status
        self.funds.set(f'所持金：{core.funds:g} · {status(core)}')
        from .core.cafe_recruitment import next_candidate_day
        if self.pet_shop:
            self.schedule.set('購入を見送っても候補は残ります。購入後の補充はありません。')
        else:
            due = next_candidate_day(self.data)
            self.schedule.set(f'次の候補追加：{due}日目（準備中にこの画面を開くと追加）')
        selected = self.cats.selection()
        self.cats.delete(*self.cats.get_children())
        from .core.cafe_preferences import feature_text
        candidates=list(self.data['candidates'].items())
        if not self.pet_shop:
            candidates=[(key,row) for key,row in candidates if key not in self.data['accepted']]+(
                [(key,row) for key,row in candidates if key in self.data['accepted']] if self.show_accepted.get() else [])
        for key, row in candidates:
            personality = Personality.from_dict(row['personality'])
            label = next((name for name, value in self.session.presets.items() if value == personality), 'カスタム')
            day = self.data['accepted'].get(key)
            self.cats.insert('', 'end', iid=key, values=(row['name'], feature_text(row.get('features', [])), label, row.get('trait',{}).get('name','なし'), f"{row['cost']:g}", f'{day}日目に{self.status_label}済み' if day else '候補'),tags=('accepted',) if day and not self.pet_shop else ())
        visible=self.cats.get_children()
        if visible:
            self.cats.selection_set(selected[0] if selected and selected[0] in visible else visible[0])
        self.selection_changed()

    def selection_changed(self):
        from .core.cafe_recruitment import require_preparation
        core = self.session.core
        selected = self.cats.selection()
        self.details.delete(*self.details.get_children())
        self.receive_button.state(['disabled'])
        if not selected:
            self.notice.set('受け入れ可能な候補はありません。「受け入れ済みも表示」で履歴を確認できます。'
                            if not self.pet_shop and not self.cats.get_children() and not self.show_accepted.get() else '候補を選んでください。')
            return
        key = selected[0]
        row = self.data['candidates'][key]
        personality = Personality.from_dict(row['personality'])
        from .core.cafe_traits import description
        from .core.cafe_preferences import feature_text
        values = [('特徴', feature_text(row.get('features', [])))] + description(row.get('trait')) + [('猫ID', key), ('提示日', f"{self.data.get('presented_days', {}).get(key, self.data['opened_day'])}日目"), ('体力', f'{core.config.max_stamina:g} / {core.config.max_stamina:g}'),
                  ('疲労 / ストレス', '0 / 0'), ('体調 / 出勤予定', '健康 / 休養'),
                  ('プレイヤー・お客への好感度', '0（未交流）')]
        values += [(f'好み：{kind.name}', f'{value:g}') for kind, value in zip(self.session.interaction_config.types, personality.type_preferences)]
        values += [(f'強さの好み：{name}', f'{value:g}') for name, value in zip(('穏やか', '普通', '活発'), personality.intensity_preferences)]
        values += [('飽きやすさ', f'{personality.boredom_decay:g}'), ('種類切り替えへの反応', f'{personality.switch_affinity:g}')]
        for value in values:
            self.details.insert('', 'end', values=value)
        if key in self.data['accepted']:
            self.notice.set(f'{self.action}済みです。上の能力は加入時の値です。現在の状態は「猫の詳細…」で確認できます。')
            return
        reason = ''
        try:
            require_preparation(core)
        except ValueError as exc:
            reason = str(exc)
        if self.session.pending:
            reason = '接客結果の保存を再試行してください。'
        from .core.cafe_housing import admission_reason
        if not reason:
            reason = admission_reason(core)
        if not reason and core.funds <= row['cost']:
            reason = f'{self.action}後に資金が残る必要があります。'
        self.notice.set(reason or f"{self.cost_label} {row['cost']:g} / {self.action}後の所持金 {core.funds - row['cost']:g}。出勤予定は加入後に設定できます。")
        self.receive_button.state(['disabled'] if reason else ['!disabled'])

    def receive(self):
        from tkinter import messagebox
        selected = self.cats.selection()
        if not selected:
            return
        core = self.session.core
        row = self.data['candidates'][selected[0]]
        if not messagebox.askyesno(self.title,
                f"{row['name']}を迎えますか？\n{self.cost_label}：{row['cost']:g}\n{self.action}後の所持金：{core.funds - row['cost']:g}\n加入時は休養予定です。", parent=self.window):
            return
        try:
            if self.pet_shop:
                self.session.purchase_cat(selected[0])
            else:
                self.session.recruit_cat(selected[0])
        except (ValueError, OSError) as exc:
            messagebox.showerror(f'{self.action}できません', str(exc), parent=self.window)
        self.on_changed()
        self.refresh()
