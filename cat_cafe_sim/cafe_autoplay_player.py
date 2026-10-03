"""通常の交流ルールをコピー上で比較する、好感度向けの操作選択。"""
import copy
import json
from functools import lru_cache

from .core.human_cat_relationship import RelationshipConfig, RelationshipInteraction

BEAM_WIDTH = 128
STAMINA_VALUE = .2
STAMINA_RESERVE_FRACTION = .6


def _clone(interaction):
    # 設定と過去の記録は読み取り専用。stepが変更する状態と記録の容器を分ける。
    cloned = copy.copy(interaction)
    cloned.state = copy.deepcopy(interaction.state)
    cloned.records = list(interaction.records)
    return cloned


def _choices(interaction):
    valid = interaction.valid_actions()
    if interaction.state['stamina'] <= interaction.config.low_stamina:
        return [('connect', None)] if 'connect' in valid else [('pause', None)]
    options = [(action, None) for action in valid if action != 'switch']
    if 'switch' in valid:
        options.extend(('switch', key) for key in interaction.type_map
                       if key != interaction.state['mode'])
    return options


def _stamina_bonus(node, reserve):
    return STAMINA_VALUE * min(reserve, node.state['stamina'])


def _partial_score(node, reserve=0):
    state, config = node.state, node.config
    gain = state['affinity_pending']
    bonus = _stamina_bonus(node, reserve)
    if state['end_reason']:
        return gain+bonus, state['stamina'], gain
    # 次の発動につながるゲージを、公開された加点と発動条件から評価する。
    threshold = config.optional_threshold
    opened = min(threshold, state['engagement'])/threshold
    connected = min(threshold, state['tension'])/threshold
    potential = (config.affinity_open_up*opened + config.affinity_connect*connected
                 + config.affinity_simultaneous*min(opened, connected))
    return gain+potential+bonus, state['stamina'], gain


def _final_score(node, reserve=0):
    gain, stamina = node.state['affinity_pending'], node.state['stamina']
    return gain+_stamina_bonus(node, reserve), gain, stamina


def _plan(interaction, reserve=0):
    # 狭い探索で既存の良い経路を落とさないよう、従来方針の完走も候補にする。
    baseline, baseline_path = _clone(interaction), []
    while not baseline.state['end_reason']:
        choice = _short_action(baseline)
        baseline.step(*choice)
        baseline_path.append(choice)
    nodes = [(_clone(interaction), ())]
    while any(not node.state['end_reason'] for node, _ in nodes):
        candidates = []
        for node, path in nodes:
            if node.state['end_reason']:
                candidates.append((node, path))
                continue
            for choice in _choices(node):
                future = _clone(node)
                future.step(*choice)
                candidates.append((future, path+(choice,)))
        # 安定ソートで同点は固定の候補順。全探索ではなく各深さで128件まで残す。
        candidates.sort(key=lambda item: _partial_score(item[0], reserve), reverse=True)
        nodes = candidates[:BEAM_WIDTH]
    nodes.append((baseline, tuple(baseline_path)))
    if reserve:
        # 体力を評価する探索でも、加点優先の良い経路を候補から落とさない。
        path = _plan(interaction)
        gain_first = _clone(interaction)
        for choice in path:gain_first.step(*choice)
        nodes.append((gain_first, path))
    return max(nodes, key=lambda item: _final_score(item[0], reserve))[1]


@lru_cache(maxsize=128)
def _initial_plan(encoded_config, stamina, engagement, tension, keep_stamina=False):
    config = RelationshipConfig.from_dict(json.loads(encoded_config))
    initial = RelationshipInteraction(config, session_id='autoplay-plan', stamina=stamina,
                                      engagement=engagement, tension=tension)
    return _plan(initial, config.max_stamina*STAMINA_RESERVE_FRACTION if keep_stamina else 0)


def player_action(interaction, *, keep_stamina=False):
    """残りの操作列を比較する。実状態を変えず、再開後も同じ列を選ぶ。"""
    if type(keep_stamina) is not bool:
        raise ValueError('体力を残す設定は真偽値で指定してください。')
    if interaction.state['end_reason']:
        raise ValueError('終了した交流の操作は選べません。')
    # 加点と設定された体力評価を使う。好感度・ID・日時に依存しない計画を再利用する。
    encoded = json.dumps(interaction.config.to_dict(), ensure_ascii=False, sort_keys=True)
    gauges = interaction.initial_gauges
    planned = _initial_plan(encoded, interaction.initial_stamina,
                            gauges['engagement'], gauges['tension'], keep_stamina)
    prefix = tuple((record['action'], record['target_type']) for record in interaction.records)
    if planned[:len(prefix)] == prefix and len(prefix) < len(planned):
        return planned[len(prefix)]
    # 手動操作などで予定から外れた場合、現在の公開状態から残りを比較する。
    reserve = interaction.config.max_stamina*STAMINA_RESERVE_FRACTION if keep_stamina else 0
    return _plan(interaction, reserve)[0]


def _short_action(interaction):
    """公開ルールで2手まで試し、好感度を増やせる交流を選ぶ。実状態は変更しない。"""
    import copy
    valid = interaction.valid_actions()
    if 'connect' in valid:
        return 'connect', None
    if interaction.state['stamina'] <= 20:
        return 'pause', None
    options = [(action, None) for action in valid if action != 'switch']
    if 'switch' in valid:
        options += [('switch', key) for key in interaction.type_map if key != interaction.state['mode']]
    ranked = []
    for index, (action, target) in enumerate(options):
        trial = copy.deepcopy(interaction)
        trial.step(action, target)
        futures = [trial]
        if not trial.state['end_reason']:
            futures = []
            for follow in trial.valid_actions():
                if follow == 'switch':
                    continue
                future = copy.deepcopy(trial)
                future.step(follow)
                futures.append(future)
        score = max((future.state['affinity_pending']-interaction.state['affinity_pending'],
                     future.state['stamina']) for future in futures)
        ranked.append((score, -index, action, target))
    _, _, action, target = max(ranked)
    return action, target
