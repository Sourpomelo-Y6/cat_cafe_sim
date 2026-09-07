"""単独交流の行動列実行・再生・固定方策比較（標準ライブラリのみ）。"""
import argparse
from dataclasses import replace
import json
from pathlib import Path

from .core.human_cat_interaction import (
    ACTIONS, DEFAULT_CONFIG, NEGATIVE, HumanCatInteraction, InteractionConfig, save, verify,
)

POLICIES = ('direct', 'intense', 'pause_feint', 'responsive', 'switching', 'pause')


def choose(name, observation, tick):
    if name in ('direct', 'intense', 'pause'):
        return name
    if name == 'pause_feint':
        return 'direct' if tick == 0 else ('pause' if tick % 2 else 'feint')
    if name == 'responsive':
        if observation['stamina'] <= 20:
            return 'pause'
        return 'adapt' if observation['previous_reaction'] in NEGATIVE else 'direct'
    if name == 'switching':
        return ('direct', 'direct', 'switch')[tick % 3]
    raise ValueError('unknown policy')


def compare(config, output):
    output = Path(output)
    rows = []
    for preferences in ((1, 1), (0, 2), (2, 0), (.5, .5)):
        for stamina in (100, 20):
            for policy in POLICIES:
                session = HumanCatInteraction(replace(config, preferences=preferences), stamina=stamina)
                while not session.state['end_reason']:
                    session.step(choose(policy, session.observation(), len(session.records)))
                path = output.with_suffix('') / f'case_{len(rows):02d}_{policy}.json'
                save(session, path)
                verify(path)
                rows.append(dict(policy=policy, preferences=list(preferences), initial_stamina=stamina,
                                 **session.summary(), log=str(path)))
    report = dict(note='仕様診断48条件。決定的な固定方策比較であり、学習の未使用評価ではない。',
                  config=config.to_dict(), rows=rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lines = ['# 単独交流の固定方策比較', '', report['note'], '',
             '| 方策 | 好み play/pet | 開始体力 | 関心 | 消費体力 | tick | 終了 |',
             '|---|---|---:|---:|---:|---:|---|']
    for r in rows:
        lines.append(f"| {r['policy']} | {r['preferences']} | {r['initial_stamina']} | {r['engagement']:.2f} | {r['stamina_spent']:.2f} | {r['ticks']} | {r['end_reason']} |")
    output.with_suffix('.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    run = sub.add_parser('run', help='指定列を1回だけ実行。終了以後の残り操作は実行しない')
    run.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    run.add_argument('--stamina', type=float)
    run.add_argument('--actions', nargs='+', choices=ACTIONS, required=True)
    run.add_argument('--output', type=Path, default=Path('reports/human_cat_session.json'))
    replay = sub.add_parser('replay')
    replay.add_argument('path', type=Path)
    comparison = sub.add_parser('compare')
    comparison.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    comparison.add_argument('--output', type=Path, default=Path('reports/human_cat_comparison.json'))
    args = parser.parse_args(argv)
    try:
        if args.command == 'replay':
            session = verify(args.path)
            print('Replay matched:', json.dumps(session.summary(), ensure_ascii=False))
        elif args.command == 'compare':
            rows = compare(InteractionConfig.load(args.config), args.output)
            print(f'{len(rows)} cases saved and replay verified: {args.output}')
        else:
            session = HumanCatInteraction(InteractionConfig.load(args.config), stamina=args.stamina)
            for action in args.actions:
                if session.state['end_reason']:
                    break
                record = session.step(action)
                state = record['after']
                print(f"{record['tick'] + 1}: {action} → {record['reaction']} "
                      f"関心={state['engagement']:.2f} 体力={state['stamina']:.2f} 種類={state['mode']}")
            save(session, args.output)
            verify(args.output)
            print('終了:', session.state['end_reason'] or '継続中（指定列を実行済み）')
            print(f'Saved and replay verified: {args.output}')
    except (ValueError, TypeError, KeyError, OSError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
