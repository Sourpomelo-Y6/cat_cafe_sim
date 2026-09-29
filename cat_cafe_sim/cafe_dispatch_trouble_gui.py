"""山あいの宿での家出に対応し、回答済みの記録も確認する。"""
from .core.cafe_dispatch_trouble import pending
from .core.cafe_management import is_over


class CafeDispatchTroubleWindow:
    def __init__(self, parent, session, event_id, on_changed):
        import tkinter as tk
        from tkinter import ttk
        self.session, self.event_id, self.on_changed = session, event_id, on_changed
        self.parent = parent
        self.window = tk.Toplevel(parent)
        self.window.title('山あいの宿・家出トラブル')
        self.window.geometry('620x400'); self.window.minsize(500, 340)
        self.window.transient(parent); self.window.grab_set()
        frame = ttk.Frame(self.window, padding=12); frame.pack(fill='both', expand=True)
        footer = ttk.Frame(frame); footer.pack(side='bottom', fill='x')
        self.search_button = ttk.Button(footer, text='捜索して連れ戻す', command=lambda: self.answer('search'))
        self.search_button.pack(side='left')
        self.wait_button = ttk.Button(footer, text='帰還を待つ（費用なし）', command=lambda: self.answer('wait'))
        self.wait_button.pack(side='left', padx=4)
        self.close_button = ttk.Button(footer, text='閉じる', command=self.close); self.close_button.pack(side='right')
        event = session.core.activities['events'][event_id]
        name = session.profiles.get(event['cat_id'], {}).get('name', event['cat_id'])
        ttk.Label(frame, text=f"{name} / {event['destination']['name']}").pack(anchor='w')
        self.description = tk.StringVar()
        ttk.Label(frame, textvariable=self.description, wraplength=460).pack(anchor='w', pady=10)
        self.notice = tk.StringVar()
        ttk.Label(frame, textvariable=self.notice, wraplength=460).pack(anchor='w')
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.window.bind('<Escape>', lambda event: self.close())
        self.refresh()

    def refresh(self):
        core = self.session.core
        event = core.activities['events'][self.event_id]; data = event['trouble']; rules = data['rules']
        self.description.set(f"{data['missing_day']}日目、派遣中に猫が驚いて宿の周囲へ出ていきました。派遣は中断し、報酬は0です。\n\n捜索費 {rules['search_cost']:g}を払うと、すぐに帰還確認へ進めます。支払い後の資金：{core.funds-rules['search_cost']:g}。\n費用なしで待つ場合は、家出した日から{rules['missing_days']}日後に帰還を確認します。帰還まで接客・交流・別の派遣には参加できません。")
        problem = 'ゲームオーバーです。' if is_over(core) else '接客結果の保存を再試行してください。' if self.session.pending else ''
        if data['status'] == 'resolved':
            choice = '捜索して連れ戻す' if data['choice'] == 'search' else '帰還を待つ'
            self.notice.set(f"{data['choice_day']}日目に回答：{choice} / 費用 {data['cost']:g}。回答は変更できません。帰還は派遣・帰還画面で確認します。")
        else:
            self.notice.set(problem or '対応を選ぶまで営業・日付の進行を停止します。人気の低下や子猫の引き渡し費用はありません。')
        enabled = pending(event) and not problem
        self.wait_button.state(['!disabled'] if enabled else ['disabled'])
        self.search_button.state(['!disabled'] if enabled and core.funds > rules['search_cost'] else ['disabled'])
        if enabled and core.funds <= rules['search_cost']:
            self.notice.set('捜索後に資金が残りません。費用なしの帰還待ちを選べます。')

    def answer(self, choice):
        from tkinter import messagebox
        data = self.session.core.activities['events'][self.event_id]['trouble']
        text = (f"捜索費 {data['rules']['search_cost']:g}を払い、帰還確認へ進みますか？" if choice == 'search' else
                f"費用なしで、家出した日から{data['rules']['missing_days']}日後の帰還を待ちますか？")
        if not messagebox.askyesno('派遣トラブルへの対応', text, parent=self.window):
            return
        try:
            self.session.resolve_dispatch_trouble(self.event_id, choice)
        except (ValueError, OSError) as exc:
            messagebox.showerror('対応できません', str(exc), parent=self.window)
        self.on_changed(); self.refresh()

    def close(self):
        self.window.destroy()
        if self.parent.winfo_exists() and self.parent.winfo_class() == 'Toplevel':
            self.parent.grab_set()
