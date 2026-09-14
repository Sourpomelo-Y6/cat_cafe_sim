"""営業途中のチェックポイント。読み込みで会計や関係更新を実行しない。"""
import copy
import json
from pathlib import Path

from .relationships import RelationshipStore, RelationshipConflict
from ..core.cafe_interaction import verify_cafe_interaction
from ..core.human_cat_relationship import RelationshipConfig, verify_relationship
from ..core.human_cat_types import unique_object
from ..policies.human_cat import AutomaticInteractionPolicy


class MemoryRelationships(RelationshipStore):
    def __init__(self, data):
        self.data = copy.deepcopy(self.validate_data(data))

    def _read(self):
        return copy.deepcopy(self.data)

    def _write(self, data):
        self.data = copy.deepcopy(data)


def validate_progress(core, baseline, current):
    """保存済み時点から許す更新は、記録済みの終了結果の保存再試行だけ。"""
    expected = MemoryRelationships(baseline)
    matched = expected.data == current
    for log in core.outcomes.values():
        expected.apply(verify_relationship(log))
        matched = matched or expected.data == current
    if not matched:
        raise RelationshipConflict('関係データがこの営業セーブより先へ進んでいるか、変更されています。新しい営業セーブを開いてください。')
    # 終了済みと偽られた適用IDや、異なる内容の終了結果も照合する。
    actual = MemoryRelationships(current)
    persisted = set()
    for session_id, log in core.outcomes.items():
        if session_id in current['applied']:
            actual.apply(verify_relationship(log))
            persisted.add(session_id)
    active = core.interactions.values() if hasattr(core,'interactions') else ([core.active] if core.active else [])
    for interaction in active:
        initial = interaction.initial_relationship
        snapshot = actual.snapshot(interaction.cat_id,interaction.customer_id)
        if (interaction.session_id in current['applied'] or snapshot != dict(affinity=initial['affinity'],revision=initial['revision'])):
            raise RelationshipConflict('交流中の相手との関係が変更されています。新しい営業セーブを開いてください。')
    return persisted


def check_link(session):
    baseline = session.checkpoint_baseline
    if baseline is not None:
        validate_progress(session.core,baseline,session.store._read())


def save_game(session, path, *, auto_assign=False):
    if session.policy.version != AutomaticInteractionPolicy.version:
        raise ValueError('この自動交流方策は営業セーブに対応していません。')
    if type(auto_assign) is not bool:
        raise ValueError('invalid assignment setting')
    path = Path(path).resolve()
    if path == session.store.path.resolve():
        raise ValueError('営業セーブと関係データは別のファイルにしてください。')
    check_link(session)
    # 操作履歴で復元できない状態を黙って捨てない。
    log = session.core.log()
    restored = verify_cafe_interaction(log)
    if restored.snapshot() != session.core.snapshot():
        raise ValueError('営業状態と履歴が一致しないため保存できません。')
    relationships = session.store._read()
    persisted = validate_progress(session.core,relationships,relationships)
    if not session.persisted <= persisted:
        raise RelationshipConflict('保存済みの交流結果が関係データから失われています。')
    payload = dict(kind='cafe-save',format_version=1,core=log,
                   interaction_config=session.interaction_config.to_dict(),
                   relationship_path=str(session.store.path.resolve()),relationships=relationships,
                   policy_version=session.policy.version,auto_assign=auto_assign)
    # 関係保存と共通の一時ファイル・fsync・置換処理を使う。
    RelationshipStore(path)._write(payload)
    session.checkpoint_path = path
    session.checkpoint_baseline = copy.deepcopy(relationships)
    return path


def load_game(path):
    from ..cafe_interaction import CafeInteractionSession
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding='utf-8'),object_pairs_hook=unique_object)
    fields={'kind','format_version','core','interaction_config','relationship_path','relationships','policy_version','auto_assign'}
    if (not isinstance(data,dict) or set(data)!=fields or data['kind']!='cafe-save'
            or type(data['format_version']) is not int or data['format_version']!=1
            or type(data['auto_assign']) is not bool or data['policy_version']!=AutomaticInteractionPolicy.version):
        raise ValueError('対応していない営業セーブです。再生ログとは別の形式です。')
    if not isinstance(data['relationship_path'],str) or not Path(data['relationship_path']).is_absolute():
        raise ValueError('invalid relationship path')
    if Path(data['relationship_path']).resolve()==path:
        raise ValueError('営業セーブと関係データは別のファイルが必要です。')
    core=verify_cafe_interaction(data['core'])
    config=RelationshipConfig.from_dict(data['interaction_config'])
    store=RelationshipStore(data['relationship_path'])
    current=store._read()
    persisted=validate_progress(core,data['relationships'],current)
    session=CafeInteractionSession(core,store,config)
    session.persisted=persisted
    session.checkpoint_path=path
    session.checkpoint_baseline=copy.deepcopy(current)
    return session,data['auto_assign']
