"""保存済みの出来事を猫別に表示する。新しい履歴や推定時刻は保存しない。"""


def cat_events(core, cat_id):
    from .core.cafe_dispatch_encounters import selected
    rows = []

    def add(day, kind, target, result):
        rows.append((day, kind, target, result))

    recruitment = core.recruitment
    if recruitment and cat_id in recruitment['accepted']:
        row = recruitment['candidates'][cat_id]
        add(recruitment['accepted'][cat_id], '加入', '保護猫の受け入れ', f"初期費用 {row['cost']:g}")
    if core.pet_shop and cat_id in core.pet_shop['accepted']:
        row = core.pet_shop['candidates'][cat_id]
        add(core.pet_shop['accepted'][cat_id], '加入', 'ペットショップ', f"購入費 {row['cost']:g}")
    request = core.intake_request
    if request and request['status'] == 'accepted' and request['rules']['cat_id'] == cat_id:
        add(request['resolved_day'], '加入', '保護猫の受け入れ依頼', f"初期費用 {request['rules']['candidate']['cost']:g}")

    for event in (core.activities or {}).get('events', {}).values():
        offered = event.get('introduction')
        if offered and offered['status'] == 'accepted' and offered['cat_id'] == cat_id:
            add(offered['resolved_day'], '加入', event['destination']['name'] + 'からの紹介', f"初期費用 {offered['candidate']['cost']:g}")
        if offered and offered['presented_day'] is not None and event['cat_id'] == cat_id:
            result = {'waiting': '回答待ち', 'accepted': '迎えた', 'declined': '見送り'}[offered['status']]
            add(offered['presented_day'], '猫の紹介', event['destination']['name'], offered['candidate']['name'] + ' / ' + result)
    for event in (core.activities or {}).get('events', {}).values():
        if event['cat_id'] != cat_id:
            continue
        place = event['destination']['name']
        add(event['started_day'], '派遣出発', place, f"予定期間 {event['destination']['days']}日")
        trouble = event.get('trouble')
        if trouble and trouble['missing_day'] is not None:
            add(trouble['missing_day'], '派遣中の家出', place, '派遣中断・報酬0')
            if trouble['choice']:
                add(trouble['choice_day'], '家出トラブルへの対応', place, ('捜索して連れ戻す' if trouble['choice']=='search' else '帰還を待つ')+f" / 捜索費 {trouble['cost']:g}")
        encounter = event.get('encounter')
        if encounter and encounter['status'] != 'scheduled':
            add(encounter['occurred_day'], '派遣中の出来事', place, encounter['rules']['title'] + ('（回答待ち）' if encounter['status']=='waiting' else '（回答済み）'))
            choice = selected(event)
            if choice:
                changes = encounter['changes']
                result = f"{choice['label']} / 帰還報酬の増減 {choice['reward']:+g} / 疲労 {changes['fatigue_before']:g} → {changes['fatigue_after']:g}"
                result += (f" / ストレス {changes['stress_before']:g} → {changes['stress_after']:g}" if changes['stress_before'] is not None else ' / ストレス未導入')
                add(encounter['resolved_day'], '派遣イベントへの回答', place, result)
        if event['status'] in ('waiting', 'resolved'):
            add(event['occurred_day'], '派遣帰還', place, '報酬受取待ち' if event['status']=='waiting' else '報酬受取済み')
        if event['status'] == 'resolved':
            from .cafe_dispatch_results import result_text
            result = result_text(core,event).replace('\n',' / ')
            add(event['resolved_day'], '帰還報酬の受取', place, result)

    management = core.management
    for event in (management or {}).get('events', {}).values():
        if event['cat_id'] != cat_id:
            continue
        # 人気の実減少量は保存されていないため、設定値から推定して表示しない。
        add(event['departed_day'], '家出', '店外', '帰還済み' if event['status']=='resolved' else '帰還確認待ち' if event['status']=='waiting' else '行方不明')
        if event['status'] in ('waiting', 'resolved'):
            day = event['departed_day'] + management['rules']['missing_days']
            add(day, '家出猫の帰還', 'お店', '帰還・費用の確認待ち' if event['status']=='waiting' else '帰還確認済み')
        if event['status'] == 'resolved':
            result = f"子猫の引き渡し費用 {event['cost']:g}" if event['kitten'] else '子猫の引き渡しなし / 費用0'
            add(event['resolved_day'], '家出猫の帰還確認', 'お店', result)

    for event in (core.adoption or {}).get('events', {}).values():
        if event['cat_id'] != cat_id:
            continue
        add(event['day'], '譲渡の申し出', event['customer_id'], '回答待ち' if event['status']=='waiting' else '回答済み')
        if event['status'] == 'resolved':
            add(event['resolved_day'], '譲渡への回答', event['customer_id'], '譲渡成立' if event['choice']=='accept' else '見送り')

    for use in core.item_uses:
        if use['cat_id'] != cat_id:
            continue
        from .core.cafe_items import reward_for_source
        item=reward_for_source(core,use['source'])['item']
        add(use['day'], 'ケア用品の使用', item['name'], f"1個使用 / ストレス {use['before']:g} → {use['after']:g}")
    growth=(core.growth or {}).get('cats',{}).get(cat_id)
    if growth and growth['specialization']:
        from .core.cafe_growth import LABELS
        add(growth['selected_day'],'得意分野の選択','成長',LABELS[growth['specialization']])
        if growth.get('mastery'):
            from .core.cafe_growth import GROUP_LABELS
            add(growth['mastery_selected_day'],'得意な交流の選択','成長',GROUP_LABELS[growth['mastery']])
        if growth.get('type_mastery'):
            from .core.cafe_growth import type_label
            add(growth['type_mastery_selected_day'],'得意な行動の選択','成長',type_label(growth['type_mastery']))
        if growth.get('second_type_mastery'):
            from .core.cafe_growth import type_label
            add(growth['second_type_mastery_selected_day'],'2つ目の得意な行動の選択','成長',type_label(growth['second_type_mastery']))
    # 同日の種類をまたぐ厳密な時系列は記録されていない。日付だけで安定ソートする。
    return sorted(rows, key=lambda row: row[0])
