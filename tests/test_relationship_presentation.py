import unittest
from dataclasses import replace

from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig, RelationshipInteraction
from cat_cafe_sim.core.human_cat_types import load_presets
from cat_cafe_sim.human_cat_relationship_gui import result_text
from cat_cafe_sim.relationship_presentation import (
    stage_index, expression_style, greeting_text, relationship_change_text,
)


class RelationshipPresentationTests(unittest.TestCase):
    def test_stage_boundaries_and_invalid_values(self):
        for value, expected in ((0,0),(9.5,0),(10,1),(29.5,1),(30,2),(59.5,2),(60,3),(100,3)):
            with self.subTest(value=value):
                self.assertEqual(stage_index(value),expected)
        for value in (-1,101,float('nan'),True):
            with self.assertRaises(ValueError):
                stage_index(value)

    def test_personality_and_stage_both_affect_expression(self):
        presets=load_presets()
        expected=('neutral','active','contact','quiet','sensitive')
        for personality, style in zip(presets.values(),expected):
            self.assertEqual(expression_style(personality),style)
            texts=[greeting_text(RelationshipInteraction(
                replace(RelationshipConfig(),personality=personality),affinity=n,revision=1))
                for n in (0,10,30,60)]
            self.assertEqual(len(set(texts)),4)
        contact=RelationshipInteraction(replace(RelationshipConfig(),personality=presets['穏やかな甘えん坊']),affinity=60,revision=1)
        quiet=RelationshipInteraction(replace(RelationshipConfig(),personality=presets['距離を大切にする猫']),affinity=60,revision=1)
        self.assertIn('すり寄せ',greeting_text(contact))
        self.assertIn('少し離れた',greeting_text(quiet))

    def test_greeting_uses_history_and_stays_at_start_snapshot(self):
        core=RelationshipInteraction(affinity=9.5,revision=1)
        before=core.log()
        text=greeting_text(core)
        self.assertIn('再会',text)
        self.assertEqual(core.log(),before)
        core.step('direct')
        core.finish()
        self.assertEqual(core.result()['affinity_after'],10)
        self.assertEqual(greeting_text(core),text)
        self.assertIn('初対面',greeting_text(RelationshipInteraction()))
        self.assertIn('再会',greeting_text(RelationshipInteraction(revision=1)))

    def test_result_reports_up_down_same_and_unsaved_without_mutation(self):
        for before,after,phrase in ((9.5,10,'上がりました'),(30,29,'下がりました'),
                                    (1,2,'増えました'),(2,1,'減りました'),(100,100,'変わりません')):
            self.assertIn(phrase,relationship_change_text(before,after))
        core=RelationshipInteraction(affinity=9.5,revision=1)
        core.step('direct');core.finish()
        log=core.log()
        self.assertIn('上がりました',result_text(core,False))
        self.assertIn('未保存',result_text(core,False))
        self.assertIn('保存済み',result_text(core,True))
        self.assertEqual(core.log(),log)
