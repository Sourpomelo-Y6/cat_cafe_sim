"""猫との単独交流をボタンで試すTkinter画面。"""
import argparse
from dataclasses import replace
from pathlib import Path

from .core.human_cat_interaction import (
    ACTIONS, DEFAULT_CONFIG, HumanCatInteraction, InteractionConfig, save, verify,
)

from .core.human_cat_types import TypesConfig, TYPES_CONFIG
from .core.human_cat_special import SpecialConfig, SPECIAL_CONFIG, create_session

ACTION_NAMES = dict(zip(ACTIONS, ('素直に動かす', '相手に合わせる', '激しく動かす',
                                  'フェイントを入れる', '動きを止めて待つ', '動作を切り替える')))
REACTION_NAMES = dict(turn_away='そっぽを向く', listless='けだるそうにする', confused='戸惑う',
                      enthusiastic='熱心に応じる', favorable='好意的に応じる', neutral='普通に応じる')
ACTION_NAMES['connect'] = '心をつかむ'
REACTION_NAMES.update(open_up='心を開く', received='特別な働きかけを受け止める')
END_NAMES = dict(success='交流成功！', exhausted='体力がなくなり、交流終了', timeout='時間になり、交流終了')


class PlaySession:
    """画面の入力変換。状態遷移とログ形式は既存coreに委譲する。"""
    def __init__(self, config):
        self.base_config = config
        self.core = create_session(config)

    def restart(self, play, pet, stamina):
        config = replace(self.base_config, preferences=(float(play), float(pet)))
        # 検証に失敗した場合は現在の交流を保持する。
        core = create_session(config, stamina=float(stamina))
        self.core = core

    def restart_personality(self, personality, stamina):
        config = replace(self.base_config, personality=personality)
        core = create_session(config, stamina=float(stamina))
        self.core = core

    def act(self, action, **kwargs):
        return self.core.step(action, **kwargs)

    def save(self, path):
        save(self.core, path)
        verify(path)


def history_row(record):
    after = record['after']
    name = ACTION_NAMES[record['action']]
    if record.get('target_type'):
        name += ' → ' + record['target_type']
    row = (record['tick'] + 1, name, REACTION_NAMES[record['reaction']],
            f"{after['engagement']:.1f} ({record['engagement_delta']:+.1f})",
            f"{after['stamina']:.1f}")
    return row + ((f"{after['tension']:.1f}", f"+{sum(record['bonuses'].values()):g}") if 'bonuses' in record else ())


class InteractionWindow:
    def __init__(self, root, config):
        import tkinter as tk
        from tkinter import ttk
        self.root = root
        self.session = PlaySession(config)
        root.title('猫とのふれあい — 試遊')
        root.geometry('980x880')
        root.minsize(860, 800)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        frame = ttk.Frame(root, padding=18)
        frame.grid(sticky='nsew')
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(5, weight=1)
        ttk.Label(frame, text='猫とのふれあい', font=('', 20, 'bold')).grid(sticky='w')
        ttk.Label(frame, text='動作を選んで、猫の反応を見てみましょう。停止すると体力が少し回復します。').grid(sticky='w', pady=(4, 12))

        settings = ttk.LabelFrame(frame, text='次の交流の条件', padding=10)
        settings.grid(row=2, sticky='ew')
        self.play = tk.StringVar(value=str(config.preferences[0]))
        self.pet = tk.StringVar(value=str(config.preferences[1]))
        self.stamina = tk.StringVar(value=str(config.max_stamina))
        self.type_controls = None
        if isinstance(config, TypesConfig):
            from .human_cat_type_controls import TypeControls
            self.type_controls = TypeControls(self, settings, config)
            ttk.Label(settings, text='個性の変更は再開始時に適用されます。').grid(row=1,column=0,columnspan=5,sticky='w',pady=6)
        else:
            for column, (label, variable, maximum) in enumerate((
                    ('遊びの好み (0〜2)', self.play, 2), ('なでる好み (0〜2)', self.pet, 2),
                    ('開始体力', self.stamina, config.max_stamina))):
                cell = ttk.Frame(settings)
                cell.grid(row=0, column=column, padx=(0, 14), sticky='w')
                ttk.Label(cell, text=label).pack(anchor='w')
                ttk.Spinbox(cell, textvariable=variable, from_=0, to=maximum,
                            increment=.1 if column < 2 else 1, width=12).pack(anchor='w')
            ttk.Button(settings, text='この条件で再開始', command=self.restart).grid(row=0, column=3, padx=6)
            ttk.Label(settings, text='数値を変更しても、再開始するまでは現在の交流に影響しません。').grid(row=1, column=0, columnspan=4, sticky='w', pady=(8, 0))

        status = ttk.Frame(frame, padding=(0, 12))
        status.grid(row=3, sticky='ew')
        status.columnconfigure(1, weight=1)
        self.status = tk.StringVar()
        self.reaction = tk.StringVar()
        self.engagement_text = tk.StringVar()
        self.stamina_text = tk.StringVar()
        ttk.Label(status, textvariable=self.status).grid(row=0, column=0, columnspan=3, sticky='w')
        self.engagement_bar = ttk.Progressbar(status, maximum=config.target)
        self.stamina_bar = ttk.Progressbar(status, maximum=config.max_stamina)
        for row, label, bar, value in ((1, '関心', self.engagement_bar, self.engagement_text),
                                       (2, '体力', self.stamina_bar, self.stamina_text)):
            ttk.Label(status, text=label).grid(row=row, column=0, padx=(0, 8), pady=4)
            bar.grid(row=row, column=1, sticky='ew')
            ttk.Label(status, textvariable=value, width=17).grid(row=row, column=2, padx=8)
        ttk.Label(status, textvariable=self.reaction, font=('', 14, 'bold')).grid(row=3, column=0, columnspan=3, sticky='w', pady=(8, 0))

        self.special_status = tk.StringVar()
        self.tension_text = tk.StringVar()
        self.tension_bar = None
        if isinstance(config, SpecialConfig):
            ttk.Label(status, text='テンション').grid(row=4, column=0)
            self.tension_bar = ttk.Progressbar(status, maximum=config.target)
            self.tension_bar.grid(row=4, column=1, sticky='ew')
            ttk.Label(status, textvariable=self.tension_text).grid(row=4, column=2)
            ttk.Label(status, textvariable=self.special_status, wraplength=800).grid(row=5, column=0, columnspan=3, sticky='w')
            ttk.Label(status, text=f'猫は関心{config.optional_threshold:g}以上で、テンション{config.optional_threshold:g}以上・残り1ターン・体力{config.low_stamina:g}以下のいずれかなら心を開きます。', wraplength=800).grid(row=6, column=0, columnspan=3, sticky='w')

        actions = ttk.Frame(frame)
        actions.grid(row=4, sticky='ew', pady=(0, 12))
        self.buttons = {}
        for i, action in enumerate(ACTIONS + (('connect',) if isinstance(config, SpecialConfig) else ())):
            actions.columnconfigure(i % 3, weight=1)
            button = ttk.Button(actions, text=ACTION_NAMES[action], command=lambda a=action: self.act(a))
            button.grid(row=i // 3, column=i % 3, sticky='ew', padx=3, pady=3, ipady=5)
            self.buttons[action] = button

        history = ttk.Frame(frame)
        history.grid(row=5, sticky='nsew')
        history.columnconfigure(0, weight=1)
        history.rowconfigure(0, weight=1)
        columns = ('tick', 'action', 'reaction', 'engagement', 'stamina')
        labels = ('回', '人の動作', '猫の反応', '関心（増減）', '体力')
        widths = (40, 150, 150, 130, 60)
        if isinstance(config, SpecialConfig):
            columns += ('tension', 'bonus')
            labels += ('テンション', '獲得資金')
            widths += (80, 70)
        self.history = ttk.Treeview(history, columns=columns, show='headings', height=7)
        for name, label, width in zip(columns, labels, widths):
            self.history.heading(name, text=label)
            self.history.column(name, width=width, minwidth=40)
        self.history.grid(row=0, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(history, orient='vertical', command=self.history.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        self.history.configure(yscrollcommand=scrollbar.set)
        footer = ttk.Frame(frame)
        footer.grid(row=6, sticky='ew', pady=(12, 0))
        footer.columnconfigure(0, weight=1)
        self.notice = tk.StringVar(value='種類によって選べる動作が変わります。')
        ttk.Label(footer, textvariable=self.notice, wraplength=590).grid(row=0, column=0, sticky='w')
        ttk.Button(footer, text='ログを保存…', command=self.save_log).grid(row=0, column=1, padx=8)
        self.refresh()

    def refresh(self):
        s = self.session.core.observation()
        c = self.session.core.config
        mode = '遊び（ねこじゃらし）' if s['mode'] == 'play' else 'なでる'
        if self.type_controls is not None:
            mode = self.session.core.type_map[s['mode']].name
        self.status.set(f"現在：{mode}　残り {s['remaining_ticks']} ターン")
        self.engagement_text.set(f"{s['engagement']:.1f} / {c.target:g}")
        self.stamina_text.set(f"{s['stamina']:.1f} / {c.max_stamina:g}")
        self.engagement_bar['value'] = s['engagement']
        self.stamina_bar['value'] = s['stamina']
        if self.tension_bar is not None:
            self.tension_bar['value'] = s['tension']
            self.tension_text.set(f"{s['tension']:.1f} / {c.target:g}")
            self.special_status.set(f"次回予約：お客 {'心をつかむ' if s['connect_pending'] else 'なし'} ／ 猫 {'心を開く' if s['open_up_pending'] else 'なし'}\n獲得資金 {s['bonus_funds']:g} ／ 発動 お客{s['connect_count']}回・猫{s['open_up_count']}回・同時{s['simultaneous_count']}回")
        reaction = REACTION_NAMES.get(s['previous_reaction'], '猫がこちらを見ています')
        if s.get('previous_cat_action') in ('open_up', 'received'):
            reaction = REACTION_NAMES[s['previous_cat_action']]
        self.reaction.set(f"{END_NAMES[s['end_reason']]} — {reaction}" if s['end_reason'] else reaction)
        valid = self.session.core.valid_actions()
        for action, button in self.buttons.items():
            enabled = action in valid
            if action == 'switch' and self.type_controls is not None:
                enabled = enabled and self.type_controls.target_id() != s['mode']
            button.state(['!disabled'] if enabled else ['disabled'])

    def act(self, action):
        from tkinter import messagebox
        try:
            kwargs = {'target_type': self.type_controls.target_id()} if action == 'switch' and self.type_controls is not None else {}
            record = self.session.act(action, **kwargs)
        except ValueError as error:
            messagebox.showerror('動作を選べません', str(error), parent=self.root)
            return
        values = list(history_row(record))
        if self.type_controls is not None:
            types = self.session.core.type_map
            values[1] = ('変更 → ' + types[record['target_type']].name if action == 'switch'
                         else values[1] + '（' + types[record['before']['mode']].name + '）')
        item = self.history.insert('', 'end', values=values)
        self.history.see(item)
        self.notice.set('交流終了後もログを保存できます。再開始すると履歴は消えます。')
        self.refresh()

    def restart(self):
        from tkinter import messagebox
        try:
            if self.type_controls is not None:
                self.session.restart_personality(self.type_controls.pending, self.stamina.get())
            else:
                self.session.restart(self.play.get(), self.pet.get(), self.stamina.get())
        except (ValueError, OverflowError):
            messagebox.showerror('条件を確認してください',
                                 f'好みは0〜2、開始体力は0より大きく{self.session.base_config.max_stamina:g}以下の有限な数値を入力してください。', parent=self.root)
            return
        self.history.delete(*self.history.get_children())
        self.notice.set('新しい条件で交流を開始しました。')
        self.refresh()

    def save_log(self):
        from tkinter import filedialog, messagebox
        path = filedialog.asksaveasfilename(parent=self.root, title='交流ログを保存',
                                          defaultextension='.json', initialfile='human_cat_play.json',
                                          filetypes=[('JSONログ', '*.json')])
        if not path:
            return
        try:
            self.session.save(path)
        except (OSError, ValueError) as error:
            messagebox.showerror('保存できませんでした', str(error), parent=self.root)
            return
        self.notice.set(f'ログを保存しました：{path}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=None)
    parser.add_argument('--rules', type=int, choices=(1, 2, 3), default=3)
    args = parser.parse_args(argv)
    try:
        config = (TypesConfig.load(args.config or TYPES_CONFIG) if args.rules == 3 else SpecialConfig.load(args.config or SPECIAL_CONFIG) if args.rules == 2
                  else InteractionConfig.load(args.config or DEFAULT_CONFIG))
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.error(str(error))
    try:
        import tkinter as tk
    except ModuleNotFoundError:
        parser.error('Tkinterが必要です。PythonのTkサポートを導入してください。')
    try:
        root = tk.Tk()
    except tk.TclError as error:
        parser.error(f'画面を開けません。デスクトップ環境で実行してください: {error}')
    InteractionWindow(root, config)
    root.mainloop()


if __name__ == '__main__':
    main()
