"""5個性×2開始体力×12方策の決定的な仕様診断。"""
from dataclasses import replace
import json
from pathlib import Path
from ..core.human_cat_types import TYPE_IDS, TypesInteraction, load_presets
from ..core.human_cat_interaction import save, verify


def choose(policy, state, threshold=80):
    if state['connect_pending'] or state['tension'] >= threshold:
        return 'connect', None
    if policy == 'pause' or state['stamina'] <= 20:
        return 'pause', None
    mode = state['mode']
    if policy.startswith('fixed:'):
        target = policy.split(':')[1]
        return ('direct', None) if mode == target else ('switch', target)
    sequence = ('teaser', 'ball', 'plush', 'tunnel') if policy == 'within' else ('teaser', 'pet', 'voice') if policy == 'across' else TYPE_IDS
    should_switch = (state['interaction_streak'] >= 2 if policy != 'responsive' else
                     state['previous_reaction'] in ('turn_away', 'confused'))
    if should_switch and state['previous_action'] != 'switch':
        return 'switch', sequence[(sequence.index(mode) + 1) % len(sequence)]
    return 'direct', None


def compare_types(config, output):
    output = Path(output)
    rows = []
    presets = load_presets()
    for name, personality in presets.items():
        for stamina in (100, 20):
            for policy in tuple('fixed:' + t for t in TYPE_IDS) + ('within', 'across', 'responsive', 'pause'):
                core = TypesInteraction(replace(config, personality=personality), stamina=stamina)
                while not core.state['end_reason']:
                    core.step(*choose(policy, core.observation(), config.optional_threshold))
                path = output.with_suffix('') / f'case_{len(rows):03d}.json'
                save(core, path)
                verify(path)
                rows.append(dict(preset=name, initial_stamina=stamina, policy=policy, **core.summary(), log=str(path)))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(rule_version=3, config=config.to_dict(),
         presets={n:p.to_dict() for n,p in presets.items()}, rows=rows), ensure_ascii=False, indent=2)+'\n')
    lines=['# 8種類と個性の固定方策比較', '', '決定的な仕様診断。学習方策の未使用評価ではない。', '',
           '| 個性 | 開始体力 | 方策 | 終了 | 資金 | 消費体力 | tick | 同時発動 |', '|---|---:|---|---|---:|---:|---:|---:|']
    for r in rows:
        lines.append(f"| {r['preset']} | {r['initial_stamina']} | {r['policy']} | {r['end_reason']} | {r['bonus_funds']:g} | {r['stamina_spent']:.2f} | {r['ticks']} | {r['simultaneous_count']} |")
    output.with_suffix('.md').write_text('\n'.join(lines)+'\n')
    return rows
