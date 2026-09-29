"""確定済みの収入・支出から日次収支を導出する。"""
import math

EXPENSE_KEYS=('operating_cost','recruitment_expenses','expansion_expenses',
              'equipment_expenses','seat_equipment_expenses','waiting_area_expenses','store_event_expenses','kitten_expenses')


def values(summary):
    income=summary.get('revenue',0)+summary.get('dispatch_income',0)
    expenses=sum(summary.get(key,0) for key in EXPENSE_KEYS)
    net=income-expenses
    return dict(opening_funds=summary['funds']-net,total_income=income,
                total_expenses=expenses,net_cash_flow=net,closing_funds=summary['funds'])


def add(summary):
    summary.update(values(summary));return summary


def validate(core):
    if core.operating_cost is None:return
    rows=list(core.day_results)
    if core.closed:rows=rows+[core.day_result()]
    previous=core.config.initial_funds+core.management['grant']
    for day in rows:
        summary=day['summary'];expected=values(summary)
        if any(type(summary.get(key)) not in (int,float) or not math.isclose(summary[key],value,rel_tol=1e-12,abs_tol=1e-8)
               for key,value in expected.items()):
            raise ValueError('日次収支の内訳が一致しません。')
        if not math.isclose(summary['opening_funds'],previous,rel_tol=1e-12,abs_tol=1e-8):
            raise ValueError('日次収支の開始資金が前日の終了資金と一致しません。')
        previous=summary['closing_funds']
