"""選んだ猫の派遣先を比較し、既存の出発確認へ進む画面。"""
from .cafe_dispatch_comparison import comparison_rows


class CafeDispatchComparisonWindow:
    def __init__(self,parent,session,cat_id,on_select):
        import tkinter as tk
        from tkinter import ttk
        from .cafe_history import CafeHistoryWindow
        self.parent,self.session,self.cat_id,self.on_select=parent,session,cat_id,on_select
        self.window=tk.Toplevel(parent);self.window.title('猫に合う派遣先を比較')
        self.window.geometry('900x560');self.window.minsize(560,400)
        self.window.transient(parent);self.window.grab_set()
        frame=ttk.Frame(self.window,padding=12);frame.pack(fill='both',expand=True)
        footer=ttk.Frame(frame);footer.pack(side='bottom',fill='x',pady=(8,0))
        self.select_button=ttk.Button(footer,text='この派遣先で出発確認…',command=self.select)
        self.select_button.pack(side='left')
        self.refresh_button=ttk.Button(footer,text='再確認',command=self.refresh);self.refresh_button.pack(side='left',padx=6)
        self.close_button=ttk.Button(footer,text='閉じる',command=self.close);self.close_button.pack(side='right')
        self.title=tk.StringVar();ttk.Label(frame,textvariable=self.title).pack(anchor='w')
        ttk.Label(frame,text='報酬は派遣全体の見込みです。出来事の選択と家出トラブルで結果が変わります。',wraplength=520).pack(anchor='w')
        body=ttk.Panedwindow(frame,orient='vertical');body.pack(fill='both',expand=True)
        table_frame=ttk.Frame(body);detail_frame=ttk.Frame(body)
        body.add(table_frame,weight=1);body.add(detail_frame,weight=1)
        self.table=CafeHistoryWindow.table(table_frame,('派遣先','参加可否・理由','日数','報酬見込み','帰還ストレス','選択による報酬・負担'))
        for column in ('派遣先','参加可否・理由','選択による報酬・負担'):self.table.column(column,width=230,stretch=False)
        self.details=tk.Text(detail_frame,wrap='word',height=7,width=40,state='disabled')
        scroll=ttk.Scrollbar(detail_frame,orient='vertical',command=self.details.yview)
        self.details.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');self.details.pack(fill='both',expand=True)
        self.table.bind('<<TreeviewSelect>>',lambda event:self.show_detail())
        self.window.protocol('WM_DELETE_WINDOW',self.close);self.window.bind('<Escape>',lambda event:self.close())
        self.refresh()

    def refresh(self):
        selected=self.table.selection()
        self.rows={row['destination']['id']:row for row in comparison_rows(self.session,self.cat_id)}
        self.title.set(f"{self.session.profiles.get(self.cat_id,{}).get('name',self.cat_id)}の派遣先比較")
        self.table.delete(*self.table.get_children())
        for key,row in self.rows.items():
            self.table.insert('','end',iid=key,values=(row['destination']['name'],row['reason'] or '参加できます',
                row['destination']['days'],f"{row['reward']:g}",f"＋{row['return_stress']:g}",' / '.join(row['options']) or 'なし'))
        key=selected[0] if selected and selected[0] in self.rows else next(iter(self.rows))
        self.table.selection_set(key);self.show_detail()

    def show_detail(self):
        selected=self.table.selection();row=self.rows.get(selected[0]) if selected else None
        self.details.configure(state='normal');self.details.delete('1.0','end')
        if row:self.details.insert('1.0',row['detail'])
        self.details.configure(state='disabled');self.select_button.state(['!disabled'] if row and not row['reason'] else ['disabled'])

    def select(self):
        selected=self.table.selection()
        if not selected:return
        key=selected[0];self.refresh()
        if key not in self.rows or self.rows[key]['reason']:return
        self.close();self.on_select(key,self.cat_id)

    def close(self):
        self.window.destroy()
        if self.parent.winfo_exists():self.parent.grab_set()
