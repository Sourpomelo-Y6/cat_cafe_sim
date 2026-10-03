"""制作ツールの採用済み文章を読む。ゲームからは書き込まない。"""
import json
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[1] / 'saves' / 'content_images' / 'texts.json'
DEFAULT_SCENES = {
    'normal': 'マットの上で落ち着いて座っています。',
    'play': 'ねこじゃらしに手を伸ばしています。',
    'pet': '頭を撫でられて、気持ちよさそうにしています。',
    'sleep': 'マットの上で丸くなって眠っています。',
}


class TextReader:
    def __init__(self, path=DEFAULT_PATH):
        self.path = Path(path)

    def read(self):
        if not self.path.exists():
            return {'version': 1, 'cats': {}}
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if (not isinstance(data, dict) or type(data.get('version')) is not int
                or data['version'] != 1 or not isinstance(data.get('cats'), dict)):
            raise ValueError('文章ファイルの形式が不正です。')
        for cat_id, record in data['cats'].items():
            if (not isinstance(cat_id, str) or not cat_id or not isinstance(record, dict)
                    or not isinstance(record.get('introduction'), str)
                    or len(record['introduction']) > 2000 or not isinstance(record.get('scenes'), dict)):
                raise ValueError('紹介文の形式が不正です。')
            for scene, text in record['scenes'].items():
                if scene not in DEFAULT_SCENES or not isinstance(text, str) or len(text) > 500:
                    raise ValueError('行動描写の形式が不正です。')
        return data

    def display(self, cat_id, name, scene):
        if scene not in DEFAULT_SCENES:
            raise ValueError('未知の場面です。')
        try:
            record = self.read()['cats'].get(cat_id, {})
        except (OSError, ValueError):
            record = {}
        introduction = record.get('introduction', '').strip()
        caption = record.get('scenes', {}).get(scene, '').strip()
        return (introduction or f'{name}の様子をご覧ください。', caption or DEFAULT_SCENES[scene])
