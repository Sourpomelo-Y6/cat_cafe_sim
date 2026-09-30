import copy
import os
import unittest
from pathlib import Path
from unittest.mock import PropertyMock, patch

import test_cafe_housing as housing
import test_cafe_introduction_housing as introductions
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.core.cafe_housing import capacity, count, daily_cost, expenses, upgrade_rules, upgrade_reason
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.core.cafe_operating_cost import estimate
from cat_cafe_sim.core.cafe_activities import destinations
from cat_cafe_sim.storage.cafe_saves import save_game


class HousingUpgradeTests(unittest.TestCase):
    setUp=housing.HousingTests.setUp
    reload=housing.HousingTests.reload
    replay=housing.HousingTests.replay
    data=introductions.IntroductionHousingTests.data
    accept=introductions.IntroductionHousingTests.accept
    reload_replay=introductions.IntroductionHousingTests.reload_replay

    def game(self, legacy=False, seats=2, selected=None):
        settings=starting_conditions('free')
        for key in ('intake_request','store_events','growth','regular_introduction'):settings.pop(key)
        settings['seat_count']=seats
        settings['management']['starting_funds']=20000
        if legacy:settings.pop('housing')
        elif selected is not None:settings['housing']=selected
        return create_game(Path(self.temp.name)/'games',settings)

    def rejected(self,s,action):
        before=s.core.log()
        with self.assertRaises(ValueError):action()
        self.assertEqual(s.core.log(),before)

    def introduction(self, kind, *, legacy=False, simultaneous=False, receive=True):
        selected = starting_conditions('free')
        for key in ('store_events', 'growth', 'dispatch_unlocks', 'customer_trust', 'customer_discontent'):
            selected.pop(key)
        selected['management']['starting_funds'] = 10000
        selected['management']['stress_per_service_tick'] = 0
        selected['profiles']['cats']['sixth'] = copy.deepcopy(selected['profiles']['cats']['cat-mugi'])
        if kind != 'regular':
            selected.pop('regular_introduction')
        else:
            selected['customer_loyalty'] = dict(gain=25, threshold=25)
        if kind == 'intake' or simultaneous:
            selected['intake_request']['day'] = 2 if kind == 'intake' else 3
        else:
            selected.pop('intake_request')
        if legacy:
            selected.pop('housing')
        s = create_game(Path(self.temp.name) / 'games', selected)
        s.purchase_housing();s.open_recruitment()
        for key in list(s.core.recruitment['candidates']):s.recruit_cat(key)
        event_id = None
        if kind == 'intake':
            s.day_off()
        elif kind == 'regular':
            while not s.core.closed:
                s.automatic_step()
            s.next_day()
        else:
            s.dispatch('cat-mike', destinations()[1])
            event_id = 'dispatch-1-cat-mike'
            s.day_off()
            s.resolve_dispatch_choice(event_id, 'decline')
            s.day_off()
        if kind=='dispatch' and receive:s.resolve_activity(event_id)
        return s,event_id

    def test_same_day_totals_original_purchase_and_replay_both_seat_modes(self):
        for seats in (1,2):
            s=self.game(seats=seats);s.purchase_housing()
            original=copy.deepcopy(s.core.housing);funds=s.core.funds
            s.upgrade_housing()
            self.assertEqual(s.core.funds,funds-1000)
            self.assertEqual(s.core.housing['purchase'],original['purchase'])
            self.assertEqual(s.core.housing['rules'],original['rules'])
            self.assertEqual(capacity(s.core),12);self.assertEqual(daily_cost(s.core),40)
            self.assertEqual(expenses(s.core),1500)
            self.assertEqual(estimate(s.core),40+seats*10+40)
            self.rejected(s,s.upgrade_housing);self.rejected(s,s.purchase_housing)
            s=self.reload(s);self.replay(s);s.day_off()
            self.assertEqual(s.core.day_results[-1]['summary']['housing_expenses'],1500)
            self.assertEqual(s.core.operating_cost['charges'][-1]['housing_cost'],40)
            s.day_off();self.assertEqual(s.core.day_results[-1]['summary']['housing_expenses'],0)
            self.reload(s);self.replay(s)

    def test_later_day_historical_capacity_costs_business_and_rest(self):
        s=self.game();s.day_off();s.purchase_housing();s.day_off();s.upgrade_housing()
        self.assertEqual([capacity(s.core,d) for d in (1,2,3)],[6,9,12])
        self.assertEqual([daily_cost(s.core,d) for d in (1,2,3)],[0,20,40])
        self.assertEqual([expenses(s.core,d) for d in (1,2,3)],[0,500,1000])
        while not s.core.closed:s.automatic_step()
        s.next_day()
        self.assertEqual([r['summary']['housing_expenses'] for r in s.core.day_results],[0,500,1000])
        self.assertEqual([r['housing_cost'] for r in s.core.operating_cost['charges']],[0,20,40])
        self.reload(s);self.replay(s)

    def test_full_nine_upgrade_and_twelve_limit_all_admission_paths(self):
        s=self.game();s.purchase_housing();s.open_recruitment()
        for key in list(s.core.recruitment['candidates']):s.recruit_cat(key)
        shops=list(s.core.pet_shop['candidates']);s.purchase_cat(shops[0])
        self.assertEqual(count(s.core),9)
        self.rejected(s,lambda:s.purchase_cat(shops[1]))
        s.upgrade_housing()
        for key in shops[1:]:s.purchase_cat(key)
        for _ in range(3):s.day_off()
        s.open_recruitment()
        candidates=[key for key in s.core.recruitment['candidates'] if key not in s.core.recruitment['accepted']]
        s.recruit_cat(candidates[0]);self.assertEqual(count(s.core),12)
        self.rejected(s,lambda:s.recruit_cat(candidates[1]))
        self.reload(s);self.replay(s)

    def test_introductions_upgrade_waiting_accept_and_finance(self):
        for kind in ('intake','regular','dispatch'):
            s,event_id=self.introduction(kind)
            self.assertEqual(count(s.core),9)
            self.rejected(s,lambda:self.accept(s,kind,event_id))
            self.assertEqual(upgrade_reason(s.core,upgrade_rules()),'')
            funds=s.core.funds;s.upgrade_housing()
            self.assertEqual(capacity(s.core),12)
            self.assertEqual(s.core.funds,funds-1000)
            self.assertEqual(self.data(s,kind,event_id)['status'],'waiting')
            self.rejected(s,s.day_off)
            s=self.reload_replay(s);self.accept(s,kind,event_id)
            self.assertEqual(count(s.core),10)
            s.day_off();self.assertEqual(s.core.day_results[-1]['summary']['housing_expenses'],1000)
            self.reload_replay(s)

    def test_legacy_no_limit_old_housing_frozen_rules_and_save_failure(self):
        s=self.game(legacy=True)
        self.assertIsNone(capacity(s.core));self.rejected(s,s.upgrade_housing)
        self.assertNotIn('housing',s.core.snapshot());self.reload(s);self.replay(s)
        from cat_cafe_sim.core.cafe_housing import rules
        s=self.game(selected=dict(rules(),initial_capacity=7,capacity_bonus=4,cost=250,daily_cost=25))
        s.purchase_housing();s=self.reload(s)
        self.assertNotIn('upgrade',s.core.housing);self.assertEqual(capacity(s.core),11)
        custom=dict(capacity_bonus=2,cost=700,daily_cost=45)
        s.upgrade_housing(custom);self.assertEqual(capacity(s.core),13)
        funds=s.core.funds
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write',side_effect=OSError('full')):
            with self.assertRaises(OSError):save_game(s,s.checkpoint_path)
        self.assertEqual(s.core.funds,funds)
        with patch('cat_cafe_sim.core.cafe_housing.upgrade_rules',side_effect=lambda data:upgrade_rules(data)):
            s=self.reload(s);self.replay(s)
        self.assertEqual(s.core.housing['upgrade']['rules'],custom)
        self.rejected(s,s.upgrade_housing);self.assertEqual(s.core.funds,funds)

    def test_preparation_initial_purchase_funds_and_pending_restrictions(self):
        s=self.game();self.rejected(s,s.upgrade_housing);s.purchase_housing()
        with patch.object(type(s),'pending',new_callable=PropertyMock,return_value={'pending'}):self.rejected(s,s.upgrade_housing)
        for funds in (999,1000):s.core.funds=funds;self.rejected(s,s.upgrade_housing)
        s.core.funds=1001;s.core.recorded_digest=None;s.upgrade_housing();self.assertEqual(s.core.funds,1)
        s.day_off();self.rejected(s,s.upgrade_housing)
        s=self.game();s.purchase_housing();s.play_with_player(next(iter(s.core.cats)))
        self.rejected(s,s.upgrade_housing);s.player_command(finish=True)
        s.step();self.rejected(s,s.upgrade_housing);s.finish();self.rejected(s,s.upgrade_housing)
        s,event_id=self.introduction('dispatch',receive=False)
        self.rejected(s,s.upgrade_housing)

    def test_simultaneous_introductions_expand_once_keep_other_pending(self):
        s,event_id=self.introduction('dispatch',simultaneous=True)
        s.upgrade_housing();self.rejected(s,s.upgrade_housing)
        s.resolve_intake_request('accept');self.rejected(s,s.day_off)
        s.resolve_dispatch_introduction(event_id,'accept')
        self.assertEqual(count(s.core),11);self.reload_replay(s)

    def test_invalid_upgrade_and_corrupt_historical_records(self):
        for changes in (dict(capacity_bonus=0),dict(capacity_bonus=True),dict(cost=0),dict(cost=float('nan')),dict(daily_cost=True),dict(extra=1)):
            with self.assertRaises(ValueError):upgrade_rules(dict(upgrade_rules(),**changes))
        s=self.game();s.purchase_housing()
        self.rejected(s,lambda:s.upgrade_housing(dict(upgrade_rules(),daily_cost=20)))
        s.day_off();s.upgrade_housing();s.day_off();source=checkpoint(s.core,set())
        for mutate in (
            lambda d:d['state']['housing']['upgrade'].update(day=0),
            lambda d:d['state']['housing']['upgrade'].update(day=True),
            lambda d:d['state']['housing']['upgrade']['rules'].update(cost=999),
            lambda d:d['state']['housing']['upgrade']['rules'].update(daily_cost=20),
            lambda d:d['state']['housing'].update(purchase=None),
            lambda d:d['state']['day_results'][1]['summary'].update(housing_expenses=0),
            lambda d:d['state']['operating_cost']['charges'][0].update(housing_cost=40),
        ):
            bad=copy.deepcopy(source);mutate(bad);bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires a display')
class HousingUpgradeGuiTests(unittest.TestCase):
    setUp=HousingUpgradeTests.setUp
    game=HousingUpgradeTests.game
    data=HousingUpgradeTests.data
    accept=HousingUpgradeTests.accept

    def test_upgrade_confirmation_cancel_history_main_log_minimum_layout(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_housing_gui import CafeHousingWindow
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root=tk.Tk();self.addCleanup(root.destroy)
        s=self.game();app=CafeInteractionWindow(root,s)
        s.purchase_housing();app.refresh();w=CafeHousingWindow(root,s,app.refresh)
        w.window.geometry('500x320');root.update()
        self.assertIn('9 → 12匹',w.details.get());self.assertIn('80 → 100',w.details.get())
        self.assertFalse(w.upgrade_button.instate(['disabled']))
        for button in (w.purchase_button,w.upgrade_button,w.close_button):
            self.assertTrue(button.winfo_ismapped())
            self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),w.window.winfo_rootx()+w.window.winfo_width())
            self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),w.window.winfo_rooty()+w.window.winfo_height())
        before=s.core.snapshot()
        with patch('tkinter.messagebox.askyesno',return_value=False):w.upgrade_button.invoke()
        self.assertEqual(s.core.snapshot(),before)
        with patch('tkinter.messagebox.askyesno',return_value=True):w.upgrade_button.invoke()
        self.assertEqual(capacity(s.core),12);self.assertIn('追加拡張済み',w.details.get())
        self.assertTrue(w.upgrade_button.instate(['disabled']))
        self.assertTrue(any('2段階目へ拡張' in str(app.history.item(key,'values')) for key in app.history.get_children()))
        s.day_off();app.show_history();row=app.history_window.days.get_children()[-1]
        self.assertEqual(app.history_window.days.set(row,'飼育スペース費用'),'1500')
        self.assertEqual(app.history_window.days.set(row,'運営費'),'100')

    def test_all_introduction_dialogs_upgrade_readmit_and_return_grab(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_intake_request_gui import CafeIntakeRequestWindow
        from cat_cafe_sim.cafe_regular_introduction_gui import CafeRegularIntroductionWindow
        from cat_cafe_sim.cafe_dispatch_introduction_gui import CafeDispatchIntroductionWindow
        root=tk.Tk();self.addCleanup(root.destroy)
        for kind,dialog in (('intake',CafeIntakeRequestWindow),('regular',CafeRegularIntroductionWindow),('dispatch',CafeDispatchIntroductionWindow)):
            s,event_id=self.introduction(kind)
            w=dialog(root,s,event_id,lambda:None) if kind=='dispatch' else dialog(root,s,lambda:None)
            self.assertFalse(w.housing_button.instate(['disabled']))
            w.housing_button.invoke();child=w.housing_window
            with patch('tkinter.messagebox.askyesno',return_value=True):child.upgrade_button.invoke()
            self.assertEqual(capacity(s.core),12)
            child.close();root.update();self.assertEqual(root.grab_current(),w.window)
            self.accept(s,kind,event_id);w.window.destroy()

HousingUpgradeGuiTests.introduction=HousingUpgradeTests.introduction
