"""親しみの確定・再会を扱う版4の画面。ログ保存は関係保存と別。"""
from dataclasses import replace
from pathlib import Path

from .human_cat_gui import InteractionWindow, PlaySession
from .storage.relationships import RelationshipStore
from .relationship_presentation import greeting_text, relationship_change_text


class RelationshipPlaySession(PlaySession):
    def __init__(self, config, store, cat_id='cat-1', customer_id='guest-1', stamina=None):
        self.base_config = config
        self.store = store
        self.core = store.begin(config,cat_id,customer_id,stamina=stamina)
        self.profile = store.cat_profile(cat_id)
        self.cat_name = self.profile['name'] if self.profile else cat_id
        self.persisted = False

    def save(self, path):
        if Path(path).resolve() == self.store.path.resolve():
            raise ValueError('交流ログは関係データとは別のファイルに保存してください。')
        super().save(path)

    def persist(self):
        result = self.store.apply(self.core, cat_name=self.cat_name)
        self.profile = self.store.cat_profile(self.core.cat_id)
        self.persisted = True
        return result

    def prepare_reunion(self, personality, stamina, cat_id, customer_id, store=None):
        return RelationshipPlaySession(replace(self.base_config,personality=personality),
                                       store or self.store,cat_id,customer_id,float(stamina))


def result_text(core, persisted):
    r=core.result()
    from .human_cat_gui import END_NAMES
    parts=r['affinity_breakdown']
    return (f"{END_NAMES[r['end_reason']]}\n猫：{r['cat_id']}　お客：{r['customer_id']}\n"
            f"親しみ {r['affinity_before']:g} → {r['affinity_after']:g}（{r['affinity_delta']:+g}）\n"
            f"{relationship_change_text(r['affinity_before'], r['affinity_after'])}\n"
            f"内訳：通常 {parts['normal']:+g} / 心をつかむ {parts['connect']:+g} / 心を開く {parts['open_up']:+g}\n"
            f"同時発動 {parts['simultaneous']:+g} / 消耗 {parts['exhaustion']:+g}\n"
            f"範囲制限による未反映 {r['affinity_unapplied']:+g}\n"
            f"獲得資金 {r['bonus_funds']:g}　使用 {r['ticks']} ターン\n"
            f"体力消費 {r['stamina_spent']:g} / 回復 {r['stamina_recovered']:g} / 残り {r['stamina']:g}\n"
            f"発動：お客 {r['connect_count']} / 猫 {r['open_up_count']} / 同時 {r['simultaneous_count']}\n"
            + ('関係データへ保存済み' if persisted else '未保存：保存を再試行してください'))


class RelationshipWindow(InteractionWindow):
    def __init__(self, root, config, path):
        import tkinter as tk
        from tkinter import ttk
        super().__init__(root,config)
        self.session = RelationshipPlaySession(config,RelationshipStore(path))
        self.next_store = self.session.store
        self.cat_id = tk.StringVar(value=self.session.core.cat_id)
        self.customer_id = tk.StringVar(value=self.session.core.customer_id)
        ids=ttk.Frame(self.settings_frame)
        ids.grid(row=4,column=0,columnspan=5,sticky='ew',pady=6)
        ttk.Label(ids,text='次の猫ID').pack(side='left')
        ttk.Entry(ids,textvariable=self.cat_id,width=14).pack(side='left',padx=4)
        ttk.Label(ids,text='次のお客ID').pack(side='left')
        ttk.Entry(ids,textvariable=self.customer_id,width=14).pack(side='left',padx=4)
        ttk.Button(ids,text='保存データを選ぶ…',command=self.choose_store).pack(side='left',padx=4)
        ttk.Button(ids,text='新しい保存データ…',command=self.new_store).pack(side='left')
        ttk.Button(self.settings_frame,text='関係一覧から再会…',command=self.show_relationships).grid(row=6,column=0,columnspan=5,sticky='w',pady=4)
        profile_frame = ttk.Frame(self.settings_frame)
        profile_frame.grid(row=7,column=0,columnspan=5,sticky='w',pady=4)
        ttk.Label(profile_frame,text='現在の猫の名前').pack(side='left')
        self.cat_name = tk.StringVar(value=self.session.cat_name)
        self.name_entry = ttk.Entry(profile_frame,textvariable=self.cat_name,width=20)
        self.name_entry.pack(side='left',padx=4)
        self.register_button = ttk.Button(profile_frame,text='現在の名前・個性で猫を登録',command=self.register_cat)
        self.register_button.pack(side='left')
        ttk.Label(self.settings_frame,text='未登録の猫は登録ボタンまたは結果保存で登録します。上の個性選択は未登録の猫の再開始に使います。',wraplength=850).grid(row=8,column=0,columnspan=5,sticky='w')
        self.greeting_text=tk.StringVar()
        ttk.Label(self.status_frame,textvariable=self.greeting_text,wraplength=850).grid(row=8,column=0,columnspan=3,sticky='w',pady=6)
        self.affinity_text=tk.StringVar()
        self.store_text=tk.StringVar()
        ttk.Label(self.status_frame,textvariable=self.affinity_text,wraplength=850).grid(row=7,column=0,columnspan=3,sticky='w',pady=6)
        ttk.Label(self.settings_frame,textvariable=self.store_text,wraplength=850).grid(row=5,column=0,columnspan=5,sticky='w')
        self.finish_button=ttk.Button(self.footer,text='切り上げる',command=self.finish)
        self.finish_button.grid(row=1,column=0,sticky='w',pady=6)
        self.persist_button=ttk.Button(self.footer,text='結果保存を再試行',command=self.persist_result)
        self.persist_button.grid(row=1,column=1)
        ttk.Button(self.footer,text='終了結果を見る',command=self.show_result).grid(row=2,column=1)
        root.geometry('1020x1000')
        root.protocol('WM_DELETE_WINDOW',self.close)
        self.refresh()

    def refresh(self):
        super().refresh()
        if not hasattr(self,'affinity_text'):
            return
        r=self.session.core.summary()
        registered = bool(self.session.profile)
        self.name_entry.state(['disabled'] if registered else ['!disabled'])
        self.register_button.state(['disabled'] if registered else ['!disabled'])
        self.greeting_text.set(f'{self.session.cat_name}（{self.session.core.cat_id}） · ' + ('登録済みの個性' if registered else '個性未登録') + '\n' + greeting_text(self.session.core))
        self.affinity_text.set(f"猫 {self.session.core.cat_id} → お客 {self.session.core.customer_id}　親しみ {r['affinity_before']:g} / 変化予定 {r['affinity_pending']:+g} / 終了時 {r['affinity_after']:g}\n"
                               + ('保存済み' if self.session.persisted else '結果未保存' if r['end_reason'] else '交流中：親しみはまだ保存されていません'))
        self.store_text.set(f'現在の保存先：{self.session.store.path}\n次回の保存先：{self.next_store.path}')
        self.finish_button.state(['disabled'] if r['end_reason'] else ['!disabled'])
        self.persist_button.state(['!disabled'] if r['end_reason'] and not self.session.persisted else ['disabled'])

    def persist_result(self):
        from tkinter import messagebox
        try:
            if not self.session.profile:
                from .core.human_cat_relationship import identity
                self.session.cat_name = identity(self.cat_name.get())
            self.session.persist()
        except (OSError,ValueError,TypeError,KeyError) as error:
            messagebox.showerror('結果を保存できませんでした',str(error),parent=self.root)
            self.refresh()
            return False
        self.refresh()
        return True

    def act(self, action):
        was_ended=bool(self.session.core.state['end_reason'])
        super().act(action)
        if not was_ended and self.session.core.state['end_reason']:
            self.persist_result()
            self.show_result()

    def finish(self):
        self.session.core.finish()
        self.persist_result()
        self.show_result()

    def show_result(self):
        import tkinter as tk
        from tkinter import ttk
        if not self.session.core.state['end_reason']:
            return
        dialog=tk.Toplevel(self.root)
        dialog.title('交流の成果')
        ttk.Label(dialog,text=result_text(self.session.core,self.session.persisted),padding=20,justify='left').pack()
        ttk.Button(dialog,text='閉じる',command=dialog.destroy).pack(pady=8)

    def resolve_current(self):
        """再会・終了前に、保存／破棄／戻るを明示的に選ぶ。"""
        import tkinter as tk
        from tkinter import ttk
        if self.session.persisted:
            return True
        if not self.session.core.records and not self.session.core.state['end_reason']:
            return True
        answer={'value':'cancel'}
        dialog=tk.Toplevel(self.root);dialog.title('現在の交流の扱い')
        dialog.transient(self.root);dialog.grab_set()
        ttk.Label(dialog,text='現在の交流をどう扱いますか？',padding=16).pack()
        def decide(value):
            answer['value']=value;dialog.destroy()
        for label,value in (('切り上げて結果を保存','save'),('試遊・未保存結果を破棄','discard'),('戻る','cancel')):
            ttk.Button(dialog,text=label,command=lambda v=value:decide(v)).pack(fill='x',padx=16,pady=5)
        self.root.wait_window(dialog)
        if answer['value']=='save':
            self.session.core.finish()
            return self.persist_result()
        return answer['value']=='discard'

    def restart(self):
        from tkinter import messagebox
        # Validate staged inputs first, but refresh the snapshot again after saving current outcome.
        try:
            self.session.prepare_reunion(self.type_controls.pending,self.stamina.get(),self.cat_id.get(),self.customer_id.get(),self.next_store)
        except (OSError,ValueError,TypeError,KeyError) as error:
            messagebox.showerror('次回の条件を確認してください',str(error),parent=self.root)
            return
        if not self.resolve_current():
            return
        try:
            next_session=self.session.prepare_reunion(self.type_controls.pending,self.stamina.get(),self.cat_id.get(),self.customer_id.get(),self.next_store)
        except (OSError,ValueError,TypeError,KeyError) as error:
            messagebox.showerror('再会を開始できません',str(error),parent=self.root)
            return
        self.session=next_session
        self.cat_name.set(self.session.cat_name)
        self.history.delete(*self.history.get_children())
        self.notice.set('関係を引き継いで交流を開始しました。')
        self.refresh()

    def close(self):
        if self.resolve_current():
            self.root.destroy()

    def register_cat(self):
        from tkinter import messagebox
        try:
            profile = self.session.store.register_cat(self.session.core.cat_id, self.cat_name.get(),
                                                      self.session.core.config.personality)
        except (OSError, ValueError, TypeError, KeyError) as error:
            messagebox.showerror('猫を登録できませんでした', str(error), parent=self.root)
            return
        self.session.profile = profile
        self.session.cat_name = profile['name']
        self.refresh()

    def show_relationships(self):
        browser = RelationshipBrowser(self)
        return browser

    def choose_store(self):
        from tkinter import filedialog,messagebox
        path=filedialog.askopenfilename(parent=self.root,title='次回の関係保存データ',filetypes=[('JSON','*.json')])
        if path:
            try:
                store=RelationshipStore(path)
                store.snapshot(self.cat_id.get(),self.customer_id.get())
            except (OSError,ValueError,TypeError,KeyError) as error:
                messagebox.showerror('保存データを読めません',str(error),parent=self.root)
                return
            self.next_store=store
            self.refresh()

    def new_store(self):
        from tkinter import filedialog,messagebox
        path=filedialog.asksaveasfilename(parent=self.root,title='新しい保存データ（未使用の名前）',defaultextension='.json')
        if path:
            if Path(path).exists():
                messagebox.showerror('別の名前を指定してください','新規作成では既存ファイルを上書きしません。',parent=self.root)
                return
            self.next_store=RelationshipStore(path)
            self.refresh()


class RelationshipBrowser:
    """次回の保存先を固定して閲覧し、既存の保存／破棄確認を経て再会する。"""
    def __init__(self, owner):
        import tkinter as tk
        from tkinter import ttk
        self.owner = owner
        self.store = owner.next_store
        self.dialog = tk.Toplevel(owner.root)
        self.dialog.title('猫とお客の関係一覧')
        self.dialog.geometry('860x420')
        self.dialog.transient(owner.root)
        ttk.Label(self.dialog, text=f'保存先：{self.store.path}', wraplength=820, padding=8).pack(anchor='w')
        ttk.Label(self.dialog, text='登録済みの猫は保存した個性を使います。未登録の猫の個性・開始体力はメイン画面で指定します。', padding=8).pack(anchor='w')
        frame = ttk.Frame(self.dialog)
        frame.pack(fill='both', expand=True, padx=8)
        columns = ('name', 'cat', 'customer', 'affinity', 'stage', 'change')
        self.tree = ttk.Treeview(frame, columns=columns, show='headings', selectmode='browse')
        for column, label, width in zip(columns, ('猫の名前', '猫ID', 'お客ID', '親しみ', '関係の目安', '直近の保存済み交流'), (120,100,100,60,150,190)):
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, minwidth=60)
        scrollbar = ttk.Scrollbar(frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        self.message = tk.StringVar()
        ttk.Label(self.dialog, textvariable=self.message, padding=8).pack(anchor='w')
        buttons = ttk.Frame(self.dialog)
        buttons.pack(fill='x', padx=8, pady=8)
        self.reunion_button = ttk.Button(buttons, text='選んだ相手と再会', command=self.reunite)
        self.reunion_button.pack(side='left')
        ttk.Button(buttons, text='一覧を更新', command=self.reload).pack(side='left', padx=8)
        ttk.Button(buttons, text='閉じる', command=self.dialog.destroy).pack(side='right')
        self.tree.bind('<<TreeviewSelect>>', self.selection_changed)
        self.reload()

    def selection_changed(self, event=None):
        self.reunion_button.state(['!disabled'] if self.tree.selection() else ['disabled'])

    def reload(self):
        from tkinter import messagebox
        from .relationship_presentation import STAGES, stage_index
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        self.selection_changed()
        try:
            rows = self.store.list_relationships()
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.message.set('一覧を読み込めませんでした。保存先を確認して再度更新してください。')
            messagebox.showerror('関係一覧を読めません', str(error), parent=self.dialog)
            return
        for index, row in enumerate(rows):
            result = row['latest_result']
            change = (f"{result['affinity_before']:g} → {result['affinity_after']:g}（{result['affinity_delta']:+g}）"
                      if result else '記録なし')
            item = str(index)
            self.rows[item] = row
            self.tree.insert('', 'end', iid=item, values=(row['cat_name'], row['cat_id'], row['customer_id'],
                             f"{row['affinity']:g}", STAGES[stage_index(row['affinity'])], change))
        self.message.set(f'{len(rows)}組の関係があります。' if rows else '保存済みの関係はありません。交流結果を保存すると表示されます。')

    def reunite(self):
        selected = self.tree.selection()
        if not selected:
            return
        row = self.rows[selected[0]]
        owner = self.owner
        previous = (owner.cat_id.get(), owner.customer_id.get(), owner.next_store)
        old_session = owner.session
        owner.cat_id.set(row['cat_id'])
        owner.customer_id.set(row['customer_id'])
        owner.next_store = self.store
        owner.restart()
        if owner.session is not old_session:
            self.dialog.destroy()
        else:
            owner.cat_id.set(previous[0])
            owner.customer_id.set(previous[1])
            owner.next_store = previous[2]
            owner.refresh()
