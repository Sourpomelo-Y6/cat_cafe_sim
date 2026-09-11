"""個性既知の幅制限探索と、公開反応だけを使う固定方策の比較。"""
import argparse
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path

from ..core.human_cat_types import TypesConfig, TypesInteraction, TYPES_CONFIG, TYPE_IDS, load_presets
from ..core.human_cat_interaction import save, verify
from .interaction_types import choose


def commands(core):
    for action in core.valid_actions():
        if action == 'switch':
            for target in TYPE_IDS:
                if target != core.state['mode']:
                    yield action, target
        else:
            yield action, None


def fork(core):
    # Config/type definitions are frozen. Steps append/replace records, never edit old records.
    branch = copy.copy(core)
    branch.state = dict(core.state)
    branch.records = list(core.records)
    return branch


def rank(core):
    s, c = core.state, core.config
    t = c.optional_threshold if s['connect_count'] else min(s['tension'], c.optional_threshold)
    e = c.optional_threshold if s['open_up_count'] else min(s['engagement'], c.optional_threshold)
    return (min(t, e) + .5 * (t + e) + .2 * s['stamina'], s['bonus_funds'], s['stamina'])


def retain(candidates, width):
    # Preserve alternative modes / resource bands / completed sides, not only gauge progress.
    buckets = {}
    for core in sorted(candidates, key=rank, reverse=True):
        s = core.state
        key = (s['mode'], bool(s['connect_count']), bool(s['open_up_count']), int(s['stamina'] // 20))
        buckets.setdefault(key, []).append(core)
    result = []
    depth = 0
    while len(result) < min(width, len(candidates)):
        for bucket in buckets.values():
            if depth < len(bucket):
                result.append(bucket[depth])
                if len(result) == width:
                    return result
        depth += 1
    return result


def search(initial, *, width=128, max_expansions=250000):
    if type(width) is not int or width < 1 or type(max_expansions) is not int or max_expansions < 1:
        raise ValueError('positive integer search limits required')
    if initial.state['end_reason']:
        return dict(found=initial.state['end_reason'] == 'success', complete=True, reason='initial_terminal',
                    expanded=0, pruned=0, duplicates=0, depth=0, witness=fork(initial))
    frontier = [fork(initial)]
    best = frontier[0]
    expanded = pruned = duplicates = 0
    for depth in range(initial.state['remaining_ticks']):
        candidates, successes = {}, []
        for parent in frontier:
            for action, target in commands(parent):
                if expanded >= max_expansions:
                    if successes:
                        witness = max(successes, key=lambda x: (x.state['bonus_funds'], x.state['stamina']))
                        return dict(found=True, complete=False, reason='success_at_expansion_limit', expanded=expanded,
                                    pruned=pruned, duplicates=duplicates, depth=depth + 1, witness=witness)
                    return dict(found=False, complete=False, reason='expansion_limit', expanded=expanded,
                                pruned=pruned, duplicates=duplicates, depth=depth, witness=best)
                branch = fork(parent)
                branch.step(action, target)
                expanded += 1
                if rank(branch) > rank(best):
                    best = branch
                if branch.state['end_reason'] == 'success':
                    successes.append(branch)
                elif not branch.state['end_reason']:
                    key = tuple(sorted(branch.state.items()))
                    if key in candidates:
                        duplicates += 1
                    else:
                        candidates[key] = branch
        if successes:
            witness = max(successes, key=lambda x: (x.state['bonus_funds'], x.state['stamina']))
            return dict(found=True, complete=pruned == 0, reason='success_witness', expanded=expanded,
                        pruned=pruned, duplicates=duplicates, depth=depth + 1, witness=witness)
        frontier = retain(list(candidates.values()), width)
        pruned += max(0, len(candidates) - len(frontier))
        if not frontier:
            break
    return dict(found=False, complete=pruned == 0, reason='tree_exhausted' if pruned == 0 else 'beam_exhausted',
                expanded=expanded, pruned=pruned, duplicates=duplicates, depth=depth + 1, witness=best)


def details(core):
    records = core.records
    return dict(summary=core.summary(),
                actions=[dict(action=r['action'], target_type=r['target_type']) for r in records],
                action_counts={a: sum(r['action'] == a for r in records) for a in ('direct','adapt','intense','feint','pause','switch','connect')},
                reaction_counts=core.summary()['reactions'],
                low_stamina_actions=sum(r['before']['stamina'] <= core.config.low_stamina for r in records),
                stamina_recovered=sum(r['stamina_recovered'] for r in records))


def diagnose(config, output, *, width=128, max_expansions=250000, progress=None, preset=None, starts=(100, 20)):
    output = Path(output)
    rows = []
    presets = load_presets()
    if preset is not None:
        if preset not in presets:
            raise ValueError('unknown preset')
        presets = {preset: presets[preset]}
    for name, personality in presets.items():
        for stamina in starts:
            initial = TypesInteraction(replace(config, personality=personality), stamina=stamina)
            result = search(initial, width=width, max_expansions=max_expansions)
            witness = result.pop('witness')
            search_path = output.with_suffix('') / f'case_{len(rows):02d}_search.json'
            save(witness, search_path)
            verify(search_path)
            # No lookahead/config/personality is passed to this existing fixed policy.
            reaction_only = TypesInteraction(replace(config, personality=personality), stamina=stamina)
            while not reaction_only.state['end_reason']:
                reaction_only.step(*choose('responsive', reaction_only.observation(), config.optional_threshold))
            policy_path = output.with_suffix('') / f'case_{len(rows):02d}_reactive.json'
            save(reaction_only, policy_path)
            verify(policy_path)
            row = dict(preset=name, initial_stamina=stamina, search={**result, **details(witness), 'log':str(search_path)},
                       reactive={**details(reaction_only), 'log':str(policy_path)})
            rows.append(row)
            if progress:
                progress(row)
    data = dict(method='diverse-beam-v1', width=width, max_expansions=max_expansions,
                note='個性既知の診断用探索。未発見は不可能の証明ではない。失敗時のsearchログは途中の診断経路。',
                config=config.to_dict(), config_sha256=hashlib.sha256(json.dumps(config.to_dict(), sort_keys=True).encode()).hexdigest(),
                rows=rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    lines=['# 個性別の到達経路診断','',data['note'],'',
           '| 個性 | 開始体力 | 探索で成功 | 探索tick | 探索資金 | 反応方策の終了 | 反応方策の資金 |',
           '|---|---:|---|---:|---:|---|---:|']
    for row in rows:
        a,b=row['search'],row['reactive']['summary']
        lines.append(f"| {row['preset']} | {row['initial_stamina']} | {a['found']} | {a['summary']['ticks']} | {a['summary']['bonus_funds']} | {b['end_reason']} | {b['bonus_funds']} |")
    output.with_suffix('.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return data


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=TYPES_CONFIG)
    parser.add_argument('--output',type=Path,default=Path('reports/type_reachability.json'))
    parser.add_argument('--preset')
    parser.add_argument('--stamina',type=float,nargs='+',default=(100,20))
    parser.add_argument('--width',type=int,default=128)
    parser.add_argument('--max-expansions',type=int,default=250000)
    args=parser.parse_args()
    def progress(row):
        r=row['search']
        print(f"{row['preset']} stamina={row['initial_stamina']} found={r['found']} ticks={r['summary']['ticks']} expanded={r['expanded']}",flush=True)
    diagnose(TypesConfig.load(args.config),args.output,width=args.width,max_expansions=args.max_expansions,progress=progress,preset=args.preset,starts=args.stamina)


if __name__ == '__main__':
    main()
