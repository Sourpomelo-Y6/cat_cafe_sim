"""背景込みの猫画像を手動で切り替える、ゲーム状態を変更しない試作。"""
from pathlib import Path


ASSET_PATH = Path(__file__).resolve().parent / 'assets' / 'cat_action_preview' / 'calico-actions-v1.png'
SCENES = (
    ('normal', '通常', 'マットの上で落ち着いて座っています。', 0, 0),
    ('play', '遊ぶ', 'ねこじゃらしに手を伸ばしています。', 1, 0),
    ('pet', '撫でられる', '頭を撫でられて、気持ちよさそうにしています。', 0, 1),
    ('sleep', '眠る', 'マットの上で丸くなって眠っています。', 1, 1),
)


class CatActionPreviewWindow:
    def __init__(self, parent, *, asset_path=ASSET_PATH):
        import tkinter as tk
        from tkinter import ttk

        self.window = tk.Toplevel(parent)
        self.window.title('猫の画像プレビュー — 三毛猫の試作')
        self.window.minsize(500, 410)
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='背景込みの三毛猫・4場面', font=('', 14, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='見た目の確認用です。ボタンを押しても営業や猫の状態は変わりません。',
                  wraplength=500).pack(anchor='w', pady=(4, 8))
        self.images = {}
        self.scene = tk.StringVar(master=self.window, value='normal')
        controls = ttk.Frame(frame)
        controls.pack(fill='x', pady=(0, 8))
        self.buttons = {}
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

    def show_scene(self, key):
        scene = next((item for item in SCENES if item[0] == key), None)
        if scene is None:
            raise ValueError('未知の場面です。')
        self.scene.set(key)
        if key in self.images:
            self.image_label.configure(image=self.images[key], text='')
        self.caption.set(f'{scene[1]}：{scene[2]}')


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
