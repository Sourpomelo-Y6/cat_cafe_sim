"""好感度の操作選択だけを切り替え、同じ営業日数でも体力・収入を比較する。"""
import argparse
import copy
import hashlib
import json
import tempfile
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from Docs.Results import BondSeedEvaluationRunner as runner
from cat_cafe_sim.autoplay_evaluation import collect
from cat_cafe_sim.cafe_autoplay_player import player_action, STAMINA_VALUE, STAMINA_RESERVE_FRACTION
from cat_cafe_sim.cafe_new_game import starting_conditions


def window_metrics(core, result, days):
    if type(days) is not int or days < 1:
        raise ValueError('比較する営業日数は正の整数を指定してください。')
    rows = list(core.day_results)
    if core.closed:
        rows.append(core.day_result())
    if len(rows) < days:
        raise ValueError('比較する営業日数まで進行していません。')
    projection = copy.copy(core)
    projection.day_results = rows[:days]
    projection.closed = False
    projection.funds = rows[days-1]['summary']['closing_funds']
    return collect(projection, result)['metrics']


def run(task):
    seed, keep_stamina, days = task
    captured = {}

    def capture(core, result):
        captured.update(window_metrics(core, result, days))
        return collect(core, result)

    def choose(interaction, **options):
        # 比較用プロセス内だけで操作選択を変える。ゲーム設定・通常操作は共通。
        return player_action(interaction, keep_stamina=keep_stamina)

    with tempfile.TemporaryDirectory(prefix='bond-stamina-') as directory, \
            patch.object(runner, 'collect', side_effect=capture), \
            patch('cat_cafe_sim.cafe_autoplay_objectives.player_action', side_effect=choose):
        row = runner.run((seed, directory))
    row.update(keep_stamina=keep_stamina, common_window_days=days, common_window_metrics=captured)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', type=int, nargs='+', default=list(range(10)))
    parser.add_argument('--window-days', type=int, default=17)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--output', default='reports/bond-stamina.json')
    args = parser.parse_args()
    if (any(seed < 0 for seed in args.seeds) or len(set(args.seeds)) != len(args.seeds)
            or args.workers < 1 or args.window_days < 1):
        parser.error('重複しない0以上のシードと正の営業日数・並列数を指定してください。')
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        runs = list(pool.map(run, [(seed, keep, args.window_days)
                                  for keep in (False, True) for seed in args.seeds]))
    conditions = starting_conditions('bond')
    encoded = json.dumps(conditions, ensure_ascii=False, sort_keys=True).encode()
    report = dict(format_version=1, evaluated_at=datetime.now(timezone.utc).isoformat(),
                  implementation_base_commit='96a825c', objective='bond', mode='clear', max_days=90,
                  seeds=args.seeds, common_window_days=args.window_days, conditions=conditions,
                  conditions_sha256=hashlib.sha256(encoded).hexdigest(),
                  stamina_value=STAMINA_VALUE, stamina_reserve_fraction=STAMINA_RESERVE_FRACTION,
                  comparison='安定経営の交流操作選択だけを加点優先／体力も評価へ切り替える', runs=runs)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
