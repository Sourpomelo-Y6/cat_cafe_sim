"""体力自慢の接客・休養と、新規候補だけへの適用。"""
import copy
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import test_cafe_traits as fixtures
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.cafe_cat_details import cat_details
from cat_cafe_sim.cafe_shift_forecast import shift_forecast
from cat_cafe_sim.core.cafe_traits import definitions, trait, description
from cat_cafe_sim.core.cafe_recruitment import candidates, catalog
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class HardyTraitTests(unittest.TestCase):
    setUp = fixtures.TraitTests.setUp
    session = fixtures.TraitTests.session
    close = fixtures.TraitTests.close
    reload = fixtures.TraitTests.reload

    def replay(self, s):
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())

    def candidate_game(self):
        selected = starting_conditions('free')
        for key in ('intake_request', 'regular_introduction', 'store_events', 'growth'):
            selected.pop(key)
        selected['management']['starting_funds'] = 10000
        s = create_game(Path(self.temp.name) / 'games', selected)
        s.open_recruitment()
        for _ in range(3):
            s.day_off()
        s.open_recruitment()
        key = next(key for key, row in s.core.recruitment['candidates'].items()
                   if row.get('trait', {}).get('id') == 'hardy')
        return s, key

    def test_catalog_assigns_two_new_candidates_and_keeps_first_batch(self):
        rows = catalog()
        self.assertEqual([row['name'] for row in rows if row['trait']['id'] == 'hardy'], ['ソラ', 'フク'])
        self.assertEqual([row['trait']['id'] for row in rows[:3]], ['hospitality', 'outgoing', 'relaxed'])
        hardy = definitions()['hardy']
        self.assertEqual(dict(description(hardy)), {'特性': '体力自慢', '接客疲労': '通常の0.75倍',
                                                    '休養時の疲労回復': '通常の0.75倍'})

    def test_service_rest_forecast_fraction_and_once_only(self):
        s = self.session({'a': 'hardy'}, fatigue=32)
        self.close(s)
        self.assertEqual(s.core.cats['a'].fatigue, 24)
        self.assertEqual(s.core.cats['b'].fatigue, 32)
        self.assertEqual(s.core.management['stress']['a'], 1)
        s = self.reload(s); s.next_day()
        forecast = shift_forecast(s.core, 'a')
        self.assertEqual(forecast['work']['fatigue'], 48)
        self.assertEqual(forecast['rest']['fatigue'], 9)
        before = s.core.snapshot()
        shift_forecast(s.core, 'a')
        self.assertEqual(s.core.snapshot(), before)
        s.day_off()
        self.assertEqual(s.core.cats['a'].fatigue, 9)
        self.assertEqual(s.core.cats['b'].fatigue, 12)
        s = self.reload(s); self.replay(s)
        s.day_off()
        self.assertEqual(s.core.cats['a'].fatigue, 0)
        self.replay(s)
        s = self.session({'a': 'hardy'})
        self.close(s)
        self.assertEqual(s.core.cats['a'].fatigue, .75)
        self.reload(s); self.replay(s)

    def test_equipment_bonus_is_added_after_trait_and_working_rest_mix(self):
        s = self.session({'a': 'hardy'}, fatigue=64)
        s.purchase_rest_space()
        self.close(s); s.next_day()
        self.assertEqual(s.core.cats['a'].fatigue, 48)
        self.assertEqual(shift_forecast(s.core, 'a')['rest']['fatigue'], 23)
        s.set_shifts(['b', 'c'])
        self.close(s)
        self.assertEqual(s.core.cats['a'].fatigue, 23)
        self.reload(s); self.replay(s)

    def test_absent_cat_does_not_receive_rest_and_dispatch_unchanged(self):
        s = self.session({'a': 'hardy'}, fatigue=32)
        self.close(s); s.next_day()
        s.dispatch('a')
        s.day_off()
        self.assertEqual(s.core.cats['a'].fatigue, 24)
        funds = s.core.funds
        stress = s.core.management['stress']['a']
        s.resolve_activity('dispatch-2-a')
        self.assertEqual(s.core.funds, funds + 100)
        self.assertEqual(s.core.management['stress']['a'], stress)
        self.reload(s); self.replay(s)

    def test_new_candidate_join_save_failure_frozen_settings_and_replay(self):
        s, key = self.candidate_game()
        initial = copy.deepcopy(s.core.traits)
        funds = s.core.funds
        row = copy.deepcopy(s.core.recruitment['candidates'][key])
        self.assertEqual(row['trait']['name'], '体力自慢')
        s = self.reload(s)
        with patch.object(s.store, '_write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                s.recruit_cat(key)
        self.assertNotIn(key, s.core.cats)
        self.assertEqual(s.core.funds, funds)
        with patch('cat_cafe_sim.core.cafe_traits.definitions', side_effect=AssertionError('settings changed')):
            s.recruit_cat(key)
            self.assertEqual(trait(s.core, key), row['trait'])
            self.assertEqual(dict(cat_details(s, key)['basic'])['特性'], '体力自慢')
            self.assertEqual({key: value for key, value in s.core.traits.items() if key in initial}, initial)
            self.assertEqual(s.core.funds, funds - 200)
            with self.assertRaises(ValueError):
                s.recruit_cat(key)
            with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    save_game(s, self.path)
            s = self.reload(s)
            self.assertEqual(s.core.funds, funds - 200)
            self.replay(s)

    def test_old_presented_sora_keeps_old_trait_and_old_traitless_save(self):
        s = self.session()
        rows = candidates(s.core.cats, batch=1)
        key = next(iter(rows))
        rows[key]['trait'] = copy.deepcopy(definitions()['hospitality'])
        s.core.open_recruitment(rows)
        s = self.reload(s)
        with patch('cat_cafe_sim.core.cafe_traits.definitions', side_effect=AssertionError('settings changed')):
            s.recruit_cat(key)
            self.assertEqual(trait(s.core, key)['id'], 'hospitality')
            self.reload(s); self.replay(s)
        self.assertIsNone(trait(s.core, 'a'))
        s = self.session()
        rows = candidates(set(s.core.cats) | set(rows), batch=1)
        for row in rows.values():
            row.pop('trait')
        s.core.open_recruitment(rows)
        s = self.reload(s); s.recruit_cat(next(iter(rows)))
        self.assertIsNone(s.core.traits)
        self.close(s)
        self.assertEqual(s.core.cats['a'].fatigue, 1)
        self.reload(s); self.replay(s)

    def test_joined_trait_corruption_is_rejected(self):
        s, key = self.candidate_game()
        s.recruit_cat(key)
        source = checkpoint(s.core, set())
        for value in (True, -.75, 1):
            bad = copy.deepcopy(source)
            bad['state']['traits'][key]['service_fatigue'] = value
            bad['digest'] = digest({key: value for key, value in bad.items() if key != 'digest'})
            with self.assertRaises(ValueError):
                restore(bad)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'requires desktop')
class HardyTraitWindowTests(unittest.TestCase):
    setUp = fixtures.TraitTests.setUp
    candidate_game = HardyTraitTests.candidate_game

    def test_candidate_effects_before_join_and_detail_after_join(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_recruitment_gui import CafeRecruitmentWindow
        root = tk.Tk(); self.addCleanup(root.destroy)
        s, key = self.candidate_game()
        window = CafeRecruitmentWindow(root, s, lambda: None)
        window.window.geometry('500x440'); root.update()
        window.cats.selection_set(key); window.selection_changed()
        self.assertIn('体力自慢', window.cats.item(key)['values'])
        details = dict(tuple(window.details.item(row)['values']) for row in window.details.get_children())
        self.assertEqual(details['接客疲労'], '通常の0.75倍')
        self.assertEqual(details['休養時の疲労回復'], '通常の0.75倍')
        with patch('tkinter.messagebox.askyesno', return_value=False):
            window.receive_button.invoke()
        self.assertNotIn(key, s.core.cats)
        with patch('tkinter.messagebox.askyesno', return_value=True):
            window.receive_button.invoke()
        self.assertEqual(dict(cat_details(s, key)['basic'])['特性'], '体力自慢')
        self.assertLessEqual(window.receive_button.winfo_rooty() + window.receive_button.winfo_height(),
                             window.window.winfo_rooty() + window.window.winfo_height())
