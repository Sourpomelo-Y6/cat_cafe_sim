"""テスト用猫の追加。既存IDは名前・個性を変更しない。"""
import json
from pathlib import Path

from ..core.human_cat_types import load_presets


def add_playtest_cats(store):
    definitions=json.loads((Path(__file__).resolve().parents[2]/'config/cafe_playtest_cats.json').read_text(encoding='utf-8'))
    presets=load_presets()
    existing={row['cat_id'] for row in store.list_cats()}
    added=[]
    for row in definitions:
        if row['cat_id'] not in existing:
            store.register_cat(row['cat_id'],row['name'],presets[row['preset']])
            added.append(row['cat_id'])
    return added
