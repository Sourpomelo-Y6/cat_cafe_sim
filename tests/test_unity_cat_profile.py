import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from cat_cafe_sim.cafe_cat_details import cat_details
from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.cafe_new_game import create_game
from cat_cafe_sim.core.cafe_traits import DEFAULTS, description, trait
from cat_cafe_sim.core.cat_appearance import FIELDS
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.core.human_cat_types import Personality
from cat_cafe_sim.storage.relationships import RelationshipStore
from cat_cafe_sim.unity_state_server import state_view, cat_profile_view
from test_unity_dispatch_choices import api


class UnityCatProfileTests(unittest.TestCase):
    def test_canonical_fields_effects_and_cat_isolation_are_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            s=create_game(Path(directory)/'source');keys=list(s.core.cats);key=keys[0]
            s.set_cat_appearance(key, {'eye_color':'緑', 'notes':'外見の補足'*100})
            s.core.traits={key:dict(DEFAULTS,id='fixture',name='テスト特性',service_stress=.8,service_fatigue=.6,rest_fatigue=1.5,dispatch_reward=1.2,return_stress=10)}
            s.core.cat_features[key]=['calico','short_hair']
            before=copy.deepcopy(s.core.snapshot());profiles=copy.deepcopy(s.profiles);raw=s.store.path.read_bytes()
            first=state_view(s);self.assertEqual(first,state_view(s))
            for row in first['cats']:
                basic=cat_details(s,row['cat_id'])['basic'];profile=row['profile_details']
                labels={'名前','猫ID','個性','特徴',*FIELDS.values(),'飽きやすさ','種類切り替えへの反応',*(name for name,_ in description(trait(s.core,row['cat_id'])))}
                for name,value in basic:
                    if name in labels or name.startswith(('好み：','強さの好み：')):
                        self.assertIn(f'{name}：{value}',profile)
            text=next(row for row in first['cats'] if row['cat_id']==key)['profile_details']
            self.assertIn('特徴：三毛・短毛',text);self.assertIn('通常の0.8倍',text);self.assertIn('＋10',text)
            self.assertNotIn('目の色：緑',next(row for row in first['cats'] if row['cat_id']==keys[1])['profile_details'])
            self.assertEqual(before,s.core.snapshot());self.assertEqual(profiles,s.profiles);self.assertEqual(raw,s.store.path.read_bytes())

    def test_unregistered_legacy_custom_personality_and_missing_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            store=RelationshipStore(Path(directory)/'missing.json')
            personality=replace(Personality(),type_preferences=(1.5,)*8)
            s=CafeInteractionSession(store=store,interaction_config=replace(RelationshipConfig(),personality=personality))
            before=copy.deepcopy(s.core.snapshot());text=cat_profile_view(cat_details(s,'cat-1'))
            self.assertIn('カスタム（未登録・営業の既定個性）',text);self.assertIn('特性：なし',text)
            self.assertIn('特徴：未設定',text);self.assertIn('目の色：未設定',text)
            self.assertIn('好み：ねこじゃらし：1.5',text)
            self.assertFalse(store.path.exists());self.assertEqual(before,s.core.snapshot())

    def test_http_save_reload_preserves_profile_and_original_files(self):
        with tempfile.TemporaryDirectory() as directory:
            s=create_game(Path(directory)/'source');key=next(iter(s.core.cats));s.set_cat_appearance(key, {'eye_color':'金色','tail':'長い尻尾'})
            originals={p:p.read_bytes() for p in s.checkpoint_path.parent.iterdir() if p.is_file()};before=copy.deepcopy(s.core.snapshot())
            with api(s,Path(directory)/'saves') as (read,post):
                first={row['cat_id']:row['profile_details'] for row in read()['cats']}
                self.assertEqual(first,{row['cat_id']:row['profile_details'] for row in read()['cats']})
                self.assertEqual(before,s.core.snapshot())
                code,saved,_=post('save_game');self.assertEqual(code,200)
                self.assertEqual(post('load_game',save_id=saved['save_id'])[0],200)
                self.assertEqual(first,{row['cat_id']:row['profile_details'] for row in read()['cats']})
            self.assertEqual(originals,{p:p.read_bytes() for p in originals})
