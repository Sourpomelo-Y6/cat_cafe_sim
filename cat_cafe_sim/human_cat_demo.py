"""単独交流の行動列実行・再生・固定方策比較（標準ライブラリのみ）。"""
import argparse
from dataclasses import replace
import json
from pathlib import Path

from .core.human_cat_interaction import (
    ACTIONS, DEFAULT_CONFIG, NEGATIVE, HumanCatInteraction, InteractionConfig, save, verify,
)

from .core.human_cat_relationship import RelationshipConfig, RELATIONSHIP_CONFIG
from .storage.relationships import RelationshipStore
from .core.human_cat_types import TypesConfig, TypesInteraction, TYPES_CONFIG, load_presets
from .core.human_cat_special import SpecialConfig, SPECIAL_CONFIG, SpecialInteraction

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
    run.add_argument('--config', type=Path, default=None)
    run.add_argument('--stamina', type=float)
    run.add_argument('--actions', nargs='+', required=True)
    run.add_argument('--output', type=Path, default=Path('reports/human_cat_session.json'))
    replay = sub.add_parser('replay')
    replay.add_argument('path', type=Path)
    comparison = sub.add_parser('compare')
    comparison.add_argument('--config', type=Path, default=None)
    comparison.add_argument('--output', type=Path, default=Path('reports/human_cat_comparison.json'))
    for command in (run, comparison):
        command.add_argument('--rules', type=int, choices=(1, 2, 3, 4), default=1)
    run.add_argument('--relationships',type=Path,default=Path('saves/relationships.json'))
    run.add_argument('--cat-id',default='cat-1')
    run.add_argument('--customer-id',default='guest-1')
    run.add_argument('--save-result',action='store_true',help='終了結果を関係データへ一度だけ反映（版4）')
    run.add_argument('--preset', help='版3の個性プリセット名')
    run.add_argument('--tension', type=float, default=0)
    run.add_argument('--engagement', type=float, default=0)
    args = parser.parse_args(argv)
    try:
        if args.command == 'replay':
            session = verify(args.path)
            print('Replay matched:', json.dumps(session.summary(), ensure_ascii=False))
        elif args.command == 'compare':
            if args.rules == 4:
                from .evaluation.relationship_outcomes import compare_relationships
                if args.output == Path('reports/human_cat_comparison.json'):
                    args.output = Path('reports/human_cat_relationship_comparison.json')
                rows = compare_relationships(RelationshipConfig.load(args.config or RELATIONSHIP_CONFIG),args.output)
            elif args.rules == 3:
                from .evaluation.interaction_types import compare_types
                if args.output == Path('reports/human_cat_comparison.json'):
                    args.output = Path('reports/human_cat_types_comparison.json')
                rows = compare_types(TypesConfig.load(args.config or TYPES_CONFIG), args.output)
            elif args.rules == 2:
                from .evaluation.special_actions import compare_special
                if args.output == Path('reports/human_cat_comparison.json'):
                    args.output = Path('reports/human_cat_special_comparison.json')
                rows = compare_special(SpecialConfig.load(args.config or SPECIAL_CONFIG), args.output)
            else:
                rows = compare(InteractionConfig.load(args.config or DEFAULT_CONFIG), args.output)
            print(f'{len(rows)} cases saved and replay verified: {args.output}')
        else:
            if args.save_result and args.rules != 4:
                raise ValueError('saving relationship outcomes requires --rules 4')
            if args.preset and args.rules not in (3,4):
                raise ValueError('presets require --rules 3')
            if args.rules == 4:
                config = RelationshipConfig.load(args.config or RELATIONSHIP_CONFIG)
                if args.preset:
                    config = replace(config,personality=load_presets()[args.preset])
                store = RelationshipStore(args.relationships)
                session = store.begin(config,args.cat_id,args.customer_id,stamina=args.stamina,tension=args.tension,engagement=args.engagement)
                if args.output == Path('reports/human_cat_session.json'):
                    args.output = Path('reports/human_cat_relationship_session.json')
            elif args.rules == 3:
                config = TypesConfig.load(args.config or TYPES_CONFIG)
                if args.preset:
                    config = replace(config, personality=load_presets()[args.preset])
                session = TypesInteraction(config, stamina=args.stamina, tension=args.tension, engagement=args.engagement)
                if args.output == Path('reports/human_cat_session.json'):
                    args.output = Path('reports/human_cat_types_session.json')
            elif args.rules == 2:
                session = SpecialInteraction(SpecialConfig.load(args.config or SPECIAL_CONFIG), stamina=args.stamina,
                                             tension=args.tension, engagement=args.engagement)
                if args.output == Path('reports/human_cat_session.json'):
                    args.output = Path('reports/human_cat_special_session.json')
            else:
                if args.tension or args.engagement:
                    raise ValueError('initial gauges require --rules 2')
                session = HumanCatInteraction(InteractionConfig.load(args.config or DEFAULT_CONFIG), stamina=args.stamina)
            if args.rules == 4 and args.output.resolve() == args.relationships.resolve():
                raise ValueError('log output and relationship store must be different files')
            for action in args.actions:
                if session.state['end_reason']:
                    break
                if args.rules == 4 and action == 'finish':
                    session.finish()
                    break
                if args.rules >= 3:
                    parts = action.split(':')
                    if len(parts) > 2:
                        raise ValueError('use switch:target_type')
                    record = session.step(parts[0], parts[1] if len(parts) == 2 else None)
                else:
                    record = session.step(action)
                state = record['after']
                print(f"{record['tick'] + 1}: {action} → {record['reaction']} "
                      f"関心={state['engagement']:.2f} 体力={state['stamina']:.2f} 種類={state['mode']}")
            if args.rules == 4 and args.save_result and not session.state['end_reason']:
                raise ValueError('include finish or reach an ending before --save-result')
            save(session, args.output)
            verify(args.output)
            if args.rules == 4 and args.save_result:
                store.apply(session)
                print(f'Relationship outcome saved: {args.relationships}')
            if args.rules >= 2:
                print(json.dumps(session.summary(), ensure_ascii=False))
            print('終了:', session.state['end_reason'] or '継続中（指定列を実行済み）')
            print(f'Saved and replay verified: {args.output}')
    except (ValueError, TypeError, KeyError, OSError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
