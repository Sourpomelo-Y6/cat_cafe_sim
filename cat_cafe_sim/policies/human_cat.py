"""営業用の暫定的な自動交流。公開反応・体力・使用可能コマンドで選ぶ。"""
from ..core.human_cat_types import TYPE_IDS


class AutomaticInteractionPolicy:
    version = 'automatic-interaction-v1'

    def choose(self, observation, valid_actions):
        if 'connect' in valid_actions:
            return 'connect', None
        if observation['stamina'] <= 20:
            return 'pause', None
        if observation['previous_reaction'] in ('turn_away', 'confused'):
            target = TYPE_IDS[(TYPE_IDS.index(observation['mode']) + 1) % len(TYPE_IDS)]
            return 'switch', target
        return 'direct', None
