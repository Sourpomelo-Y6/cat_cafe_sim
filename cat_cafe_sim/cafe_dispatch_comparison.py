"""新しい派遣の候補を、現在の猫と保存済み条件から閲覧用に比較する。"""
from .core.cafe_activities import destinations, dispatch_reason
from .core.cafe_traits import dispatch_terms
from .core.cafe_dispatch_match import terms as welcome_terms, description as welcome_description
from .core.cafe_dispatch_encounters import for_destination as encounter_for
from .core.cafe_dispatch_unlocks import description as unlock_description


def comparison_rows(session,cat_id):
    core=session.core
    if cat_id not in core.cats:raise ValueError('比較する猫を選んでください。')
    choices=destinations(core)
    if core.patron:choices.append(core.patron['rules']['destination'])
    rows=[]
    for destination in choices:
        terms=dispatch_terms(core,cat_id,destination['reward'])
        welcome=welcome_terms(core,cat_id,destination) or {}
        amount=terms['reward']+welcome.get('reward_bonus',0)
        reason='交流結果の保存を再試行してください。' if session.pending else dispatch_reason(core,cat_id,destination)
        detail=[f"{destination['name']}：{destination['days']}日",f"参加：{reason or '参加できます'}",
                f"必要特性：{destination.get('required_trait_name','指定なし')} / 疲労{destination['max_fatigue']:g}以下",
                unlock_description(core,destination['id']),welcome_description(core,cat_id,destination),
                f"報酬見込み：{amount:g}（特性・成長・歓迎補正込み、選択イベント前）",
                f"通常帰還時ストレス：＋{terms['stress']:g}"]
        encounter=encounter_for(destination)
        options=[]
        if encounter:
            detail.append(f"1日目の出来事：{encounter['title']}")
            cat=core.cats[cat_id]
            for choice in encounter['choices']:
                text=(f"{choice['label']}：報酬 {max(0,amount+choice['reward']):g}（{choice['reward']:+g}） / "
                      f"疲労 {choice['fatigue']:+g} / ストレス {choice['stress']:+g}")
                after=max(0,min(getattr(core.shift_rules,'max_fatigue',100),cat.fatigue+choice['fatigue']))
                text+=f"（現在の状態なら疲労 {cat.fatigue:g} → {after:g}"
                if core.management:
                    before=core.management['stress'][cat_id]
                    text+=f" / ストレス {before:g} → {max(0,min(100,before+choice['stress'])):g}）"
                else:text+=' / 経営ルールなし：ストレス変化は適用なし）'
                options.append(text);detail.append(text)
        else:detail.append('選択イベント：なし')
        from .core.cafe_items import for_destination as item_for, effect_text
        item=item_for(destination)
        if item:detail.append(f"アイテム報酬：{item['name']} ×1（{effect_text(item)}、受取後に使用）")
        from .core.cafe_dispatch_introduction import for_departure
        introduction=for_departure(core,destination,set())
        if introduction:detail.append(f"帰還受取後の猫紹介：{introduction['candidate']['name']} / 受け入れ費用 {introduction['candidate']['cost']:g}")
        if core.patron and destination['id']==core.patron['rules']['destination']['id']:
            detail.append(f"有力者満足度：＋{core.patron['rules']['gain']+welcome.get('satisfaction_bonus',0):g}（上限 {core.patron['rules']['target']:g}）")
        from .core.cafe_dispatch_trouble import DESTINATION_ID, probability
        if destination['id']==DESTINATION_ID and core.dispatch_trouble:
            trouble=core.dispatch_trouble
            detail.append(f"家出トラブル：{probability(core,cat_id)*100:g}% / 中断報酬0 / 捜索費 {trouble['search_cost']:g} または{trouble['missing_days']}日後の帰還待ち / 中断帰還時ストレスは{trouble['return_stress']:g}に設定（通常帰還の加算なし）")
        rows.append(dict(destination=destination,reason=reason,reward=amount,return_stress=terms['stress'],
                         options=options,detail='\n'.join(detail)))
    return rows
