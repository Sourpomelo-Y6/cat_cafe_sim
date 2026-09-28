"""来店停止を繰り返した客の信頼回復と永久離脱。"""
import copy
import json
import math
from pathlib import Path


def rules(data=None):
    if data is None:
        data = json.loads((Path(__file__).resolve().parents[2] / 'config/cafe_customer_trust.json').read_text())
    if (not isinstance(data, dict) or set(data) != {'warning_suspensions','recovery_score','popularity_loss'}
            or type(data['warning_suspensions']) is not int or data['warning_suspensions'] < 2):
        raise ValueError('信頼回復の設定が不正です。')
    for key in ('recovery_score','popularity_loss'):
        if type(data[key]) not in (int,float) or not math.isfinite(data[key]) or data[key] < 0:
            raise ValueError('信頼回復の設定が不正です。')
    return copy.deepcopy(data)


def initialize(core, selected=None):
    core.require_events_resolved()
    if (not core.compact or core.day != 1 or not core.can_set_shifts or core.customer_trust is not None
            or core.customer_discontent is None or core.management is None):
        raise ValueError('信頼回復は新規ゲームの準備中に設定してください。')
    selected = rules(selected)
    if selected['recovery_score'] >= core.customer_discontent['rules']['threshold']:
        raise ValueError('信頼回復後の不満は上限未満にしてください。')
    core.customer_trust = dict(rules=selected, customers={}, events={})
    core._tick_events=[]
    core._record(dict(kind='initialize_customer_trust', rules=selected))


def waiting(core):
    return [event for event in core.customer_trust['events'].values() if event['status']=='waiting'] if core.customer_trust else []


def consider_suspension(core, customer_id):
    data = core.customer_trust
    if data is None:
        return
    suspensions = len(core.customer_discontent['customers'][customer_id]['suspensions'])
    customer = data['customers'].get(customer_id)
    if suspensions < data['rules']['warning_suspensions'] or customer and customer['status'] in ('waiting','recovery','departed'):
        return
    event_id=f'trust-{core.day}-{customer_id}'
    event=dict(id=event_id,customer_id=customer_id,day=core.day,suspensions=suspensions,
               status='waiting',choice=None,resolved_day=None,outcome=None)
    data['events'][event_id]=event
    data['customers'][customer_id]=dict(status='waiting',event_id=event_id,departed_day=None,reason=None)
    core._emit('customer_trust_warning',event_id=event_id,customer_id=customer_id,suspensions=suspensions)


def present(core):
    if core.customer_trust is None:return
    for customer_id in sorted(core.customer_discontent['customers']):
        consider_suspension(core,customer_id)


def _depart(core, customer_id, reason, event):
    customer=core.customer_trust['customers'][customer_id]
    customer.update(status='departed',departed_day=core.day,reason=reason)
    event.update(status='resolved',resolved_day=core.day,outcome='departed')
    before=core.management['popularity']
    core.management['popularity']=max(0,before-core.customer_trust['rules']['popularity_loss'])
    from .cafe_management import check_end
    check_end(core)
    core._emit('customer_departed',customer_id=customer_id,reason=reason,
               popularity_before=before,popularity=core.management['popularity'])


def resolve(core,event_id,choice):
    core.require_running()
    if not core.customer_trust or event_id not in core.customer_trust['events'] or choice not in ('recover','ignore'):
        raise ValueError('信頼回復イベントと選択肢を確認してください。')
    event=core.customer_trust['events'][event_id]
    if event['status']!='waiting':
        if event['choice']==choice:return
        raise ValueError('解決済みの信頼回復方針は変更できません。')
    event['choice']=choice
    customer=core.customer_trust['customers'][event['customer_id']]
    if choice=='recover':
        event['status']='recovery';customer['status']='recovery'
        core._emit('customer_trust_recovery_started',event_id=event_id,customer_id=event['customer_id'])
    else:
        _depart(core,event['customer_id'],'ignored',event)
    core._record(dict(kind='resolve_customer_trust',event_id=event_id,choice=choice))


def apply_service(core,result,satisfaction):
    if core.customer_trust is None or satisfaction is None:return
    customer=core.customer_trust['customers'].get(result['customer_id'])
    if not customer or customer['status']!='recovery':return
    event=core.customer_trust['events'][customer['event_id']]
    if satisfaction['level']=='satisfied':
        value=core.customer_discontent['customers'][result['customer_id']]
        value['score']=core.customer_trust['rules']['recovery_score'];value['score_day']=core.day
        customer.update(status='stable',event_id=None,reason=None)
        event.update(status='resolved',resolved_day=core.day,outcome='recovered')
        core._emit('customer_trust_recovered',customer_id=result['customer_id'],score=value['score'])
    elif satisfaction['level']=='dissatisfied':
        _depart(core,result['customer_id'],'recovery_failed',event)


def available(core,customer_id,day=None):
    customer=(core.customer_trust or {}).get('customers',{}).get(customer_id)
    day=core.day if day is None else day
    return (not customer or customer['status']!='departed' or day<customer['departed_day']
            or day==customer['departed_day'] and customer['reason']=='recovery_failed')


def row(core,customer_id):
    if core.customer_trust is None:return None
    return copy.deepcopy(core.customer_trust['customers'].get(customer_id,
                         dict(status='stable',event_id=None,departed_day=None,reason=None)))


def losses(core,day=None):
    if core.customer_trust is None:return 0
    rows=(c for c in core.customer_trust['customers'].values() if c['status']=='departed')
    if day is not None:rows=(c for c in rows if c['departed_day']==day)
    return sum(core.customer_trust['rules']['popularity_loss'] for _ in rows)


def validate(core,data):
    if not isinstance(data,dict) or set(data)!={'rules','customers','events'} or not isinstance(data['customers'],dict) or not isinstance(data['events'],dict):
        raise ValueError('信頼回復の記録が不正です。')
    selected=rules(data['rules'])
    if selected['recovery_score']>=core.customer_discontent['rules']['threshold']:
        raise ValueError('信頼回復の設定が不正です。')
    fields={'status','event_id','departed_day','reason'}
    event_fields={'id','customer_id','day','suspensions','status','choice','resolved_day','outcome'}
    for key,customer in data['customers'].items():
        if (not isinstance(key,str) or not isinstance(customer,dict) or set(customer)!=fields
                or customer['status'] not in ('waiting','recovery','stable','departed')):
            raise ValueError('お客さんの信頼状態が不正です。')
        event_id=customer['event_id']
        if customer['status'] in ('waiting','recovery') and event_id not in data['events']:
            raise ValueError('信頼回復イベントが見つかりません。')
        if customer['status']=='departed':
            if type(customer['departed_day']) is not int or not 1<=customer['departed_day']<=core.day or customer['reason'] not in ('ignored','recovery_failed'):
                raise ValueError('永久離脱の記録が不正です。')
        elif customer['departed_day'] is not None or customer['reason'] is not None:
            raise ValueError('信頼状態と永久離脱が矛盾しています。')
    for key,event in data['events'].items():
        periods=(core.customer_discontent['customers'].get(event.get('customer_id'),{}).get('suspensions',[])
                 if isinstance(event,dict) else [])
        if (not isinstance(event,dict) or set(event)!=event_fields or event['id']!=key
                or key!=f"trust-{event['day']}-{event['customer_id']}"
                or event['customer_id'] not in data['customers'] or type(event['day']) is not int
                or not 1<=event['day']<=core.day or type(event['suspensions']) is not int
                or event['suspensions']<selected['warning_suspensions']
                or event['suspensions']!=sum(period['day']<event['day'] for period in periods)):
            raise ValueError('信頼回復イベントが不正です。')
        if event['status']=='waiting':
            if event['choice'] is not None or event['resolved_day'] is not None or event['outcome'] is not None:raise ValueError('未回答の信頼回復イベントが不正です。')
        elif event['status']=='recovery':
            if event['choice']!='recover' or event['resolved_day'] is not None or event['outcome'] is not None:raise ValueError('信頼回復中の記録が不正です。')
        elif event['status']=='resolved':
            if event['choice'] not in ('recover','ignore') or type(event['resolved_day']) is not int or not event['day']<=event['resolved_day']<=core.day or event['outcome'] not in ('recovered','departed'):raise ValueError('信頼回復結果が不正です。')
        else:raise ValueError('信頼回復イベントの状態が不正です。')
    for key,customer in data['customers'].items():
        related=[event for event in data['events'].values() if event['customer_id']==key]
        latest=max(related,key=lambda event:event['day']) if related else None
        if not latest:raise ValueError('お客さんの信頼状態にイベントがありません。')
        if customer['status'] in ('waiting','recovery') and (customer['event_id']!=latest['id'] or latest['status']!=customer['status']):
            raise ValueError('お客さんの信頼状態とイベントが一致しません。')
        if customer['status']=='stable' and (customer['event_id'] is not None or latest['outcome']!='recovered'):
            raise ValueError('信頼回復結果が一致しません。')
        if customer['status']=='departed':
            expected_choice='ignore' if customer['reason']=='ignored' else 'recover'
            if customer['event_id']!=latest['id'] or latest['outcome']!='departed' or latest['choice']!=expected_choice or latest['resolved_day']!=customer['departed_day']:
                raise ValueError('永久離脱と信頼回復イベントが一致しません。')
    return copy.deepcopy(data)
