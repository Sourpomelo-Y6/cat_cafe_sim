"""猫の閲覧一覧の表示条件。保存データや活動状態は変更しない。"""


def visible_cat_ids(core, show_adopted=False):
    return [key for key in core.cats
            if show_adopted or core.activity(key) != 'adopted']


def adoption_toggle(parent, command, *, value=False, inline=False):
    import tkinter as tk
    from tkinter import ttk
    option = tk.BooleanVar(master=parent, value=value)
    button = ttk.Checkbutton(parent, text='譲渡済みも表示', variable=option, command=command)
    button.pack(side='right' if inline else 'top', anchor='w')
    return option
