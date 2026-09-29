"""派遣先の歓迎条件と、出発時に固定する追加報酬。"""
import copy
import math
from .cafe_preferences import FEATURES
from .cafe_growth import SPECIALIZATIONS,LABELS


def validate_rules(data):
    if (not isinstance(data,dict) or set(data)!={'feature','specialization','reward_bonus','satisfaction_bonus'}
            or data['feature'] not in FEATURES or data['specialization'] not in SPECIALIZATIONS
            or any(type(data[k]) not in (int,float) or not math.isfinite(data[k]) or data[k]<0
                   for k in ('reward_bonus','satisfaction_bonus'))):
        raise ValueError('派遣先の歓迎条件が不正です。')
    return copy.deepcopy(data)


def terms(core,cat_id,destination,day=None):
    rules=destination.get('welcome')
    if rules is None:return None
    rules=validate_rules(rules)
    growth=(core.growth or {}).get('cats',{}).get(cat_id,{})
    feature=rules['feature'] in (core.cat_features or {}).get(cat_id,[])
    specialization=(growth.get('specialization')==rules['specialization']
                    and (day is None or growth.get('selected_day',core.day)<=day))
    count=int(feature)+int(specialization)
    return dict(feature_matched=feature,specialization_matched=specialization,
                reward_bonus=count*rules['reward_bonus'],satisfaction_bonus=count*rules['satisfaction_bonus'])


def description(core,cat_id,destination):
    row=terms(core,cat_id,destination)
    if row is None:return '歓迎条件：なし'
    rules=destination['welcome']
    return (f"歓迎条件：{FEATURES[rules['feature']][0]} {'一致' if row['feature_matched'] else '不一致'} / "
            f"得意分野 {LABELS[rules['specialization']]} {'一致' if row['specialization_matched'] else '不一致'}"
            f" / 追加報酬 {row['reward_bonus']:g} / 追加満足度 {row['satisfaction_bonus']:g}")
