"""通常営業の画面構成。操作は営業・準備・結果に分け、ログを常設する。"""


def build(app):
    import tkinter as tk
    from tkinter import ttk
    root = app.root
    root.title('猫カフェ')
    root.geometry('1100x800')
    root.minsize(860, 660)
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('TFrame', background='#f4f3ee')
    style.configure('TLabel', background='#f4f3ee', foreground='#253d36')
    style.configure('TLabelframe', background='#f4f3ee')
    style.configure('TLabelframe.Label', background='#f4f3ee', foreground='#253d36')
    style.configure('TNotebook', background='#f4f3ee')
    style.map('TNotebook.Tab', background=[('selected','#ffffff')])
    style.configure('Cafe.TFrame', background='#f4f3ee')
    style.configure('Cafe.TLabel', background='#f4f3ee', foreground='#253d36', font=('', 10))
    style.configure('Cafe.Title.TLabel', background='#f4f3ee', foreground='#253d36', font=('', 18, 'bold'))
    style.configure('Cafe.TButton', padding=(10, 7))
    style.configure('Cafe.Primary.TButton', padding=(12, 7), font=('', 10, 'bold'))
    style.configure('Cafe.Treeview', rowheight=25)
    style.configure('Cafe.TNotebook.Tab', padding=(20, 8))
    shell = ttk.Frame(root, padding=14, style='Cafe.TFrame')
    shell.pack(fill='both', expand=True)
    shell.columnconfigure(0, weight=1)
    shell.rowconfigure(2, weight=3, minsize=250)
    shell.rowconfigure(4, weight=2, minsize=170)
    header = ttk.Frame(shell, style='Cafe.TFrame')
    header.grid(row=0, column=0, sticky='ew', pady=(0,10))
    app.phase = tk.StringVar()
    ttk.Label(header, textvariable=app.phase, style='Cafe.Title.TLabel').pack(side='left')
    app.status = tk.StringVar()
    ttk.Label(header, textvariable=app.status, style='Cafe.TLabel').pack(side='right')

    toolbar = ttk.Frame(shell, style='Cafe.TFrame')
    toolbar.grid(row=1, column=0, sticky='ew', pady=(0,10))
    app.automation_buttons = ttk.Frame(toolbar, style='Cafe.TFrame')
    app.automation_buttons.pack(side='left')
    app.run_button = ttk.Button(app.automation_buttons, text='営業を開始・再開', command=app.toggle, style='Cafe.Primary.TButton')
    app.run_button.grid(row=0, column=0)
    app.day_button = ttk.Button(app.automation_buttons, text='閉店結果・翌日へ', command=app.show_day_result, style='Cafe.Primary.TButton')
    app.day_button.grid(row=0, column=0)
    app.day_off_button = ttk.Button(app.automation_buttons, text='今日は休業する', command=app.take_day_off)
    app.day_off_button.grid(row=0, column=1, padx=6)
    app.file_controls = ttk.Frame(toolbar, style='Cafe.TFrame')
    app.file_controls.pack(side='right')
    for attr, text, command in (
        ('save_button','保存…',app.save_game), ('open_button','開く…',app.open_game),
        ('history_button','営業履歴…',app.show_history), ('new_game_button','新規ゲーム…',app.new_game),
    ):
        button = ttk.Button(app.file_controls, text=text, command=command)
        button.pack(side='left', padx=3)
        setattr(app, attr, button)
    app.pages = ttk.Notebook(shell, style='Cafe.TNotebook')
    app.pages.grid(row=2, column=0, sticky='nsew')
    app.business_page = ttk.Frame(app.pages, padding=10)
    app.preparation_page = ttk.Frame(app.pages, padding=16)
    app.results_page = ttk.Frame(app.pages, padding=16)
    for page, label in ((app.business_page,'営業'), (app.preparation_page,'準備・お店'), (app.results_page,'結果・記録')):
        app.pages.add(page, text=label)
    app.pages.bind('<<NotebookTabChanged>>', lambda event: app.page_changed())

    page = app.business_page
    page.columnconfigure(0, weight=1)
    page.rowconfigure(2, weight=1, minsize=120)
    app.controls = ttk.Frame(page)
    app.controls.grid(row=0, column=0, sticky='ew')
    for col in (0, 1):
        app.controls.columnconfigure(col, weight=1)
    app.customer = tk.StringVar()
    app.cat_choice = tk.StringVar(value=next(iter(app.cat_labels)))
    app.seat_choice = tk.StringVar(value=next(iter(app.session.free_seats), ''))
    for col, label in enumerate(('お客さん', '担当する猫', '席')):
        ttk.Label(app.controls, text=label).grid(row=0, column=col, sticky='w')
    app.queue = ttk.Combobox(app.controls, textvariable=app.customer, state='readonly', width=14)
    app.cat_selector = ttk.Combobox(app.controls, textvariable=app.cat_choice, state='readonly', width=20)
    app.seat_selector = ttk.Combobox(app.controls, textvariable=app.seat_choice, state='readonly', width=9)
    for col, widget in enumerate((app.queue, app.cat_selector, app.seat_selector)):
        widget.grid(row=1, column=col, sticky='ew', padx=(0,8))
    app.start_button = ttk.Button(app.controls, text='担当猫を割り当てる', command=app.assign)
    app.start_button.grid(row=1, column=3, padx=(0,8))
    app.assignment_button = ttk.Checkbutton(app.controls, text='自動割り当て', variable=app.auto_assign, command=app.refresh)
    app.assignment_button.grid(row=1, column=4)
    row = ttk.Frame(page)
    row.grid(row=1, column=0, sticky='ew', pady=(10,4))
    ttk.Label(row, text='猫の状態', font=('',10,'bold')).pack(side='left')
    app.cat_details_button = ttk.Button(row, text='選んだ猫の詳細・交流…', command=app.show_cat_details)
    app.cat_details_button.pack(side='right')
    app.compatibility_button = ttk.Button(row, text='お客との相性…', command=app.show_compatibility)
    app.compatibility_button.pack(side='right', padx=6)
    roster_frame = ttk.Frame(page)
    roster_frame.grid(row=2, column=0, sticky='nsew')
    roster_frame.columnconfigure(0, weight=1)
    roster_frame.rowconfigure(0, weight=1)
    app.roster = ttk.Treeview(roster_frame, columns=('cat','personality','stamina','affinity','status','fatigue','health','stress'),
                             displaycolumns=('cat','stamina','fatigue','stress','health','status','affinity','personality'),
                             show='headings', height=3, style='Cafe.Treeview')
    for key, title, width in (('cat','猫',155),('personality','個性',115),('stamina','体力',60),
                             ('affinity','選択客への親しみ',115),('status','予定・状態',90),('fatigue','疲労',60),('health','体調',100),('stress','ストレス',75)):
        app.roster.heading(key, text=title)
        app.roster.column(key, width=width, minwidth=70 if key=='stress' else 50)
    app.roster.grid(row=0, column=0, sticky='nsew')
    ttk.Scrollbar(roster_frame, orient='vertical', command=app.roster.yview).grid(row=0,column=1,sticky='ns')
    horizontal = ttk.Scrollbar(roster_frame, orient='horizontal', command=app.roster.xview)
    horizontal.grid(row=1,column=0,sticky='ew')
    app.roster.configure(xscrollcommand=horizontal.set, yscrollcommand=roster_frame.grid_slaves(row=0,column=1)[0].set)
    app.details = tk.StringVar()
    app.seat_details = ttk.Label(page, textvariable=app.details, wraplength=760)
    app.seat_details.grid(row=3, column=0, sticky='ew', pady=(6,0))
    app.roster.bind('<Double-1>', lambda event: app.show_cat_details())
    app.cat_selector.bind('<<ComboboxSelected>>', lambda event: app.refresh())
    app.queue.bind('<<ComboboxSelected>>', lambda event: app.refresh())

    def card(parent, column, title, hint, actions):
        parent.columnconfigure(column, weight=1, uniform='cards')
        box = ttk.LabelFrame(parent, text=title, padding=14)
        box.grid(row=1, column=column, sticky='nsew', padx=(0,12) if column==0 else 0, pady=10)
        if hint:
            ttk.Label(box, text=hint, wraplength=320).pack(anchor='w', pady=(0,10))
        for attr, label, command in actions:
            button = ttk.Button(box, text=label, command=command, style='Cafe.TButton')
            button.pack(fill='x', pady=3)
            setattr(app, attr, button)
        return box

    app.preparation_summary = tk.StringVar()
    ttk.Label(app.preparation_page, textvariable=app.preparation_summary, wraplength=760).grid(row=0,column=0,columnspan=2,sticky='w')
    card(app.preparation_page, 0, '猫の準備', '猫の体調を確認して、その日の担当を決めます。', (
        ('shift_button','出勤・休養を決める…',app.show_shifts),
        ('recruitment_button','保護猫を迎える…',app.show_recruitment),
        ('activity_button','派遣・帰還を確認する…',app.show_activities),
    ))
    card(app.preparation_page, 1, 'お店への投資', '費用と効果を確認してから購入できます。', (
        ('expansion_button','席を増やす…',app.show_expansion),
        ('equipment_button','休養スペースを購入する…',app.show_equipment),
    ))
    ttk.Label(app.preparation_page, text='準備ができたら上の「営業を開始・再開」へ。\n全員を休ませる日は「今日は休業する」を選べます。',wraplength=760).grid(row=2,column=0,columnspan=2,sticky='w')

    app.results_summary = tk.StringVar()
    ttk.Label(app.results_page, textvariable=app.results_summary, wraplength=760).grid(row=0,column=0,columnspan=2,sticky='w')
    goals = card(app.results_page, 0, '目標と営業の記録', '', (
        ('goal_button','人気目標・結果…',app.show_goal),
        ('patron_button','有力者目標・結果…',app.show_patron),
        ('bond_goal_button','猫との好感度目標・結果…',app.show_bond_goal),
    ))
    app.instructions = ttk.Label(goals, text='', wraplength=320)
    app.instructions.pack(anchor='w',pady=8)
    card(app.results_page, 1, 'イベントと店の状態', '確認が必要な出来事は、下の案内からも直接開けます。', (
        ('adoption_button','譲渡の申し出・設定…',app.show_adoption),
        ('management_button','家出・帰還・経営状態…',app.show_management),
    ))
    app.notice = tk.StringVar()
    notice = ttk.Frame(shell, style='Cafe.TFrame')
    notice.grid(row=3,column=0,sticky='ew',pady=8)
    notice.columnconfigure(0,weight=1)
    app.notice_label = ttk.Label(notice,textvariable=app.notice,wraplength=700,style='Cafe.TLabel')
    app.notice_label.grid(row=0,column=0,sticky='w')
    app.attention_button = ttk.Button(notice,text='確認する',command=app.open_attention)
    app.attention_button.grid(row=0,column=1,padx=(10,0))

    log = ttk.LabelFrame(shell, text='営業ログ', padding=6)
    log.grid(row=4,column=0,sticky='nsew')
    log.rowconfigure(0,weight=1)
    log.columnconfigure(0,weight=1)
    app.history = ttk.Treeview(log, columns=('tick','event'), show='headings', height=5)
    app.history.heading('tick',text='進行')
    app.history.heading('event',text='できごと')
    app.history.column('tick',width=60,stretch=False)
    app.history.column('event',width=900)
    app.history.grid(row=0,column=0,sticky='nsew')
    scroll = ttk.Scrollbar(log,orient='vertical',command=app.history.yview)
    scroll.grid(row=0,column=1,sticky='ns')
    app.history.configure(yscrollcommand=scroll.set)
    # 検証用の手動画面と共用する処理が参照する部品。通常画面には表示しない。
    app.actions_frame = ttk.Frame(shell)
    app.wait_button = ttk.Button(app.actions_frame)
    app.finish_button = ttk.Button(app.actions_frame)
    app.retry_button = ttk.Button(app.actions_frame, command=lambda: app.perform(app.session.persist))
    app.buttons = {}
    app.types = {t.name:t.id for t in app.session.interaction_config.types}
    app.target = tk.StringVar(value=next(iter(app.types)))
    menu = tk.Menu(root)
    files = tk.Menu(menu,tearoff=False)
    files.add_command(label='営業を保存…',command=app.save_game)
    files.add_command(label='営業ログを書き出す…',command=app.save_log)
    files.add_separator()
    files.add_command(label='終了',command=app.close)
    menu.add_cascade(label='ファイル',menu=files)
    root.configure(menu=menu)
    root.protocol('WM_DELETE_WINDOW', app.close)
