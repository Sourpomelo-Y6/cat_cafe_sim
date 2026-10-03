"""好感度モードを通常操作で評価し、加入と交流選択を記録する。"""
import argparse
import copy
import json
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from cat_cafe_sim.autoplay_evaluation import collect
from cat_cafe_sim.cafe_autoplay import AutoPlayer
from cat_cafe_sim.cafe_autoplay_strategy import reserve
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.core import cafe_player
from cat_cafe_sim.storage.cafe_saves import load_game, save_game


def run(task):
    seed, output = task
    conditions = starting_conditions('bond')
    with tempfile.TemporaryDirectory(prefix='bond-seeds-') as directory:
        session = create_game(directory, copy.deepcopy(conditions), seed=seed)
        recruitment, selections = [], []
        original_recruit, original_play = session.recruit_cat, session.play_with_player

        def recruit(cat_id):
            core = session.core
            recruitment.append(dict(day=core.day, cat_id=cat_id, funds_before=core.funds,
                                    reserve=reserve(core), cats_before=len(core.cats),
                                    cost=core.recruitment['candidates'][cat_id]['cost']))
            return original_recruit(cat_id)

        def play(cat_id):
            core = session.core
            bond = cafe_player.state(core)
            selections.append(dict(day=core.day, cat_id=cat_id, remaining=cafe_player.remaining(core),
                candidates=[dict(cat_id=key, affinity=bond['affinity'][key],
                                 unavailable_reason=cafe_player.unavailable_reason(core, key),
                                 health=cat.health_status, activity=core.activity(key),
                                 stamina=cat.stamina, fatigue=cat.fatigue,
                                 stress=core.management['stress'][key])
                            for key, cat in sorted(core.cats.items())]))
            return original_play(cat_id)

        session.recruit_cat, session.play_with_player = recruit, play
        result = AutoPlayer(session, objective='bond', mode='clear',
                            max_days=90, emit=lambda line: None).run()
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
            metrics['uncompleted_day_finance'] = preparation
        if abs(metrics['starting_funds']+metrics['income']-metrics['expenses']-core.funds) > 1e-8:
            raise ValueError('完了日と準備中の収支が一致しません。')
        if metrics['days'] != result.days:
            raise ValueError('完了日数と集計日数が一致しません。')
        completions = [event['result'] for row in core.operations for event in row['events']
                       if event['kind']=='player_completed']
        if len(completions) > len(selections):
            raise ValueError('交流開始と完了記録が一致しません。')
        for selection, completed in zip(selections, completions):
            if selection['cat_id'] != completed['cat_id']:
                raise ValueError('交流を選んだ猫と完了結果が一致しません。')
            selection['result'] = completed
        save_game(session, session.checkpoint_path)
        loaded, _ = load_game(session.checkpoint_path)
        if loaded.core.snapshot() != core.snapshot():
            raise ValueError('最終状態の保存再開が一致しません。')
        row = dict(seed=seed, reason=result.reason, completed_days=result.days,
                   operations=result.operations, metrics=metrics, cat_count=len(core.cats),
                   goal=core.bond_goal, player_bond=cafe_player.state(core),
                   profiles={key: dict(name=value['name']) for key, value in session.profiles.items()},
                   recruitment=recruitment, selections=selections,
                   save_resume_verified=True)
        (Path(output)/f'{seed}.json').write_text(
            json.dumps(row, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(dict(seed=seed, reason=result.reason, day=core.bond_goal['resolved_day'],
                              funds=core.funds, illnesses=metrics['illnesses'],
                              runaways=metrics['runaways']), ensure_ascii=False), flush=True)
        return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', type=int, nargs='+', default=list(range(10)))
    parser.add_argument('--output', default='reports/bond-seeds')
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    if any(seed < 0 for seed in args.seeds) or args.workers < 1 or len(set(args.seeds)) != len(args.seeds):
        parser.error('重複しない0以上のシードと、1以上の並列数を指定してください。')
    Path(args.output).mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run, [(seed, args.output) for seed in args.seeds]))


if __name__ == '__main__':
    main()
