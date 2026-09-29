"""新規ゲームの派遣先解放。達成時の記録を保持する。"""
import copy
import json
import math
from pathlib import Path

IDS=('shopping_street_event','out_of_town_visit')


def rules(data=None):
    if data is None:data=json.loads((Path(__file__).resolve().parents[2]/'config/cafe_dispatch_unlocks.json').read_text())
    if not isinstance(data,dict) or set(data)!=set(IDS):raise ValueError('派遣解放設定が不正です。')
    for row in data.values():
        if (not isinstance(row,dict) or set(row)!={'popularity','returns'}
                or type(row['returns']) is not int or row['returns']<1
                or type(row['popularity']) not in (int,float) or not math.isfinite(row['popularity']) or row['popularity']<=0):
            raise ValueError('派遣解放条件が不正です。')
    return copy.deepcopy(data)


def count(core):
    from .cafe_dispatch_trouble import interrupted
    return sum(e['status']=='resolved' and not interrupted(e) for e in (core.activities or {}).get('events',{}).values())


def initialize(core,selected=None):
    core.require_events_resolved()
    if not core.compact or core.day!=1 or not core.can_set_shifts or core.management is None or core.dispatch_unlocks is not None:
        raise ValueError('派遣解放は新規ゲームの準備中に導入してください。')
    core.dispatch_unlocks=dict(rules=rules(selected),unlocked={})
    core._tick_events=[];core._record(dict(kind='initialize_dispatch_unlocks',rules=core.dispatch_unlocks['rules']))


def update(core):
    data=core.dispatch_unlocks
    if data is None or not core.management or core.management['game_over']:return
    popularity=core.management['popularity'];returns=count(core)
    for key,row in data['rules'].items():
        if key not in data['unlocked'] and popularity>=row['popularity'] and returns>=row['returns']:
            data['unlocked'][key]=dict(day=core.day,popularity=popularity,returns=returns)
            core._emit('dispatch_destination_unlocked',destination_id=key)


def reason(core,destination_id):
    data=core.dispatch_unlocks
    if data is None or destination_id not in data['rules'] or destination_id in data['unlocked']:return ''
    row=data['rules'][destination_id]
    return f"未解放：人気 {core.management['popularity']:g}/{row['popularity']:g}・派遣報酬受取 {count(core)}/{row['returns']}回"


def description(core,destination_id):
    data=core.dispatch_unlocks
    if data is None:return '派遣先の段階解放なし（従来の参加条件）'
    if destination_id not in data['rules']:return '最初から利用可能（参加条件あり）'
    problem=reason(core,destination_id)
    return problem or f"{data['unlocked'][destination_id]['day']}日目に解放済み"


def validate(core,data):
    if not isinstance(data,dict) or set(data)!={'rules','unlocked'} or not isinstance(data['unlocked'],dict):
        raise ValueError('派遣解放記録が不正です。')
    selected=rules(data['rules'])
    if core.management is None or not set(data['unlocked'])<=set(selected):raise ValueError('派遣解放記録が不正です。')
    for key,row in data['unlocked'].items():
        if (not isinstance(row,dict) or set(row)!={'day','popularity','returns'}
                or type(row['day']) is not int or not 1<=row['day']<=core.day
                or type(row['returns']) is not int or not selected[key]['returns']<=row['returns']<=count(core)
                or type(row['popularity']) not in (int,float) or not math.isfinite(row['popularity'])
                or row['popularity']<selected[key]['popularity']):raise ValueError('派遣解放の達成記録が不正です。')
    if not core.management['game_over']:
        for key,row in selected.items():
            if key not in data['unlocked'] and core.management['popularity']>=row['popularity'] and count(core)>=row['returns']:
                raise ValueError('達成済みの派遣先解放記録がありません。')
    for e in (core.activities or {}).get('events',{}).values():
        key=e['destination']['id']
        if key in selected and (key not in data['unlocked'] or e['started_day']<data['unlocked'][key]['day']):
            raise ValueError('解放前の派遣記録があります。')
    return copy.deepcopy(data)
