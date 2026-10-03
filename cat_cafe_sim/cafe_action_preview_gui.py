"""背景込みの猫画像を手動またはゲーム状態で切り替える試作。"""
from pathlib import Path


ASSET_PATH = Path(__file__).resolve().parent / 'assets' / 'cat_action_preview' / 'calico-actions-v1.png'
SCENES = (
    ('normal', '通常', 'マットの上で落ち着いて座っています。', 0, 0),
    ('play', '遊ぶ', 'ねこじゃらしに手を伸ばしています。', 1, 0),
    ('pet', '撫でられる', '頭を撫でられて、気持ちよさそうにしています。', 0, 1),
    ('sleep', '眠る', 'マットの上で丸くなって眠っています。', 1, 1),
)


class CatActionPreviewWindow:
    def __init__(self, parent, *, asset_path=ASSET_PATH, session_provider=None, registry=None):
        import tkinter as tk
        from tkinter import ttk

        self.window = tk.Toplevel(parent)
        self.session_provider = session_provider
        from .content_images import ImageRegistry
        self.registry = registry or ImageRegistry()
        self.registered_cache = {}
        self.target_id = None
        self.timer = None
        self.window.bind('<Destroy>', self._destroyed)
        self.window.title('猫の画像プレビュー')
        self.window.minsize(500, 410)
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='背景込みの猫画像・4場面', font=('', 14, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='見た目の確認用です。ボタンを押しても営業や猫の状態は変わりません。',
                  wraplength=500).pack(anchor='w', pady=(4, 8))
        self.images = {}
        self.scene = tk.StringVar(master=self.window, value='normal')
        controls = ttk.Frame(frame)
        controls.pack(fill='x', pady=(0, 8))
        self.buttons = {}
        self.auto = tk.BooleanVar(master=self.window, value=session_provider is not None)
        if session_provider is not None:
            self.cat_choice = tk.StringVar(master=self.window)
            self.cat_selector = ttk.Combobox(frame, textvariable=self.cat_choice, state='readonly', width=40)
            self.cat_selector.pack(fill='x', pady=(0, 6))
            self.cat_selector.bind('<<ComboboxSelected>>', self.select_cat)
            ttk.Checkbutton(frame, text='ゲーム状態に合わせて自動表示', variable=self.auto,
                            command=self.sync).pack(anchor='w', pady=(0, 6))
        self.game_status = tk.StringVar(master=self.window)
        ttk.Label(frame, textvariable=self.game_status, wraplength=500).pack(anchor='w', pady=(0, 6))
        for key, label, _, _, _ in SCENES:
            button = ttk.Radiobutton(controls, text=label, value=key, variable=self.scene,
                                     command=lambda key=key: self.show_scene(key))
            button.pack(side='left', padx=(0, 12))
            self.buttons[key] = button
        self.image_label = ttk.Label(frame, anchor='center')
        self.image_label.pack(fill='both', expand=True)
        self.caption = tk.StringVar(master=self.window)
        ttk.Label(frame, textvariable=self.caption, wraplength=500).pack(anchor='w', pady=8)
        ttk.Button(frame, text='閉じる', command=self.window.destroy).pack(anchor='e')

        try:
            # 比較用の原画から各場面を表示用に取り出す。原画ファイルは変更しない。
            sheet = tk.PhotoImage(master=self.window, file=str(asset_path))
            width, height = sheet.width() // 2, sheet.height() // 2
            scale = max(1, (width + 639) // 640, (height + 419) // 420)
            for key, _, _, column, row in SCENES:
                tile = tk.PhotoImage(master=self.window)
                left, top = column * width + 4, row * height + 4
                tile.tk.call(tile, 'copy', sheet, '-from', left, top,
                             (column + 1) * width - 4, (row + 1) * height - 4)
                self.images[key] = tile.subsample(scale, scale)
        except (tk.TclError, OSError):
            self.image_label.configure(text='試作画像を読み込めませんでした。\n画像ファイルをご確認ください。')
        self.show_scene('normal')
        if session_provider is not None:
            self._poll()

    def _destroyed(self, event):
        if event.widget == self.window and self.timer is not None:
            self.window.after_cancel(self.timer)
            self.timer = None

    def _poll(self):
        self.timer = None
        self.sync()
        self.timer = self.window.after(200, self._poll)

    def sync(self):
        if self.session_provider is None:
            return
        for button in self.buttons.values():
            button.state(['disabled'] if self.auto.get() else ['!disabled'])
        session = self.session_provider()
        self.cat_labels = {f"{session.profiles.get(key, {}).get('name', key)}（{key}）": key
                           for key in session.core.cats}
        self.cat_selector.configure(values=list(self.cat_labels))
        if self.target_id not in session.core.cats:
            self.target_id = 'playtest-mike' if 'playtest-mike' in session.core.cats else next(iter(session.core.cats), None)
        self.cat_choice.set(next((label for label, key in self.cat_labels.items() if key == self.target_id), ''))
        if not self.auto.get():
            self.show_scene(self.scene.get())
            self.game_status.set('手動プレビュー中（ゲーム状態は変更しません）')
            return
        from .cafe_action_presentation import current_scene
        view = current_scene(session, self.target_id)
        self.show_scene(view['scene'])
        self.game_status.set(f"{view['name']} / {view['room']} / {view['status']}")

    def select_cat(self, event=None):
        self.target_id = self.cat_labels.get(self.cat_choice.get())
        self.sync()

    def registered_image(self, key):
        import tkinter as tk
        from .content_images import load_display_image
        try:
            path = self.registry.image_path(self.target_id, key)
            if path is None:
                return None
            stamp = (str(path), path.stat().st_mtime_ns)
            if key not in self.registered_cache or self.registered_cache[key][0] != stamp:
                self.registered_cache[key] = (stamp, load_display_image(self.window, path))
            return self.registered_cache[key][1]
        except (OSError, ValueError, tk.TclError):
            return None

    def show_scene(self, key):
        scene = next((item for item in SCENES if item[0] == key), None)
        if scene is None:
            raise ValueError('未知の場面です。')
        self.scene.set(key)
        image = self.registered_image(key) if self.target_id is not None else None
        registered = image is not None
        image = image or self.images.get(key)
        if image is not None:
            self.image_label.configure(image=image, text='')
        self.caption.set(f"{scene[1]}：{scene[2]} / " + ('登録画像' if registered else '仮の三毛猫画像（未登録・読込失敗時の代替）'))


def main():
    """ゲームやセーブなしでも起動できるプレビュー。"""
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    preview = CatActionPreviewWindow(root)
    preview.window.protocol('WM_DELETE_WINDOW', root.destroy)
    preview.window.bind('<Destroy>', lambda event: root.destroy()
                        if event.widget == preview.window and root.winfo_exists() else None)
    root.mainloop()


if __name__ == '__main__':
    main()
