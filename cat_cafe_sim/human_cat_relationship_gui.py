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
        self.persisted = False

    def save(self, path):
        if Path(path).resolve() == self.store.path.resolve():
            raise ValueError('交流ログは関係データとは別のファイルに保存してください。')
        super().save(path)

    def persist(self):
        result = self.store.apply(self.core)
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
        self.greeting_text.set(greeting_text(self.session.core))
        self.affinity_text.set(f"猫 {self.session.core.cat_id} → お客 {self.session.core.customer_id}　親しみ {r['affinity_before']:g} / 変化予定 {r['affinity_pending']:+g} / 終了時 {r['affinity_after']:g}\n"
                               + ('保存済み' if self.session.persisted else '結果未保存' if r['end_reason'] else '交流中：親しみはまだ保存されていません'))
        self.store_text.set(f'現在の保存先：{self.session.store.path}\n次回の保存先：{self.next_store.path}')
        self.finish_button.state(['disabled'] if r['end_reason'] else ['!disabled'])
        self.persist_button.state(['!disabled'] if r['end_reason'] and not self.session.persisted else ['disabled'])

    def persist_result(self):
        from tkinter import messagebox
        try:
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
        self.history.delete(*self.history.get_children())
        self.notice.set('関係を引き継いで交流を開始しました。')
        self.refresh()

    def close(self):
        if self.resolve_current():
            self.root.destroy()

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
