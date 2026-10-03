"""自動プレイの目標別成果と、閉店済み・未閉店の収支を読み取り専用で集計する。"""
import copy

from .core import cafe_bond_goal, cafe_player


def completed_window(core, result, days):
    from .autoplay_evaluation import collect
    rows = list(core.day_results)
    if core.closed:
        rows.append(core.day_result())
    if not 1 <= days <= len(rows):
        raise ValueError('閉店済み日数の範囲で比較してください。')
    projection = copy.copy(core)
    projection.day_results = rows[:days]
    projection.closed = False
    projection.funds = rows[days-1]['summary']['closing_funds']
    metrics = collect(projection, result)['metrics']
    last = rows[days-1]
    metrics['seats'] = last['summary']['seat_count']
    metrics['final_popularity'] = last['summary']['popularity']
    metrics['runaways'] = sum(event['departed_day'] <= last['day']
                              for event in core.management['events'].values())
    return metrics


def objective_result(core, objective):
    data = {'popularity': core.goal, 'bond': core.bond_goal, 'patron': core.patron}[objective]
    result = dict(objective=objective, status=data['status'], resolved_day=data['resolved_day'])
    if objective == 'bond':
        events = [event['result'] for row in core.operations for event in row['events']
                  if event['kind'] == 'player_completed']
        affinity = cafe_player.state(core)['affinity']
        cats = {}
        for key, cat in core.cats.items():
            completed = [row for row in events if row['cat_id'] == key]
            cats[key] = dict(affinity=affinity[key], stamina=cat.stamina,
                            activity=core.activity(key), sets=len(completed),
                            affinity_gain=sum(row['affinity_delta'] for row in completed),
                            stamina_spent=sum(row['stamina_spent'] for row in completed),
                            stamina_recovered=sum(row['stamina_recovered'] for row in completed),
                            remaining_stamina=[row['stamina'] for row in completed])
        result.update(rules=copy.deepcopy(data['rules']), qualifying=len(cafe_bond_goal.qualifying(core)),
                      sets=len(events), cats=cats,
                      affinity_gain=sum(row['affinity_delta'] for row in events),
                      stamina_spent=sum(row['stamina_spent'] for row in events),
                      stamina_recovered=sum(row['stamina_recovered'] for row in events),
                      remaining_stamina=[row['stamina'] for row in events],
                      simultaneous_count=sum(row['simultaneous_count'] for row in events))
    elif objective == 'patron':
        members = {}
        rules = data['rules']
        for row in [dict(id=rules['destination']['id'], name=rules['name'], target=rules['target']),
                    *rules.get('members', [])]:
            key = row['id']
            visits = [event for event in (core.activities or {}).get('events', {}).values()
                      if event['destination']['id'] == key]
            received = [event for event in visits if event['status'] == 'resolved']
            scored = [event for event in received if 'patron_match' in event]
            matched = sum(event['patron_match']['matched'] for event in scored)
            members[key] = dict(name=row['name'], target=row['target'],
                satisfaction=data['satisfaction'] if key == rules['destination']['id'] else data['members'][key],
                dispatched=len(visits), received=len(received), pending=len(visits)-len(received),
                conditional_visits=len(scored), matched=matched, unmatched=len(scored)-matched,
                match_rate=matched/len(scored) if scored else None)
        result.update(members=members, dispatched=sum(r['dispatched'] for r in members.values()),
                      received=sum(r['received'] for r in members.values()))
    return result


def collect_session(session, result, objective):
    from .autoplay_evaluation import collect
    core = session.core
    projection = copy.copy(core)
    preparation = core.summary() if not core.closed else None
    if preparation is not None:
        projection.funds = preparation['opening_funds']
    collected = collect(projection, result)
    metrics = collected['metrics']
    if preparation is not None:
        metrics['income'] += preparation['total_income']
        metrics['expenses'] += preparation['total_expenses']
        for key in metrics['expense_breakdown']:
            metrics['expense_breakdown'][key] += preparation.get(key, 0)
        metrics['final_funds'] = core.funds
        metrics['uncompleted_day_finance'] = copy.deepcopy(preparation)
        metrics['equipment_cost'] = sum(metrics['expense_breakdown'][key] for key in
                                       ('equipment_expenses', 'seat_equipment_expenses', 'expansion_expenses'))
    if abs(metrics['starting_funds']+metrics['income']-metrics['expenses']-core.funds) > 1e-8:
        raise ValueError('閉店済み日と未閉店日の収支が一致しません。')
    if metrics['days'] != result.days:
        raise ValueError('閉店済み日数と集計日数が一致しません。')
    if objective != 'popularity':
        collected['stages'] = []
    collected.update(objective_result=objective_result(core, objective), operations=result.operations,
                     current_day=core.day)
    return collected


def summarize_objective(runs):
    from .autoplay_evaluation import distribution
    rows = [run['objective_result'] for run in runs if 'objective_result' in run]
    if not rows:
        return {}
    objective = rows[0]['objective']
    if objective == 'bond':
        result = {key: distribution([row[key] for row in rows]) for key in
                  ('sets', 'qualifying', 'affinity_gain', 'stamina_spent', 'stamina_recovered', 'simultaneous_count')}
        result['remaining_stamina'] = distribution([value for row in rows for value in row['remaining_stamina']])
        result['by_cat'] = {
            key: {metric: distribution([row['cats'][key][metric] for row in rows if key in row['cats']])
                  for metric in ('sets', 'affinity', 'stamina', 'stamina_spent', 'stamina_recovered')}
            for key in sorted({key for row in rows for key in row['cats']})}
        return result
    if objective == 'patron':
        result = {key: distribution([row[key] for row in rows]) for key in ('dispatched', 'received')}
        result['by_member'] = {}
        for key in sorted({key for row in rows for key in row['members']}):
            members = [row['members'][key] for row in rows if key in row['members']]
            count = sum(row['conditional_visits'] for row in members)
            result['by_member'][key] = dict(name=members[0]['name'],
                metrics={metric: distribution([row[metric] for row in members]) for metric in
                         ('satisfaction', 'dispatched', 'received', 'pending', 'matched', 'unmatched')},
                conditional_visits=count, matched=sum(row['matched'] for row in members),
                match_rate=sum(row['matched'] for row in members)/count if count else None)
        return result
    return {}
