"""営業用の暫定的な自動交流。公開反応・体力・使用可能コマンドで選ぶ。"""
from ..core.human_cat_types import TYPE_IDS


class AutomaticInteractionPolicy:
    version = 'automatic-interaction-v2'
    compatible_versions = ('automatic-interaction-v1', version)

    @staticmethod
    def _type_map(config):
        return {row.id:row for row in config.types} if config is not None else {}

    def _best_type(self,config,group,current,exclude_group=None):
        rows=self._type_map(config)
        if not rows:return None
        preferences=config.personality.type_preferences
        ranked=[]
        for index,key in enumerate(TYPE_IDS):
            row=rows[key]
            if key!=current and row.group!=exclude_group and (group is None or row.group==group):
                if getattr(config,'second_type_mastery','') or getattr(config,'second_group_second_type_mastery','') or getattr(config,'third_group_second_type_mastery',''):
                    learned=key in (config.type_mastery,config.second_type_mastery,getattr(config,'second_group_type_mastery',''),getattr(config,'second_group_second_type_mastery',''),getattr(config,'third_group_type_mastery',''),getattr(config,'third_group_second_type_mastery',''))
                    multiplier=config.type_mastery_engagement_multiplier if learned else 1
                    second_group_choice=getattr(config,'second_group_type_mastery','')
                    preferred=(bool(second_group_choice and group==config.second_mastery_group
                                    and key in (second_group_choice,getattr(config,'second_group_second_type_mastery','')))
                               or bool(getattr(config,'third_group_type_mastery','') and group==config.third_mastery_group
                                       and key in (config.third_group_type_mastery,config.third_group_second_type_mastery)))
                    ranked.append((preferred,row.gain*preferences[index]*multiplier,-index,key))
                else:
                    ranked.append((key in (getattr(config,'type_mastery',''),getattr(config,'second_group_type_mastery',''),getattr(config,'third_group_type_mastery',''),getattr(config,'third_group_second_type_mastery','')),row.gain*preferences[index],-index,key))
        return max(ranked)[-1] if ranked else None

    def choose(self, observation, valid_actions, config=None):
        if 'connect' in valid_actions:
            return 'connect', None
        if observation['stamina'] <= 20:
            return 'pause', None
        rows=self._type_map(config);current=observation['mode']
        current_group=rows[current].group if current in rows else None
        mastery = ('contact' if getattr(config, 'contact_service', False) else
                   'play' if getattr(config, 'play_service', False) else
                   'quiet' if getattr(config, 'quiet_service', False) else getattr(config,'mastery_group',''))
        individual=getattr(config,'type_mastery','')
        if getattr(config,'second_group_type_mastery','') and mastery==config.second_mastery_group:
            individual=(self._best_type(config,mastery,'') if getattr(config,'second_group_second_type_mastery','') else config.second_group_type_mastery)
        if getattr(config,'second_type_mastery','') and not (getattr(config,'second_group_type_mastery','') and mastery==config.second_mastery_group):
            individual=self._best_type(config,mastery,'')
        if getattr(config,'third_group_type_mastery','') and mastery==config.third_mastery_group:
            individual=(self._best_type(config,mastery,'') if config.third_group_second_type_mastery else config.third_group_type_mastery)
        if ('switch' in valid_actions and individual and current!=individual
                and rows[individual].group==mastery and observation.get('last_interaction_group') is None):
            return 'switch',individual
        if ('switch' in valid_actions and mastery and current_group!=mastery
                and observation.get('last_interaction_group') is None):
            target=self._best_type(config,mastery,current)
            if target:return 'switch',target
        if observation['previous_reaction'] in ('turn_away', 'confused'):
            if not mastery:
                target=TYPE_IDS[(TYPE_IDS.index(current)+1)%len(TYPE_IDS)]
            else:
                target=(self._best_type(config,mastery,current) if current_group!=mastery else
                        self._best_type(config,None,current,current_group))
            return 'switch', target
        if ('switch' in valid_actions and mastery and observation.get('interaction_streak',0)>=2
                and observation.get('previous_action')!='switch'):
            target=(self._best_type(config,mastery,current) if mastery and current_group!=mastery else
                    self._best_type(config,None,current,current_group if mastery else None))
            if target:return 'switch',target
        return 'direct', None
