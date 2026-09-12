"""終了・親しみ・資金・消耗の仕様診断。成功率は集計しない。"""
from dataclasses import replace
import json
from pathlib import Path
import tempfile

from ..core.human_cat_types import load_presets
from ..core.human_cat_interaction import save, verify
from ..storage.relationships import RelationshipStore
from .interaction_types import choose


def compare_relationships(config, output):
    output=Path(output)
    rows=[]
    for name,personality in load_presets().items():
        for stamina in (100,20):
            for policy in ('short','responsive','pause','special_cycle'):
                # Each experiment gets an isolated store; normal save files are never touched.
                with tempfile.TemporaryDirectory() as directory:
                    store=RelationshipStore(Path(directory)/'relations.json')
                    for visit in range(3):
                        core=store.begin(replace(config,personality=personality),'cat-test','guest-test',stamina=stamina,
                                         session_id=f'case-{len(rows):03d}')
                        while not core.state['end_reason']:
                            if policy=='short' and len(core.records)>=3:
                                core.finish();break
                            if core.state['connect_pending']:
                                command=('connect',None)
                            elif policy=='pause':
                                command=('pause',None)
                            elif policy=='short':
                                command=('direct',None)
                            else:
                                command=choose('responsive' if policy=='responsive' else 'across',core.observation(),config.optional_threshold)
                            core.step(*command)
                        path=output.with_suffix('')/f'case_{len(rows):03d}.json'
                        save(core,path);verify(path)
                        store.apply(core)
                        assert store.snapshot('cat-test','guest-test')['affinity']==core.result()['affinity_after']
                        rows.append(dict(preset=name,initial_stamina=stamina,policy=policy,visit=visit+1,**core.result(),log=str(path)))
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(dict(rule_version=4,config=config.to_dict(),rows=rows),ensure_ascii=False,indent=2)+'\n')
    lines=['# 親しみと終了成果の診断','','各条件で同じ相手と3回再会。体力は毎回指定値に戻す単独試遊。','',
           '| 個性 | 開始体力 | 方策 | 回 | 終了 | 親しみ前 | 親しみ後 | 資金 | 消費体力 |',
           '|---|---:|---|---:|---|---:|---:|---:|---:|']
    for r in rows:
        lines.append(f"| {r['preset']} | {r['initial_stamina']} | {r['policy']} | {r['visit']} | {r['end_reason']} | {r['affinity_before']:g} | {r['affinity_after']:g} | {r['bonus_funds']:g} | {r['stamina_spent']:.2f} |")
    output.with_suffix('.md').write_text('\n'.join(lines)+'\n')
    return rows
