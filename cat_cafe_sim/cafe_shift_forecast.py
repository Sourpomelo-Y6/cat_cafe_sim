"""営業準備用の目安。営業状態・乱数・履歴は変更しない。"""


def shift_forecast(core, cat_id):
    cat = core.cats[cat_id]
    previous = core.day_results[-1]['cats'].get(cat_id, {}) if core.day_results else {}
    actions = previous.get('service_ticks')
    result = dict(previous_actions=actions, work=None, rest=None,
                  sick=cat.health_status == 'sick', recovery_after=None)
    if core.shift_rules is None:
        return result
    rules = core.shift_rules

    def estimate(change):
        fatigue = max(0, min(rules.max_fatigue, cat.fatigue + change))
        probability = (core.health_rules.probability(fatigue)
                       if core.health_rules and not result['sick'] else None)
        return dict(fatigue=fatigue, probability=probability)

    from .core.cafe_traits import fatigue_change
    result['rest'] = estimate(fatigue_change(core,cat_id,False,0))
    if result['sick']:
        if core.health_rules:
            result['recovery_after'] = max(0, cat.recovery_days_remaining - 1)
    elif actions is not None:
        result['work'] = estimate(fatigue_change(core,cat_id,True,actions))
    return result


def estimate_text(value):
    if value is None:
        return '—'
    chance = f"{value['probability']:.1%}" if value['probability'] is not None else '判定なし'
    return f"{value['fatigue']:g} / {chance}"


def forecast_note(value):
    if value['sick']:
        remaining = value['recovery_after']
        if remaining is None:
            return '療養中は出勤できません。病気・療養ルールは未導入です。'
        return ('療養中は再発症判定を行いません。丸1日休むと閉店時に回復し、翌日から出勤を選べます。'
                if remaining == 0 else f'療養中は再発症判定を行いません。丸1日休むと残り療養{remaining}日になります。')
    if value['rest'] is None:
        return '出勤・疲労ルールは未導入です。設定を保存してから開き直すと予測を表示します。'
    if value['previous_actions'] is None:
        return '前日の接客行動数の記録がないため、出勤時の予測は表示していません。'
    return (f"前日の接客{value['previous_actions']}行動を基準にしています。"
            '当日の担当回数や交流時間によって、実際の疲労・発症確率は変わります。')
