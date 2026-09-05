"""保存した営業ログから失敗直前の公開観測・Q値と1手だけの代替結果を調べる。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from cat_cafe_sim import __version__

from cat_cafe_sim.core import Command, SimulationCore, StartState
from cat_cafe_sim.envs.observations import cat_observation
from cat_cafe_sim.policies.learned import LearnedCatPolicy


class RecordedPolicy:
    def __init__(self):
        self.action = None
        self.observation = None

    def choose(self, observation):
        self.observation = dict(observation)
        return self.action


def analyze_log(path, policy):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data['format_version'] != 1 or data['simulator_version'] != __version__:
        raise ValueError('unsupported replay version')
    if data.get('cat_policy_metadata', {}).get('model_sha256') != policy.model_sha256:
        raise ValueError('log and model fingerprint mismatch')
    from cat_cafe_sim.core.config import Config
    config = Config.from_dict(data['config'])
    policy.validate_config(config)
    initial = StartState(**data['start_state']) if 'start_state' in data else None
    core = SimulationCore(config, seed=data['seed'], start_state=initial)
    recorder = RecordedPolicy()
    core.cat_policy = recorder
    failures = []
    for index, record in enumerate(data['records']):
        before = copy.deepcopy(core)
        recorder.action = record['cat_action']
        recorder.observation = None
        core.step(Command(**record['command']))
        if core.records[-1] != record:
            raise ValueError(f'log does not replay at record {index}')
        for event in record['events']:
            if event['kind'] != 'departure' or event['reason'] != 'failure':
                continue
            raw = recorder.observation
            if raw is None:
                raise ValueError('failure without a cat action')
            state = policy.model.agent.encoder.encode(cat_observation(raw, policy.model.config))
            selected = policy.model.agent.act(state, [1] * 7)
            if selected != record['cat_action']:
                raise ValueError('recorded decision differs from model')
            alternatives = []
            for action in range(7):
                branch = copy.deepcopy(before)
                branch.step(Command(**record['command']), cat_action=action)
                visit = branch.visits[event['customer_id']]
                alternatives.append({'action': action, 'departure_reason': visit.departure_reason,
                                     'satisfaction': visit.satisfaction, 'stamina': branch.cat.stamina,
                                     'spirit': branch.cat.spirit})
            failures.append({'log': str(path), 'log_sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                             'model_sha256': policy.model_sha256, 'tick': event['tick'],
                             'customer_id': event['customer_id'], 'observation': raw,
                             'state': list(state), 'known_state': state in policy.model.agent.table,
                             'q_values': list(policy.model.agent.values(state)), 'action': selected,
                             'satisfaction_after': event['satisfaction'], 'alternatives_one_step': alternatives})
    if core.summary() != data['summary']:
        raise ValueError('log summary does not replay')
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--logs', type=Path, nargs='+', required=True)
    parser.add_argument('--models', type=Path, nargs='+', required=True)
    parser.add_argument('--output', type=Path, default=Path('reports/failure_analysis.json'))
    args = parser.parse_args()
    policies = [LearnedCatPolicy.load(path) for path in args.models]
    by_hash = {p.model_sha256: p for p in policies}
    failures = []
    for path in args.logs:
        digest = json.loads(path.read_text())['cat_policy_metadata']['model_sha256']
        if digest not in by_hash:
            parser.error(f'missing model for {path}')
        failures.extend(analyze_log(path, by_hash[digest]))
    report = {'logs': len(args.logs), 'failures': failures,
              'note': '代替行動は同じ公開観測からの1step診断。内部の好みは診断にのみ使い、方策には渡さない。将来の成功を保証しない。'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Analyzed {len(args.logs)} logs, {len(failures)} failures')


if __name__ == '__main__':
    main()
