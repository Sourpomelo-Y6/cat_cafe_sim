import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.cafe_cat_details import cat_details
from cat_cafe_sim.cafe_cat_events import cat_events
from cat_cafe_sim.core.cafe_checkpoint import checkpoint,digest,restore
from cat_cafe_sim.core.cafe_growth import description,mastery_choices,mastery_pending,pending,rules,service,summary
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.storage.cafe_saves import load_game,save_game
from cat_cafe_sim.storage.playtest_cats import add_playtest_cats
from cat_cafe_sim.storage.relationships import RelationshipStore


class CafeGrowthTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=RelationshipStore(Path(self.temp.name)/'relationships.json');add_playtest_cats(self.store)
        self.path=Path(self.temp.name)/'game.json'

    def session(self,mastery_threshold=15):
        s=CafeInteractionSession(store=self.store,seat_count=2,
            cafe_config=replace(Config.load(),opening_ticks=8,arrival_ticks=(0,1)),
            interaction_config=replace(RelationshipConfig(),ticks=1))
        s.core.initialize_growth(dict(rules(),threshold=1,mastery_threshold=mastery_threshold));return s

    def reload(self,s):
        save_game(s,self.path);loaded,_=load_game(self.path)
        self.assertEqual(loaded.core.snapshot(),s.core.snapshot());return loaded

    def test_service_experience_categories_choice_effect_save_and_replay(self):
        s=self.session();key=next(iter(s.core.cats));s.automatic_step();s.start('guest-1',key,'seat-1');s.automatic_step(auto_assign=False)
        row=s.core.growth['cats'][key]
        self.assertEqual((row['service'],row['groups']['play']), (1,1))
        self.assertEqual(pending(s.core),[key])
        with self.assertRaisesRegex(ValueError,'得意分野'):s.automatic_step()
        s.resolve_growth(key,'service');before=s.core.cats[key].stamina
        s.start('guest-2',key,'seat-1');s.automatic_step(auto_assign=False)
        self.assertEqual(s.core.cats[key].stamina,before-4.5)
        self.assertEqual(s.core.growth['cats'][key]['type_actions']['teaser'],2)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot());self.reload(s)

    def test_rest_and_dispatch_specializations_apply_once(self):
        rest=self.session();keys=list(rest.core.cats);key=keys[0]
        rest.set_shifts(keys[1:]);rest.day_off();self.assertIn(key,pending(rest.core))
        for cat_id in list(pending(rest.core)):rest.resolve_growth(cat_id,'rest' if cat_id==key else 'service')
        rest.core.cats[key].fatigue=40;rest.core.initial_fatigue[key]=40;rest.set_shifts(keys[1:]);rest.day_off()
        self.assertEqual(rest.core.cats[key].fatigue,15)

        dispatch=self.session();key=next(iter(dispatch.core.cats));dispatch.dispatch(key);dispatch.day_off()
        event=next(iter(dispatch.core.activities['events']));before=dispatch.core.funds
        for cat_id in list(pending(dispatch.core)):dispatch.resolve_growth(cat_id,'service')
        dispatch.resolve_activity(event);self.assertIn(key,pending(dispatch.core));dispatch.resolve_growth(key,'dispatch')
        self.assertEqual(dispatch.core.funds,before+100)
        dispatch.dispatch(key);dispatch.day_off()
        event=[e for e in dispatch.core.activities['events'] if e!=event][0];before=dispatch.core.funds
        dispatch.resolve_activity(event);self.assertEqual(dispatch.core.funds,before+130)  # 派遣得意の倍率と歓迎報酬20。
        self.reload(dispatch)

    def test_invalid_rules_choices_and_corrupt_growth_are_rejected(self):
        base=rules()
        for changed in (dict(threshold=0),dict(service_xp=0),dict(service_stamina_refund=1),dict(dispatch_reward_multiplier=float('nan')),
                        dict(mastery_threshold=0),dict(mastery_engagement_multiplier=1)):
            with self.assertRaises(ValueError):rules(dict(base,**changed))
        s=self.session();before=s.core.snapshot()
        for cat,choice in (('unknown','service'),(next(iter(s.core.cats)),'invalid')):
            with self.assertRaises(ValueError):s.resolve_growth(cat,choice)
            self.assertEqual(s.core.snapshot(),before)
        source=checkpoint(s.core,set())
        for mutate in (lambda d: d['state']['growth']['cats'].pop(next(iter(d['state']['growth']['cats']))),
                       lambda d: d['state']['growth']['cats'][next(iter(d['state']['growth']['cats']))]['groups'].update(play=2)):
            bad=copy.deepcopy(source);mutate(bad);bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)

    def test_selection_text_shows_progress_practice_and_active_effect(self):
        s=self.session();key=next(iter(s.core.cats));row=s.core.growth['cats'][key]
        row.update(service=.5,rest=.25,dispatch=.25)
        row['type_actions']['teaser']=2;row['groups']['play']=2
        self.assertEqual(summary(s.core,key),'\u7d4c\u9a13 1/1')
        self.assertIn('\u63a5\u5ba2 0.5 / \u4f11\u990a 0.25 / \u6d3e\u9063 0.25',description(s.core,key))
        self.assertIn('\u904a\u3073 2 / \u89e6\u308c\u5408\u3044 0 / \u9759\u304b\u306a\u4ea4\u6d41 0',description(s.core,key))
        s.resolve_growth(key,'dispatch')
        self.assertEqual(summary(s.core,key),'\u5f97\u610f\uff1a\u6d3e\u9063')
        self.assertIn('\u6d3e\u9063\u5831\u916c\u00d71.1',description(s.core,key))
        s.core.growth=None
        self.assertEqual(summary(s.core,key),'\u672a\u5c0e\u5165')
        self.assertIn('\u672a\u5c0e\u5165',description(s.core,key))

    def test_positive_service_unlocks_chosen_mastery_and_boosts_matching_group(self):
        s=self.session(mastery_threshold=1);key=next(iter(s.core.cats))
        s.automatic_step();s.start('guest-1',key,'seat-1');s.step('direct')
        s.resolve_growth(key,'service')
        self.assertEqual(mastery_pending(s.core),[key])
        self.assertEqual(mastery_choices(s.core,key),('play',))
        with self.assertRaisesRegex(ValueError,'接客分類'):s.resolve_growth_mastery(key,'quiet')
        s.resolve_growth_mastery(key,'play')
        self.assertIn('遊び',description(s.core,key));self.assertIn('×1.1',description(s.core,key))
        self.assertEqual(dict(cat_details(s,key)['basic'])['得意な交流'],'遊び')
        self.assertIn('得意な交流の選択',str(cat_events(s.core,key)))

        s.start('guest-2',key,'seat-1')
        active=s.active_interactions['seat-1']
        self.assertEqual((active.config.mastery_group,active.config.mastery_engagement_multiplier),('play',1.1))
        s.step('direct');record=next(event['record'] for event in reversed(s.core.events) if event['kind']=='human_cat_action')
        self.assertEqual(record['diagnostic']['mastery_group'],'play')
        self.assertEqual(record['diagnostic']['mastery_multiplier'],1.1)
        self.assertGreater(record['engagement_delta'],record['diagnostic']['base_gain'])
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot());self.reload(s)

    def test_failed_service_does_not_qualify_and_legacy_growth_stays_compatible(self):
        s=self.session();key=next(iter(s.core.cats));row=s.core.growth['cats'][key]
        service(s.core,dict(cat_id=key,stamina_spent=0,affinity_delta=0,type_actions={'teaser':10}))
        self.assertEqual(row['groups']['play'],10)
        self.assertEqual(row['mastery_groups']['play'],0)

        legacy=rules();legacy.pop('mastery_threshold');legacy.pop('mastery_engagement_multiplier')
        old=CafeInteractionSession(store=self.store,seat_count=2)
        old.core.initialize_growth(legacy)
        self.assertNotIn('mastery',old.core.growth['cats'][next(iter(old.core.cats))])
        self.reload(old)


if __name__=='__main__':unittest.main()
