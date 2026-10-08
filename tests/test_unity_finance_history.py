import copy
import tempfile
import unittest
from pathlib import Path
from test_unity_dispatch_choices import api
from cat_cafe_sim.cafe_new_game import create_game
from cat_cafe_sim.core.cafe_finance import values
from cat_cafe_sim.unity_state_server import state_view,finance_history_view


class UnityFinanceHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.s=create_game(self.root/'source')

    def test_empty_and_closed_business_then_day_off(self):
        s=self.s;before=copy.deepcopy(s.core.snapshot());self.assertEqual(finance_history_view(s)['rows'],[]);self.assertEqual(before,s.core.snapshot())
        while not s.core.closed:s.automatic_step()
        first=finance_history_view(s);summary=s.core.day_result()['summary'];money=values(summary)
        self.assertEqual(len(first['rows']),1);self.assertIn('営業日',first['rows'][0]['label'])
        self.assertIn(f"総収入：{money['total_income']:g}",first['rows'][0]['details']);self.assertIn(f"純収支：{money['net_cash_flow']:+g}",first['rows'][0]['details'])
        s.next_day();self.assertEqual(finance_history_view(s),first);s.day_off()
        second=finance_history_view(s);self.assertEqual(len(second['rows']),2);self.assertIn('休業日',second['rows'][1]['label'])
        current=s.core.day_results[-1]['summary'];self.assertIn(f"純収支：{current['net_cash_flow']-summary['net_cash_flow']:+g}",second['rows'][1]['details'])
        self.assertIn(f"純収支：{current['net_cash_flow']+summary['net_cash_flow']:+g}",second['totals'])

    def test_all_breakdown_keys_negative_comparison_and_legacy(self):
        from cat_cafe_sim.core.cafe_finance import EXPENSE_KEYS
        s=self.s;s.day_off();day=copy.deepcopy(s.core.day_results[0]);summary=day['summary'];summary.update(revenue=50,interaction_bonus=20,dispatch_income=30,item_sales_income=10)
        for key in EXPENSE_KEYS:summary[key]=10
        summary['funds']=1000;summary.update(values(summary));s.core.day_results=[day]
        before=copy.deepcopy(s.core.snapshot());view=finance_history_view(s);self.assertIn('総収入：90',view['rows'][0]['details']);self.assertIn('総支出：120',view['rows'][0]['details']);self.assertIn('純収支：-30',view['rows'][0]['details'])
        for label in ('派遣捜索費','猫購入費','受け入れ費用','子猫引き渡し費用','増席費用','待合費用','飼育スペース費用','休養設備費用','接客設備費用','用品購入費','運営費','店舗イベント支出'):self.assertIn(label+'：10',view['rows'][0]['details'])
        self.assertEqual(before,s.core.snapshot());summary.pop('net_cash_flow');summary.pop('opening_funds');summary.pop('item_expenses')
        old=finance_history_view(s);self.assertIn('純収支：記録なし',old['rows'][0]['details']);self.assertIn('用品購入費：記録なし',old['rows'][0]['details']);self.assertIn('集計できる記録なし',old['totals'])
        next_day=copy.deepcopy(day);next_day['day']=3;s.core.day_results.append(next_day)
        self.assertIn('総収入：比較できる記録なし',finance_history_view(s)['rows'][1]['details'])

    def test_http_read_only_and_save_reload(self):
        s=self.s;s.day_off();original={p:p.read_bytes() for p in s.checkpoint_path.parent.iterdir()}
        with api(s,self.root/'saves') as (read,post):
            before=copy.deepcopy(s.core.snapshot());view=read()['finance_history'];self.assertEqual(view,read()['finance_history']);self.assertEqual(before,s.core.snapshot())
            saved=post('save_game')[1]['save_id'];self.assertEqual(post('day_off')[0],200);self.assertEqual(len(read()['finance_history']['rows']),2)
            self.assertEqual(post('load_game',save_id=saved)[0],200);self.assertEqual(read()['finance_history'],view)
        self.assertEqual(original,{p:p.read_bytes() for p in original})
