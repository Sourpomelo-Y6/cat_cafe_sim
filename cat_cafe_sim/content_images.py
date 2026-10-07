"""独立した制作ツールが書き出した画像対応表の読み込み。"""
import json
from pathlib import Path

DEFAULT_DIRECTORY = Path(__file__).resolve().parents[1] / 'saves' / 'content_images'
from .core.human_cat_types import TYPE_IDS, default_types
SCENE_IDS = ('normal', 'play', 'pet', 'sleep', 'pause', 'open_up', 'simultaneous') + TYPE_IDS + tuple(
    row.id + '__' + action for row in default_types()
    for action in row.actions + ('pause', 'switch', 'connect', 'open_up', 'simultaneous'))


class ImageRegistry:
    def __init__(self, directory=DEFAULT_DIRECTORY):
        self.directory = Path(directory)
        self.path = self.directory / 'manifest.json'

    def read(self):
        if not self.path.exists():
            return {'version': 1, 'cats': {}}
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('cats'), dict):
            raise ValueError('画像対応表の形式が不正です。')
        for cat_id, scenes in data['cats'].items():
            if not isinstance(cat_id, str) or not isinstance(scenes, dict):
                raise ValueError('猫の画像登録が不正です。')
            for key, value in scenes.items():
                if key not in SCENE_IDS or not isinstance(value, str):
                    raise ValueError('場面の画像登録が不正です。')
                self._resolve(value)
        return data

    def _resolve(self, value):
        path = (self.directory / value).resolve()
        if self.directory.resolve() not in path.parents:
            raise ValueError('画像は登録フォルダ内に置いてください。')
        return path

    def image_path(self, cat_id, scene):
        value = self.read()['cats'].get(cat_id, {}).get(scene)
        return self._resolve(value) if value else None

def load_display_image(master, path):
    import tkinter as tk
    image = tk.PhotoImage(master=master, file=str(path))
    scale = max(1, (image.width() + 639) // 640, (image.height() + 419) // 420)
    return image.subsample(scale, scale)
