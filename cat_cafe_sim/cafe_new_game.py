"""通常ゲームの初期条件とゲームごとの独立した保存先。"""
import json
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

from .core.cafe_management import rules
from .core.config import Config
from .core.cafe_goal import rules as goal_rules
from .core.human_cat_types import load_presets
from .storage.relationships import RelationshipStore
from .storage.cafe_saves import save_game


def starting_conditions():
    data = json.loads((Path(__file__).resolve().parents[1] / 'config/cafe_new_game.json').read_text(encoding='utf-8'))
    if data['seat_count'] not in (1, 2) or not data['cats']:
        raise ValueError('新規ゲームの席・猫の設定が不正です。')
    presets = load_presets()
    from .core.cafe_traits import definitions
    traits = definitions()
    initial_traits = {}
    initial_features = {}
    from .core.cafe_preferences import validate_features, rules as preference_rules
    profiles = dict(format_version=2, cats={}, pairs=[], applied={})
    for row in data['cats']:
        if row['cat_id'] in profiles['cats']:
            raise ValueError('初期猫のIDが重複しています。')
        RelationshipStore._register(profiles, row['cat_id'], row['name'], presets[row['preset']])
        initial_features[row['cat_id']] = validate_features(row.get('features', []))
        if row.get('trait') is not None:
            initial_traits[row['cat_id']] = traits[row['trait']]
    return dict(seat_count=data['seat_count'], profiles=profiles, management=rules(), goal=goal_rules(), traits=initial_traits, features=initial_features, preferences=preference_rules())


def create_game(directory='saves/games', conditions=None):
    """新しい専用ディレクトリに初期セーブまで作成する。既存ゲームを変更しない。"""
    from .cafe_interaction import CafeInteractionSession
    selected = starting_conditions() if conditions is None else conditions
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    location = Path(tempfile.mkdtemp(prefix='game-', dir=directory))
    try:
        store = RelationshipStore(location / 'relationships.json')
        store._write(selected['profiles'])
        session = CafeInteractionSession(store=store, seat_count=selected['seat_count'],
            cafe_config=replace(Config.load(), initial_funds=0))
        session.core.initialize_traits(selected.get('traits', {}))
        if 'preferences' in selected:
            session.core.initialize_preferences(selected.get('features', {}), selected['preferences'])
        session.enable_management(selected['management'])
        session.enable_goal(selected.get('goal'))
        save_game(session, location / 'cafe.json', auto_assign=False)
    except Exception:
        # Only this call's newly allocated directory belongs to the failed creation.
        shutil.rmtree(location, ignore_errors=True)
        raise
    return session
