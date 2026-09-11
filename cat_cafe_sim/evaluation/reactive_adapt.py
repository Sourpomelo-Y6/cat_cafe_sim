"""低体力後の公開反応を使う、単一候補の固定方策比較。"""
import argparse
from dataclasses import replace
import json
from pathlib import Path

from ..core.human_cat_types import TypesConfig, TypesInteraction, Personality, load_presets
from ..core.human_cat_interaction import save, verify
from .interaction_types import choose


def choose_adapt(state, threshold=80):
    action, target = choose('responsive', state, threshold)
    if action == 'direct' and state['previous_reaction'] == 'listless':
        return 'adapt', None
    return action, target


def compare(config, cases_path, output):
    cases = json.loads(Path(cases_path).read_text(encoding='utf-8'))
    groups = dict(diagnostic=(load_presets(), (100,20)),
                  reserved=({n:Personality.from_dict(p) for n,p in cases['personalities'].items()}, cases['start_stamina']))
    rows=[]
    output=Path(output)
    for split,(profiles,starts) in groups.items():
        for name,personality in profiles.items():
            for stamina in starts:
                for policy in ('baseline','adapt_after_listless'):
                    core=TypesInteraction(replace(config,personality=personality),stamina=stamina)
                    while not core.state['end_reason']:
                        observation=core.observation()
                        action=(choose('responsive',observation,config.optional_threshold) if policy=='baseline'
                                else choose_adapt(observation,config.optional_threshold))
                        core.step(*action)
                    path=output.with_suffix('')/f'case_{len(rows):02d}.json'
                    save(core,path);verify(path)
                    rows.append(dict(split=split,preset=name,initial_stamina=stamina,policy=policy,
                                     **core.summary(),log=str(path)))
    data=dict(candidate='replace direct with adapt only after listless',config=config.to_dict(),reserved_cases=cases,rows=rows)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return data


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases',type=Path,default=Path('config/type_reactive_evaluation.json'))
    parser.add_argument('--output',type=Path,default=Path('reports/type_reactive_adapt.json'))
    args=parser.parse_args()
    result=compare(TypesConfig.load(),args.cases,args.output)
    for split in ('diagnostic','reserved'):
        for policy in ('baseline','adapt_after_listless'):
            rows=[r for r in result['rows'] if r['split']==split and r['policy']==policy]
            print(split,policy,'success',sum(r['end_reason']=='success' for r in rows),'/',len(rows),
                  'mean funds',sum(r['bonus_funds'] for r in rows)/len(rows))


if __name__=='__main__':
    main()
