"""通常ゲームの初期条件とゲームごとの独立した保存先。"""
import json
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

from .core.cafe_management import rules
from .core.config import Config
from .core.cafe_goal import progression_rules as goal_rules
from .core.human_cat_types import load_presets
from .storage.relationships import RelationshipStore
from .storage.cafe_saves import save_game


def starting_conditions(mode="popularity"):
    from .core.cafe_objective import MODES
    if mode not in MODES:
        raise ValueError("目標を選んでください。")
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
    from .core.cafe_weekdays import rules as weekday_rules
    from .core.cafe_intake_request import rules as intake_rules
    from .core.cafe_patron import rules as patron_rules
    from .core.cafe_bond_goal import rules as bond_rules
    from .core.cafe_advanced_customers import rules as advanced_rules
    from .core.cafe_customer_loyalty import rules as loyalty_rules
    from .core.cafe_customer_discontent import rules as discontent_rules
    from .core.cafe_customer_satisfaction import rules as satisfaction_rules
    from .core.cafe_customer_trust import rules as trust_rules
    from .core.cafe_reservation import rules as reservation_rules
    from .core.cafe_vip_customer import rules as vip_rules
    from .core.cafe_operating_cost import rules as operating_cost_rules
    from .core.cafe_waiting_area import rules as waiting_area_rules
    from .core.cafe_store_events import rules as store_event_rules
    return dict(store_events=store_event_rules(), waiting_area=waiting_area_rules(), operating_cost=operating_cost_rules(), vip_customer=vip_rules(), reservation=reservation_rules(), customer_trust=trust_rules(), customer_satisfaction=satisfaction_rules(), customer_discontent=discontent_rules(), customer_loyalty=loyalty_rules(), advanced_customers=advanced_rules(), objective=mode, patron=patron_rules(), bond=bond_rules(), intake_request=intake_rules(), weekdays=weekday_rules(), seat_count=data['seat_count'], profiles=profiles, management=rules(), goal=goal_rules(), traits=initial_traits, features=initial_features, preferences=preference_rules())


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
        if 'weekdays' in selected:
            session.core.initialize_weekdays(selected['weekdays'])
        session.core.initialize_traits(selected.get('traits', {}))
        if 'preferences' in selected:
            session.core.initialize_preferences(selected.get('features', {}), selected['preferences'])
        if 'customer_satisfaction' in selected:
            session.core.initialize_customer_satisfaction(selected['customer_satisfaction'])
        if 'customer_loyalty' in selected:
            session.core.initialize_customer_loyalty(selected['customer_loyalty'])
        if 'customer_discontent' in selected:
            session.core.initialize_customer_discontent(selected['customer_discontent'])
        session.enable_management(selected['management'])
        if 'operating_cost' in selected:
            session.core.initialize_operating_cost(selected['operating_cost'])
        if 'waiting_area' in selected and 'operating_cost' in selected:
            session.core.initialize_waiting_area(selected['waiting_area'])
        if 'store_events' in selected and 'operating_cost' in selected and 'weekdays' in selected:
            session.core.initialize_store_events(selected['store_events'])
        if 'customer_trust' in selected:
            session.core.initialize_customer_trust(selected['customer_trust'])
        session.core.initialize_clear_results()
        mode = selected.get('objective', 'popularity')
        from .core.cafe_objective import MODES
        if mode not in MODES:
            raise ValueError('目標を選んでください。')
        if mode == 'popularity':
            session.enable_goal(selected.get('goal'))
            if 'advanced_customers' in selected:
                session.core.initialize_advanced_customers(selected['advanced_customers'])
            if 'reservation' in selected:
                session.core.initialize_reservation(selected['reservation'])
            if 'vip_customer' in selected:
                session.core.initialize_vip_customer(selected['vip_customer'])
        else:
            from .core.cafe_goal import rules as popularity_rules
            growth = dict(selected.get('goal') or popularity_rules())
            growth.pop('stages', None)
            session.core.enable_goal(growth, tracking_only=True)
            if mode == 'patron':
                session.enable_patron(selected['patron'])
            elif mode == 'bond':
                session.enable_bond_goal(selected['bond'])
        if 'intake_request' in selected:
            session.core.initialize_intake_request(selected['intake_request'])
        if 'objective' in selected:
            session.core.initialize_objective(mode)
        save_game(session, location / 'cafe.json', auto_assign=False)
    except Exception:
        # Only this call's newly allocated directory belongs to the failed creation.
        shutil.rmtree(location, ignore_errors=True)
        raise
    return session
