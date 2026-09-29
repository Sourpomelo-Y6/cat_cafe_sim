"""派遣の保存済み条件・成果から閲覧用の内訳を導出する。"""
from .core.cafe_traits import effect
from .core.cafe_dispatch_encounters import reward_delta
from .core.cafe_activities import reward


def result_rows(core,event):
    base=event['destination']['reward']
    trait=effect(core,event['cat_id'],'dispatch_reward')
    growth=event.get('growth_multiplier',1)
    welcome=event.get('welcome_match',{})
    rows=[('状態',{'travelling':'派遣中（報酬見込み）','waiting':'帰還・受取待ち','resolved':'受取済み'}[event['status']]),
          ('出発日',f"{event['started_day']}日目"),
          ('受取日',f"{event['resolved_day']}日目" if event['resolved_day'] is not None else '未受取'),
          ('基本報酬',f'{base:g}'),('特性補正',f'×{trait:g}（{base*(trait-1):+g}）'),
          ('成長補正',f'×{growth:g}（{base*trait*(growth-1):+g}）'),
          ('歓迎ボーナス',f"{welcome.get('reward_bonus',0):+g}"),
          ('イベント増減',f'{reward_delta(event):+g}'),
          ('資金報酬合計',f'{reward(core,event):g}')]
    raw=base*trait*growth+welcome.get('reward_bonus',0)+reward_delta(event)
    if raw<0:rows.append(('下限処理',f'{-raw:+g}（報酬は最低0）'))
    if welcome:
        from .core.cafe_preferences import FEATURES
        from .core.cafe_growth import LABELS
        selected=event['destination']['welcome']
        rows.extend([('歓迎する特徴',FEATURES[selected['feature']][0]+('：一致' if welcome['feature_matched'] else '：不一致')),
                     ('歓迎する得意分野',LABELS[selected['specialization']]+('：一致' if welcome['specialization_matched'] else '：不一致'))])
    else:rows.append(('歓迎条件','設定なし'))
    if 'item_reward' in event:rows.append(('アイテム報酬',event['item_reward']['name']+' ×1'))
    offered = event.get('introduction')
    if offered:
        rows.append(('紹介された猫', offered['candidate']['name']))
        rows.append(('猫紹介の状態', {'scheduled': '帰還報酬受取後の準備で確認', 'waiting': '回答待ち', 'accepted': '迎えた', 'declined': '見送り'}[offered['status']]))
        rows.append(('紹介猫の受け入れ費用', f"{offered['candidate']['cost']:g}（迎える場合だけ支払い）"))
    from .core.cafe_patron import DESTINATION_ID
    if core.patron and event['destination']['id']==DESTINATION_ID:
        rules=core.patron['rules'];gain=rules['gain']+welcome.get('satisfaction_bonus',0)
        rows.extend([('基本満足度',f"{rules['gain']:g}"),('歓迎の追加満足度',f"{welcome.get('satisfaction_bonus',0):g}")])
        if event['status']=='resolved':
            received=sorted((e for e in core.activities['events'].values()
                             if e['status']=='resolved' and e['destination']['id']==DESTINATION_ID),key=lambda e:e['resolved_day'])
            total=0
            for e in received:
                before=total;total=min(rules['target'],total+rules['gain']+e.get('welcome_match',{}).get('satisfaction_bonus',0))
                if e['id']==event['id']:
                    rows.append(('満足度の実増加',f'{total-before:g}（{before:g} → {total:g} / 上限{rules["target"]:g}）'));break
        else:rows.append(('満足度の増加見込み',f'{gain:g}（目標上限まで）'))
    return rows


def result_text(core,event):
    return '\n'.join(f'{label}：{value}' for label,value in result_rows(core,event))
