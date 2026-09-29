"""新規ゲームの日末に一度だけ精算する店舗運営費。"""
import copy
import json
import math
from pathlib import Path


def rules(data=None):
    if data is None:data=json.loads((Path(__file__).resolve().parents[2]/'config/cafe_operating_cost.json').read_text())
    if (not isinstance(data,dict) or set(data)!={'base_cost','per_seat_cost'}
            or any(type(value) not in (int,float) or not math.isfinite(value) or value<0 for value in data.values())
            or data['base_cost']+data['per_seat_cost']<=0):
        raise ValueError('店舗運営費の設定が不正です。')
    return copy.deepcopy(data)


def initialize(core,selected=None):
    core.require_events_resolved()
    if (not core.compact or core.day!=1 or not core.can_set_shifts or core.operating_cost is not None
            or core.management is None):
        raise ValueError('店舗運営費は経営ルールが有効な新規ゲームの準備中に設定してください。')
    core.operating_cost=dict(rules=rules(selected),started_day=core.day,charges=[])
    core._tick_events=[];core._emit('operating_cost_enabled')
    core._record(dict(kind='initialize_operating_cost',rules=copy.deepcopy(core.operating_cost['rules'])))


def estimate(core,seat_count=None):
    if core.operating_cost is None:return 0
    count=seat_count if seat_count is not None else len(core.seats) if hasattr(core,'seats') else 1
    selected=core.operating_cost['rules']
    from .cafe_waiting_area import daily_cost
    return selected['base_cost']+selected['per_seat_cost']*count+daily_cost(core)


def charge(core):
    data=core.operating_cost
    if data is None:return
    if any(row['day']==core.day for row in data['charges']):raise ValueError('本日の店舗運営費は精算済みです。')
    count=len(core.seats) if hasattr(core,'seats') else 1;selected=data['rules'];total=estimate(core,count)
    row=dict(day=core.day,base=selected['base_cost'],seat_count=count,
             seat_cost=selected['per_seat_cost']*count,total=total)
    if core.waiting_area is not None:
        from .cafe_waiting_area import daily_cost
        row['facility_cost']=daily_cost(core)
    data['charges'].append(row);core.funds-=total
    core._emit('operating_cost_charged',**row)


def charged(core,day=None):
    if core.operating_cost is None:return 0
    return sum(row['total'] for row in core.operating_cost['charges'] if day is None or row['day']==day)


def validate(core,data):
    if (not isinstance(data,dict) or set(data)!={'rules','started_day','charges'}
            or type(data['started_day']) is not int or not 1<=data['started_day']<=core.day
            or not isinstance(data['charges'],list)):
        raise ValueError('店舗運営費の記録が不正です。')
    selected=rules(data['rules']);core.operating_cost=copy.deepcopy(data)
    closed_days=[row['day'] for row in core.day_results]
    if core.closed:closed_days.append(core.day)
    expected=[day for day in closed_days if day>=data['started_day']]
    if [row.get('day') for row in data['charges']]!=expected:raise ValueError('店舗運営費の精算日が不正です。')
    summaries={row['day']:row['summary'] for row in core.day_results}
    if core.closed:summaries[core.day]=core.summary()
    for row in data['charges']:
        fields={'day','base','seat_count','seat_cost','total'};summary=summaries[row['day']]
        count=summary.get('seat_count',1)
        expected_row=dict(day=row['day'],base=selected['base_cost'],seat_count=count,
                          seat_cost=selected['per_seat_cost']*count,
                          total=selected['base_cost']+selected['per_seat_cost']*count)
        if core.waiting_area is not None:
            from .cafe_waiting_area import purchased
            cost=core.waiting_area['rules']['daily_cost'] if purchased(core) and row['day']>=purchased(core)['day'] else 0
            fields.add('facility_cost');expected_row['facility_cost']=cost;expected_row['total']+=cost
        if set(row)!=fields or row!=expected_row or summary.get('operating_cost',0)!=row['total']:
            raise ValueError('店舗運営費の内訳が営業結果と一致しません。')
    return copy.deepcopy(data)
