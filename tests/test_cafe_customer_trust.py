import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from cat_cafe_sim.cafe_customers import directory
from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.core.cafe_customer_discontent import rules as discontent_rules, row as discontent_row
from cat_cafe_sim.core.cafe_customer_satisfaction import rules as satisfaction_rules
from cat_cafe_sim.core.cafe_customer_trust import rules, row, waiting
from cat_cafe_sim.core.cafe_management import rules as management_rules
from cat_cafe_sim.core.cafe_weekdays import schedule
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.storage.cafe_saves import save_game, load_game
from cat_cafe_sim.storage.playtest_cats import add_playtest_cats
from cat_cafe_sim.storage.relationships import RelationshipStore


class CustomerTrustTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        store=RelationshipStore(Path(self.temp.name)/'relationships.json');add_playtest_cats(store)
        config=replace(Config.load(),opening_ticks=4,arrival_ticks=(0,),max_wait_ticks=2)
        self.s=CafeInteractionSession(store=store,seat_count=2,cafe_config=config,interaction_config=replace(RelationshipConfig(),ticks=2))
        core=self.s.core
        core.initialize_weekdays(dict(start_weekday=0,patterns=[list(range(7))]))
        core.initialize_preferences({key:[] for key in core.cats},dict(pool=['white'],tension_multiplier=1.25))
        core.initialize_customer_satisfaction(dict(satisfaction_rules(),satisfied_score=1))
        core.initialize_customer_loyalty(dict(gain=25,threshold=100))
        core.initialize_customer_discontent(dict(discontent_rules(),waiting_gain=100,suspension_days=1))
        self.s.set_shifts(sorted(core.cats))
        self.s.enable_management(management_rules())
        core.initialize_customer_trust(rules())

    def timeout_day(self):
        self.s.step();self.s.step()
        while not self.s.core.closed:self.s.step()
        self.s.next_day()

    def warning(self):
        self.timeout_day();self.s.day_off()
        self.timeout_day()
        self.assertEqual(len(waiting(self.s.core)),1)
        return waiting(self.s.core)[0]

    def reload(self):
        path=Path(self.temp.name)/'cafe.json';save_game(self.s,path);loaded,_=load_game(path)
        self.assertEqual(loaded.core.snapshot(),self.s.core.snapshot());self.s=loaded

    def test_ignore_causes_permanent_departure_popularity_loss_and_no_future_visit(self):
        event=self.warning();before=self.s.core.management['popularity']
        self.s.resolve_customer_trust(event['id'],'ignore')
        self.assertEqual(row(self.s.core,'guest-1')['status'],'departed')
        self.assertEqual(self.s.core.management['popularity'],before-rules()['popularity_loss'])
        self.assertNotIn('guest-1',schedule(self.s.core,100))
        listing=next(value for value in directory(self.s) if value['customer_id']=='guest-1')
        self.assertIn('永久離脱',listing['status'])
        self.assertEqual(verify_cafe_interaction(self.s.core.log()).snapshot(),self.s.core.snapshot())
        self.reload()

    def test_recovery_succeeds_on_satisfied_service_and_keeps_history(self):
        event=self.warning();self.s.resolve_customer_trust(event['id'],'recover');self.reload()
        self.s.day_off();self.s.step();self.s.start('guest-1',next(iter(self.s.core.cats)))
        while self.s.active_interactions:self.s.automatic_step()
        self.assertEqual(row(self.s.core,'guest-1')['status'],'stable')
        self.assertEqual(discontent_row(self.s.core,'guest-1')['score'],rules()['recovery_score'])
        self.assertEqual(self.s.core.customer_trust['events'][event['id']]['outcome'],'recovered')
        self.reload()

    def test_dissatisfied_recovery_service_causes_departure(self):
        from cat_cafe_sim.cafe_customers import cat_rows
        event=self.warning();self.s.resolve_customer_trust(event['id'],'recover')
        self.s.day_off();self.s.step()
        cat=next(value['cat_id'] for value in cat_rows(self.s,'guest-1') if not value['matches'])
        self.s.start('guest-1',cat);self.s.finish()
        self.assertEqual(row(self.s.core,'guest-1')['reason'],'recovery_failed')
        self.assertEqual(self.s.core.customer_trust['events'][event['id']]['outcome'],'departed')
        self.reload()

    def test_invalid_rules(self):
        base=rules()
        for change in (dict(warning_suspensions=1),dict(warning_suspensions=True),dict(recovery_score=-1),dict(popularity_loss=float('inf'))):
            with self.assertRaises(ValueError):rules(dict(base,**change))


if __name__=='__main__':unittest.main()
