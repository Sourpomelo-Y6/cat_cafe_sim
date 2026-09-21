"""譲渡イベントの設定、申し出への回答、確定済み履歴の閲覧。"""
from .core.cafe_adoption import enabled, waiting
from .core.cafe_management import is_over


class CafeAdoptionWindow:
    def __init__(self, parent, session, on_changed):
        import tkinter as tk
        from tkinter import ttk
        from .cafe_history import CafeHistoryWindow
        self.session, self.on_changed = session, on_changed
        self.window = tk.Toplevel(parent)
        self.window.title('譲渡の設定・申し出')
        self.window.geometry('800x500')
        self.window.minsize(500, 400)
        self.window.transient(parent)
        self.window.grab_set()
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        footer = ttk.Frame(frame)
        footer.pack(side='bottom', fill='x')
        self.accept_button = ttk.Button(footer, text='譲渡する', command=lambda:self.resolve('accept'))
        self.accept_button.pack(side='left')
        self.decline_button = ttk.Button(footer, text='見送る', command=lambda:self.resolve('decline'))
        self.decline_button.pack(side='left', padx=4)
        self.close_button = ttk.Button(footer, text='閉じる', command=self.close)
        self.close_button.pack(side='right')
        self.option = tk.BooleanVar()
        self.toggle = ttk.Checkbutton(frame, text='譲渡イベントを有効にする（準備中に変更）',
                                      variable=self.option, command=self.configure)
        self.toggle.pack(anchor='w')
        ttk.Label(frame, text='接客終了時：猫からお客への親しみ80以上、かつプレイヤーへの好感度より高いと申し出が発生します。同じ猫は1日1回まで。',
                  wraplength=460).pack(anchor='w', pady=4)
        self.notice = tk.StringVar()
        ttk.Label(frame, textvariable=self.notice, wraplength=460).pack(anchor='w')
        self.details = tk.StringVar()
        ttk.Label(frame, textvariable=self.details, wraplength=460).pack(anchor='w', pady=4)
        self.events = CafeHistoryWindow.table(frame, ('発生日','猫','お客','お客への親しみ','プレイヤー好感度','結果'))
        self.events.bind('<<TreeviewSelect>>', lambda event:self.selection())
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.window.bind('<Escape>', lambda event:self.close())
        self.refresh()

    def close(self):
        parent = self.window.master
        self.window.destroy()
        if parent.winfo_exists():
            parent.grab_set()
        self.on_changed()

    def refresh(self):
        from .core.cafe_activities import waiting_events
        from .core.cafe_player import active
        core = self.session.core
        selected = self.events.selection()
        self.option.set(enabled(core))
        can_configure = core.can_set_shifts and not is_over(core) and not self.session.pending and not waiting_events(core) and not active(core)
        self.toggle.state(['!disabled'] if can_configure else ['disabled'])
        self.events.delete(*self.events.get_children())
        if core.adoption:
            for key, event in core.adoption['events'].items():
                label = '回答待ち' if event['status']=='waiting' else '譲渡成立' if event['choice']=='accept' else '見送り'
                self.events.insert('', 'end', iid=key, values=(event['day'],
                    self.session.profiles.get(event['cat_id'], {}).get('name', event['cat_id']),
                    event['customer_id'], f"{event['guest_affinity']:g}", f"{event['player_affinity']:g}", label))
        pending = waiting(core)
        if selected and self.events.exists(selected[0]):
            self.events.selection_set(selected[0])
        elif pending:
            self.events.selection_set(pending[0]['id'])
        elif self.events.get_children():
            self.events.selection_set(self.events.get_children()[-1])
        self.notice.set('接客結果の保存が未完了です。営業画面で保存を再試行してください。' if self.session.pending else
                        '申し出への回答待ちです。すべて回答するまで営業は停止します。' if pending else
                        '発生はONです。次の接客終了時から条件を判定します。' if enabled(core) else
                        '発生はOFFです。過去の申し出の履歴は保持します。')
        self.selection()

    def selection(self):
        selected = self.events.selection()
        event = self.session.core.adoption['events'][selected[0]] if selected and self.session.core.adoption else None
        can_resolve = event and event['status']=='waiting' and not self.session.pending and not is_over(self.session.core)
        for button in (self.accept_button, self.decline_button):
            button.state(['!disabled'] if can_resolve else ['disabled'])
        self.details.set(f"対象：{event['cat_id']} → {event['customer_id']}。譲渡後も詳細と関係の記録は残ります。" if event else
                         '申し出はありません。プレイヤー好感度が相手以上なら発生を予防できます。')

    def configure(self):
        self.perform(lambda:self.session.configure_adoption(self.option.get()))

    def resolve(self, choice):
        from tkinter import messagebox
        selected = self.events.selection()
        if not selected:
            return
        if choice == 'accept':
            event = self.session.core.adoption['events'][selected[0]]
            name = self.session.profiles.get(event['cat_id'], {}).get('name', event['cat_id'])
            if not messagebox.askyesno('猫の譲渡', f"{name}を{event['customer_id']}へ譲渡しますか？\nこの営業では店内接客・派遣・プレイヤー交流に戻せません。", parent=self.window):
                return
        self.perform(lambda:self.session.resolve_adoption(selected[0], choice))

    def perform(self, action):
        from tkinter import messagebox
        try:
            action()
        except (ValueError, OSError) as exc:
            messagebox.showerror('譲渡イベントを処理できません', str(exc), parent=self.window)
        self.on_changed()
        self.refresh()
