"""お客さんとの相性を考慮した自動割り当て。"""


def available_cats(core):
    active = ({item.cat_id for item in core.interactions.values()}
              if hasattr(core, 'interactions') else ({core.active.cat_id} if core.active else set()))
    return [cat for cat in core.cats.values()
            if core.activity(cat.id) == 'cafe' and cat.id in core.working_cats
            and cat.health_status == 'healthy' and not cat.cannot_continue and cat.stamina > 0
            and cat.id not in active]


def select(core, customer_id):
    if customer_id not in core.queue:
        raise ValueError('自動割り当てするお客さんが待機していません。')
    candidates = available_cats(core)
    if not candidates:
        raise ValueError('自動割り当てできる猫がいません。')
    from .cafe_preferences import match
    rows = [(cat, match(core, cat.id, customer_id)) for cat in candidates]
    cat, compatibility = min(rows, key=lambda row: (-int(row[1]['matched']), -row[0].stamina, row[0].id))
    return cat, compatibility


def record(core, customer_id, cat_id):
    cat, compatibility = select(core, customer_id)
    if cat.id != cat_id:
        raise ValueError('自動割り当ての選択が現在の相性・体力と一致しません。')
    core._tick_events = []
    core._emit('automatic_assignment', customer_id=customer_id, cat_id=cat_id,
               matched=compatibility['matched'], preference=compatibility['preference'],
               reason='preference_match' if compatibility['matched'] else 'stamina')
    core._record(dict(kind='automatic_assignment', customer_id=customer_id, cat_id=cat_id))

