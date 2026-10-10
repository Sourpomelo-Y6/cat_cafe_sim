import copy
import tempfile
import unittest
from pathlib import Path
from test_unity_dispatch_choices import api
from cat_cafe_sim.cafe_new_game import create_game
from cat_cafe_sim.cafe_history import comparison_rows
from cat_cafe_sim.unity_state_server import business_history_view

class UnityBusinessHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.s=create_game(self.root/'source')

    def test_closed_business_day_off_and_read_only(self):
        s=self.s;before=s.core.snapshot();self.assertEqual(business_history_view(s)['rows'],[]);self.assertEqual(s.core.snapshot(),before)
        while not s.core.closed:s.automatic_step()
        first=business_history_view(s);summary=s.core.day_result()['summary']
        self.assertEqual(len(first['rows']),1)
        row=first['rows'][0];self.assertEqual(row['presentation_version'],1);self.assertIn('店の人気',row['headline']);self.assertIn('接客評価',row['breakdown']);self.assertIn('比較できる記録なし',row['comparison']);self.assertEqual(row['details'],row['breakdown']+'\n\n'+row['comparison'])
        self.assertIn(f"店の人気：{summary['popularity']:g}",first['rows'][0]['details'])
        self.assertIn(f"接客評価・満足：{summary['customer_satisfaction']['satisfied']}",first['rows'][0]['details'])
        s.next_day();self.assertEqual(business_history_view(s),first);s.day_off()
        before=copy.deepcopy(s.core.snapshot());view=business_history_view(s)
        self.assertEqual([row['day'] for row in view['rows']],[1,2]);self.assertIn('休業日',view['rows'][1]['label'])
        summary2=comparison_rows(s.core)[1]['summary']
        self.assertIn(f"店の人気：{summary2['popularity']-summary['popularity']:+g}",view['rows'][1]['details'])
        self.assertEqual(before,s.core.snapshot())

    def test_unknown_legacy_gaps_and_negative_differences(self):
        s=self.s;s.day_off();day=copy.deepcopy(s.core.day_results[0])
        first=day['summary'];first.update(popularity=100,popularity_gain=5,customer_satisfaction=dict(satisfied=2,normal=3,dissatisfied=4),departures=dict(queue_full=3,wait_timeout=2))
        second=copy.deepcopy(day);second['day']=2;second['summary'].update(popularity=90,popularity_gain=2,customer_satisfaction=dict(satisfied=1,normal=4,dissatisfied=2),departures=dict(queue_full=1,wait_timeout=3))
        s.core.day_results=[day,second];view=business_history_view(s)
        text=view['rows'][1]['details']
        for label,value in [('店の人気',-10),('獲得人気',-3),('接客評価・満足',-1),('満員で帰った客',-2),('待ち切れず帰った客',1)]:self.assertIn(f"{label}：{value:+g}",text)
        second['day']=3;self.assertIn('店の人気：比較できる記録なし',business_history_view(s)['rows'][1]['details'])
        for key in ('popularity','popularity_gain','customer_satisfaction'):first.pop(key)
        text=business_history_view(s)['rows'][0]['details']
        self.assertIn('店の人気：未導入・記録なし',text);self.assertIn('接客評価・満足：未導入・記録なし',text)

    def test_http_save_reload_preserves_history(self):
        s=self.s;s.day_off();files={p:p.read_bytes() for p in s.checkpoint_path.parent.iterdir()}
        with api(s,self.root/'saves') as (read,post):
            before=s.core.snapshot();view=read()['business_history'];self.assertEqual(view,read()['business_history']);self.assertEqual(s.core.snapshot(),before)
            saved=post('save_game')[1]['save_id'];self.assertEqual(post('day_off')[0],200);self.assertEqual(len(read()['business_history']['rows']),2)
            self.assertEqual(post('load_game',save_id=saved)[0],200);self.assertEqual(read()['business_history'],view)
        self.assertEqual(files,{p:p.read_bytes() for p in files})
