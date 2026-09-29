import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.core.cafe_checkpoint import checkpoint,digest,restore
from cat_cafe_sim.core.cafe_growth import pending,rules
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

    def session(self):
        s=CafeInteractionSession(store=self.store,seat_count=2,
            cafe_config=replace(Config.load(),opening_ticks=8,arrival_ticks=(0,1)),
            interaction_config=replace(RelationshipConfig(),ticks=1))
        s.core.initialize_growth(dict(rules(),threshold=1));return s

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
        dispatch.resolve_activity(event);self.assertEqual(dispatch.core.funds,before+110)
        self.reload(dispatch)

    def test_invalid_rules_choices_and_corrupt_growth_are_rejected(self):
        base=rules()
        for changed in (dict(threshold=0),dict(service_xp=0),dict(service_stamina_refund=1),dict(dispatch_reward_multiplier=float('nan'))):
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


if __name__=='__main__':unittest.main()
