"""公開観測だけを使う特別行動の固定方策比較。"""
from dataclasses import replace
import json
from pathlib import Path
from ..core.human_cat_special import SpecialInteraction
from ..core.human_cat_interaction import save, verify


def choose(policy, s, threshold=80):
    if s['connect_pending']:
        return 'connect'
    if policy != 'pause' and s['tension'] >= threshold:
        if policy in ('immediate', 'repeat') or s['engagement'] >= threshold or s['open_up_pending']:
            return 'connect'
    if policy == 'pause' or s['stamina'] <= 20:
        return 'pause'
    if policy == 'repeat':
        return 'direct'
    if s['previous_reaction'] == 'turn_away' or s['interaction_streak'] >= 2:
        return 'switch' if s['last_interaction_kind'] == s['mode'] else 'direct'
    return 'direct'


def compare_special(config, output):
    output = Path(output)
    rows = []
    for prefs in ((1, 1), (0, 2), (2, 0), (.5, .5)):
        for stamina in (100, 20):
            for policy in ('immediate', 'synchronize', 'repeat', 'pause'):
                core = SpecialInteraction(replace(config, preferences=prefs), stamina=stamina)
                while not core.state['end_reason']:
                    core.step(choose(policy, core.observation(), config.optional_threshold))
                path = output.with_suffix('') / f'case_{len(rows):02d}.json'
                save(core, path)
                verify(path)
                rows.append(dict(policy=policy, preferences=list(prefs), initial_stamina=stamina,
                                 **core.summary(), log=str(path)))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(rule_version=2, config=config.to_dict(), rows=rows), ensure_ascii=False, indent=2)+'\n')
    return rows
