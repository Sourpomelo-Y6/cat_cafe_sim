"""営業開始前の出勤・休養設定画面。"""
from .cafe_health_text import health_text


class CafeShiftWindow:
    def __init__(self, parent, session, on_saved):
        import tkinter as tk
        from tkinter import ttk
        self.session = session
        self.on_saved = on_saved
        self.window = tk.Toplevel(parent)
        self.window.title('出勤・休養の設定')
        self.window.geometry('620x400')
        self.window.minsize(500, 300)
        self.window.transient(parent)
        self.window.grab_set()
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='営業開始前に設定してください。前日の設定を引き継ぎます。').pack(anchor='w')
        ttk.Label(frame, text='全員休養も可能です。その日は接客せず営業が進みます。').pack(anchor='w')
        body = ttk.Frame(frame)
        body.pack(fill='both', expand=True, pady=8)
        self.tree = ttk.Treeview(body, columns=('name', 'fatigue', 'shift', 'health'), show='headings', selectmode='browse')
        for key, label, width in (('name', '猫', 200), ('fatigue', '現在の疲労', 80), ('shift', '本日の予定', 80), ('health', '体調', 130)):
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
            self.tree.insert('', 'end', iid=row['cat_id'], values=(f"{row['name']}（{row['cat_id']}）",
                             f"{row['fatigue']:g}", '出勤' if row['working'] else '休養', health_text(row['health_status'],row['recovery_days_remaining'])))
        self.tree.selection_set(next(iter(session.core.cats)))
        controls = ttk.Frame(frame)
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

    def refresh_selection(self):
        selected=self.tree.selection()
        available=bool(selected) and all(self.session.core.cats[key].health_status=='healthy' for key in selected)
        self.work_button.state(['!disabled'] if available else ['disabled'])

    def set_selected(self, working):
        for key in self.tree.selection():
            if working:
                if self.session.core.cats[key].health_status != 'healthy':
                    return
                self.working.add(key)
            else:
                self.working.discard(key)
            self.tree.set(key, 'shift', '出勤' if working else '休養')

    def save(self):
        from tkinter import messagebox
        try:
            self.session.set_shifts(sorted(self.working))
        except (ValueError, OSError) as exc:
            messagebox.showerror('出勤・休養を設定できません', str(exc), parent=self.window)
            return
        self.on_saved()
        self.window.destroy()
