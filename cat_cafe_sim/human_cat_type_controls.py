"""版3試遊画面の種類選択と次回個性編集。"""
from .core.human_cat_types import Personality, TYPE_IDS, STRENGTHS, load_presets

GROUP_NAMES = dict(play='遊ぶ', contact='触れ合う', quiet='静かに過ごす')


class TypeControls:
    def __init__(self, app, parent, config):
        import tkinter as tk
        from tkinter import ttk
        self.app = app
        self.config = config
        self.pending = config.personality
        self.presets = load_presets()
        self.preset = tk.StringVar(value='設定ファイルの個性')
        self.selector = ttk.Combobox(parent, textvariable=self.preset, values=tuple(self.presets), state='readonly', width=24)
        self.selector.grid(row=0, column=0, padx=4)
        self.selector.bind('<<ComboboxSelected>>', self.select_preset)
        ttk.Button(parent, text='個性の詳細…', command=self.edit).grid(row=0, column=1, padx=4)
        ttk.Label(parent, text='開始体力').grid(row=0, column=2)
        ttk.Spinbox(parent, textvariable=app.stamina, from_=1, to=config.max_stamina, width=8).grid(row=0, column=3)
        ttk.Button(parent, text='この条件で再開始', command=app.restart).grid(row=0, column=4, padx=4)
        self.labels = {f'{GROUP_NAMES[t.group]} ／ {t.name}': t.id for t in config.types}
        self.target = tk.StringVar(value=next(iter(self.labels)))
        ttk.Label(parent, text='変更先（選択後、動作を切り替えるボタンで実行）').grid(row=2, column=0, columnspan=5, sticky='w')
        combo = ttk.Combobox(parent, textvariable=self.target, values=tuple(self.labels), state='readonly', width=34)
        combo.grid(row=3, column=0, columnspan=3, sticky='w')
        combo.bind('<<ComboboxSelected>>', lambda _: app.refresh())

    def select_preset(self, _=None):
        self.pending = self.presets[self.preset.get()]

    def target_id(self):
        return self.labels.get(self.target.get())

    def accept_details(self, values):
        # Validation completes before replacing the next-session settings.
        personality = Personality.from_dict(values)
        self.pending = personality
        self.preset.set('カスタム')

    def edit(self):
        import tkinter as tk
        from tkinter import ttk, messagebox
        dialog = tk.Toplevel(self.app.root)
        dialog.title('次の交流の個性')
        dialog.transient(self.app.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill='both', expand=True)
        values = self.pending.to_dict()
        fields = {}
        labels = {t.id:t.name for t in self.config.types}
        rows = [('type_preferences', k, labels[k], 0, 2) for k in TYPE_IDS]
        rows += [('intensity_preferences', k, name, 0, 2) for k,name in zip(STRENGTHS, ('穏やかな動き', '標準の動き', '活発な動き'))]
        rows += [(None,'boredom_decay','飽きやすさ',0,1),(None,'switch_affinity','切り替えの好み',-.5,.5)]
        for row,(section,key,label,minimum,maximum) in enumerate(rows):
            ttk.Label(frame,text=f'{label} ({minimum}〜{maximum})').grid(row=row,column=0,sticky='w',padx=4,pady=2)
            variable = tk.StringVar(value=str(values[section][key] if section else values[key]))
            fields[(section,key)] = variable
            ttk.Spinbox(frame,textvariable=variable,from_=minimum,to=maximum,increment=.1,width=10).grid(row=row,column=1)
        def accept():
            try:
                edited = dict(type_preferences={},intensity_preferences={})
                for (section,key),variable in fields.items():
                    if section:
                        edited[section][key] = float(variable.get())
                    else:
                        edited[key] = float(variable.get())
                self.accept_details(edited)
            except ValueError:
                messagebox.showerror('個性の値を確認してください','各欄の範囲内の有限な数値を入力してください。',parent=dialog)
                return
            dialog.destroy()
        ttk.Label(frame,text='保存しても、再開始するまでは現在の猫に影響しません。').grid(row=len(rows),column=0,columnspan=2,pady=8)
        ttk.Button(frame,text='次の交流に使う',command=accept).grid(row=len(rows)+1,column=0)
        ttk.Button(frame,text='キャンセル',command=dialog.destroy).grid(row=len(rows)+1,column=1)
