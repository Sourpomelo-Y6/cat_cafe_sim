"""新規ゲームの派遣先解放。達成時の記録を保持する。"""
import copy
import json
import math
from pathlib import Path

LEGACY_IDS={'shopping_street_event','out_of_town_visit'}
EXERCISE_ID='cat_exercise_class'
READING_ID='quiet_reading_salon'
PHOTO_ID='cat_photo_studio'
TRIAL_ID='cat_product_trial'
MUSEUM_ID='small_art_museum'
SPECIAL_DESTINATIONS={EXERCISE_ID:('hardy','体力自慢'),READING_ID:('relaxed','のんびり屋'),PHOTO_ID:('hospitality','接客好き'),TRIAL_ID:('hardworking','働き者'),MUSEUM_ID:('easygoing','マイペース')}
IDS=LEGACY_IDS | set(SPECIAL_DESTINATIONS)


def rules(data=None):
    if data is None:data=json.loads((Path(__file__).resolve().parents[2]/'config/cafe_dispatch_unlocks.json').read_text())
    if not isinstance(data,dict) or not LEGACY_IDS<=set(data)<=IDS:raise ValueError('派遣解放設定が不正です。')
    for key,row in data.items():
        if key==MUSEUM_ID:
            if not isinstance(row,dict) or set(row)!={'stage','destination'} or type(row['stage']) is not int or row['stage']!=2:
                raise ValueError('美術館の解放条件が不正です。')
            continue
        if (not isinstance(row,dict) or set(row) not in ({'popularity','returns'}, {'popularity','returns','destination'})
                or type(row['returns']) is not int or row['returns']<1
                or type(row['popularity']) not in (int,float) or not math.isfinite(row['popularity']) or row['popularity']<=0):
            raise ValueError('派遣解放条件が不正です。')
    for key, row in data.items():
        if key in SPECIAL_DESTINATIONS:
            from .cafe_activities import destination
            selected = destination(row.get('destination', {}))
            trait_id,trait_name=SPECIAL_DESTINATIONS[key]
            if (selected['id'] != key or selected.get('required_trait') != trait_id
                    or selected.get('required_trait_name') != trait_name):
                raise ValueError('特性に応じた派遣先の参加条件が不正です。')
        elif 'destination' in row:
            raise ValueError('従来の派遣解放設定に派遣先は指定できません。')
    return copy.deepcopy(data)


def exercise_destination(core):
    return saved_destination(core,EXERCISE_ID)


def reading_destination(core):
    return saved_destination(core,READING_ID)


def photo_destination(core):
    return saved_destination(core,PHOTO_ID)


def trial_destination(core):
    return saved_destination(core,TRIAL_ID)


def saved_destination(core,destination_id):
    data = core.dispatch_unlocks
    return copy.deepcopy(data['rules'][destination_id]['destination']) if data and destination_id in data['rules'] else None


def validate_destinations(core):
    for event in (core.activities or {}).get('events', {}).values():
        key=event['destination']['id']
        if key in SPECIAL_DESTINATIONS and event['destination'] != saved_destination(core,key):
            raise ValueError('特性に応じた派遣記録と開始時の設定が一致しません。')


def museum_destination(core):
    return saved_destination(core,MUSEUM_ID)


def eligible(core,row):
    if 'stage' in row:
        from .cafe_expansion import second_popularity_cleared
        return second_popularity_cleared(core)
    return core.management['popularity']>=row['popularity'] and count(core)>=row['returns']


def second_cleared_day(core):
    return ([*core.goal.get('history',[]),core.goal])[1]['resolved_day']


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
        if key not in data['unlocked'] and eligible(core,row):
            data['unlocked'][key]=dict(day=core.day,popularity=popularity,returns=returns)
            core._emit('dispatch_destination_unlocked',destination_id=key)


def reason(core,destination_id):
    data=core.dispatch_unlocks
    if data is None or destination_id not in data['rules'] or destination_id in data['unlocked']:return ''
    row=data['rules'][destination_id]
    if 'stage' in row:return '未解放：人気第2段階の達成が必要です。'
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
                or type(row['returns']) is not int or not selected[key].get('returns',0)<=row['returns']<=count(core)
                or type(row['popularity']) not in (int,float) or not math.isfinite(row['popularity'])
                or row['popularity']<selected[key].get('popularity',0)):raise ValueError('派遣解放の達成記録が不正です。')
    for key,row in data['unlocked'].items():
        if 'stage' in selected[key] and (not eligible(core,selected[key]) or row['day']<second_cleared_day(core)):
            raise ValueError('人気第2段階の達成前に美術館が解放されています。')
    if not core.management['game_over']:
        for key,row in selected.items():
            if key not in data['unlocked'] and eligible(core,row):
                raise ValueError('達成済みの派遣先解放記録がありません。')
    for e in (core.activities or {}).get('events',{}).values():
        key=e['destination']['id']
        if key in selected and (key not in data['unlocked'] or e['started_day']<data['unlocked'][key]['day']):
            raise ValueError('解放前の派遣記録があります。')
    return copy.deepcopy(data)
