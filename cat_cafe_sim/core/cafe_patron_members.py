"""任意の追加有力者。出発時の条件・加点を固定し、保存済み設定で検証する。"""
import copy
import math

IDS = ('patron_moody_visit', 'patron_strict_visit')


def validate_rules(rows):
    from .cafe_preferences import FEATURES
    from .cafe_growth import SPECIALIZATIONS
    if not isinstance(rows, list) or len(rows) != 2 or [r.get('id') for r in rows if isinstance(r, dict)] != list(IDS):
        raise ValueError('追加有力者は気分型・厳格型の2人を指定してください。')
    for row in rows:
        if set(row) != {'id','name','target','gain','unmatched_gain','conditions'} or not isinstance(row['name'], str) or not row['name'].strip():
            raise ValueError('追加有力者の設定が不正です。')
        if any(type(row[k]) not in (int,float) or not math.isfinite(row[k]) or row[k] < 0 for k in ('target','gain','unmatched_gain')) or not 0 <= row['unmatched_gain'] < row['gain'] or row['target'] <= 0:
            raise ValueError('追加有力者の満足度設定が不正です。')
        if not isinstance(row['conditions'], list) or not row['conditions']:
            raise ValueError('有力者の希望を指定してください。')
        if row['id'] == IDS[1] and (row['unmatched_gain'] != 0 or len(row['conditions']) != 1):
            raise ValueError('厳格な有力者は固定条件・不一致加点0です。')
        for condition in row['conditions']:
            if not isinstance(condition, dict) or not condition or not set(condition) <= {'feature','specialization'}:
                raise ValueError('有力者の希望条件が不正です。')
            if ('feature' in condition and (not isinstance(condition['feature'], str) or condition['feature'] not in FEATURES)) or ('specialization' in condition and (not isinstance(condition['specialization'], str) or condition['specialization'] not in SPECIALIZATIONS)):
                raise ValueError('有力者の希望条件が不正です。')
    return copy.deepcopy(rows)


def member(core, destination_id, selected=None):
    selected = selected or (core.patron or {}).get('rules', {})
    return next((r for r in selected.get('members', []) if r['id'] == destination_id), None)


def destination(core, row, selected=None):
    selected = selected or core.patron['rules']
    trip = copy.deepcopy(selected['destination'])
    trip.pop('welcome', None)
    trip.update(id=row['id'], name=row['name']+'への訪問')
    return trip


def terms(core, cat_id, destination_id, day=None, selected=None):
    row = member(core, destination_id, selected)
    if row is None:
        return None
    events = (core.activities or {}).get('events', {}).values()
    number = sum(e['destination']['id']==destination_id and
                 (e['status']=='resolved' if day is None else e['started_day'] < day) for e in events)
    index = number % len(row['conditions'])
    condition = row['conditions'][index]
    growth = (core.growth or {}).get('cats', {}).get(cat_id, {})
    matched = (('feature' not in condition or condition['feature'] in (core.cat_features or {}).get(cat_id, [])) and
               ('specialization' not in condition or (growth.get('specialization') == condition['specialization'] and
                 (day is None or growth.get('selected_day', core.day) <= day))))
    return dict(member_id=destination_id, condition_index=index, condition=copy.deepcopy(condition),
                matched=matched, gain=row['gain'] if matched else row['unmatched_gain'])


def condition_text(condition):
    from .cafe_preferences import FEATURES
    from .cafe_growth import LABELS
    names = ([FEATURES[condition['feature']][0]] if 'feature' in condition else []) + ([LABELS[condition['specialization']]] if 'specialization' in condition else [])
    return '・'.join(names)


def description(core, cat_id, destination_id):
    row = terms(core, cat_id, destination_id)
    if row is None:
        return ''
    condition = row['condition']
    return f"現在の希望：{condition_text(condition)}（すべて必要） / {'一致' if row['matched'] else '不一致'} / 満足度＋{row['gain']:g}（出発時に固定）"


def validate_events(core, selected):
    scores = dict.fromkeys((r['id'] for r in selected.get('members', [])), 0)
    for event in (core.activities or {}).get('events', {}).values():
        key = event['destination']['id']
        row = member(core, key, selected)
        if key not in IDS:
            if 'patron_match' in event:
                raise ValueError('有力者条件の対象が不正です。')
            continue
        if row is None or event['destination'] != destination(core, row, selected):
            raise ValueError('追加有力者の派遣設定が一致しません。')
        expected = terms(core, event['cat_id'], key, event['started_day'], selected)
        match = event.get('patron_match')
        if (not isinstance(match, dict) or match != expected or type(match.get('matched')) is not bool
                or type(match.get('condition_index')) is not int
                or type(match.get('gain')) not in (int, float)):
            raise ValueError('出発時の有力者条件・満足度が一致しません。')
        other = [e for e in core.activities['events'].values() if e['id'] != event['id'] and e['destination']['id'] == key]
        if any(e['started_day']==event['started_day'] or (e['started_day'] < event['started_day'] and
               (e['resolved_day'] is None or e['resolved_day'] > event['started_day'])) for e in other):
            raise ValueError('追加有力者の訪問が重複しています。')
        if event['status']=='resolved':
            scores[key] = min(row['target'], scores[key]+expected['gain'])
    return scores
