"""営業途中のチェックポイント。読み込みで会計や関係更新を実行しない。"""
import copy
from pathlib import Path

from .relationships import RelationshipStore, RelationshipConflict
from ..core.human_cat_relationship import RelationshipConfig, verify_relationship
from ..policies.human_cat import AutomaticInteractionPolicy


class MemoryRelationships(RelationshipStore):
    def __init__(self, data):
        self.data = copy.deepcopy(self.validate_data(data))

    def _read(self):
        return copy.deepcopy(self.data)

    def _write(self, data):
        self.data = copy.deepcopy(data)


def validate_progress(core, baseline, current):
    """既知の未保存結果の適用だけを許す。確定済み成果はハッシュで照合する。"""
    from ..core.cafe_checkpoint import receipt, is_receipt
    expected = MemoryRelationships(baseline)
    actual = MemoryRelationships(current)
    matched = expected.data == current
    persisted = set()
    for session_id, log in core.outcomes.items():
        saved = receipt(log)
        applied = dict(digest=saved['digest'], result=saved['result'])
        if session_id in baseline['applied']:
            if baseline['applied'][session_id] != applied:
                raise RelationshipConflict('保存済みの交流結果と営業の記録が一致しません。')
        else:
            if is_receipt(log):
                raise RelationshipConflict('照合用の交流結果が関係データから失われています。')
            expected.apply(verify_relationship(log))
            matched = matched or expected.data == current
        if session_id in current['applied']:
            if current['applied'][session_id] != applied:
                raise RelationshipConflict('交流結果の内容が変更されています。')
            persisted.add(session_id)
    if not matched:
        raise RelationshipConflict('関係データがこの営業セーブより先へ進んでいるか、変更されています。新しい営業セーブを開いてください。')
    active = core.interactions.values() if hasattr(core,'interactions') else ([core.active] if core.active else [])
    for interaction in active:
        initial = interaction.initial_relationship
        pair = actual.snapshot(interaction.cat_id,interaction.customer_id)
        if (interaction.session_id in current['applied'] or pair != dict(affinity=initial['affinity'],revision=initial['revision'])):
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
    relationships = session.store._read()
    persisted = validate_progress(session.core,relationships,relationships)
    if not session.persisted <= persisted:
        raise RelationshipConflict('保存済みの交流結果が関係データから失われています。')
    from ..core.cafe_checkpoint import checkpoint
    state = checkpoint(session.core, set(session.core.outcomes)-persisted)
    payload = dict(kind='cafe-save',format_version=2,core=state,
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
    from .legacy_cafe_reader import read_game
    try:
        data, legacy = read_game(path)
    except (KeyError, TypeError, IndexError) as error:
        raise ValueError('営業セーブの形式が不正です。') from error
    fields={'kind','format_version','core','interaction_config','relationship_path','relationships','policy_version','auto_assign'}
    if (not isinstance(data,dict) or set(data)!=fields or data['kind']!='cafe-save'
            or type(data['format_version']) is not int or data['format_version'] not in (1,2)
            or type(data['auto_assign']) is not bool or data['policy_version']!=AutomaticInteractionPolicy.version):
        raise ValueError('対応していない営業セーブです。再生ログとは別の形式です。')
    if not isinstance(data['relationship_path'],str) or not Path(data['relationship_path']).is_absolute():
        raise ValueError('invalid relationship path')
    if Path(data['relationship_path']).resolve()==path:
        raise ValueError('営業セーブと関係データは別のファイルが必要です。')
    from ..core.cafe_checkpoint import checkpoint, restore
    try:
        core=legacy if data['format_version']==1 else restore(data['core'])
    except (KeyError, TypeError, IndexError) as error:
        raise ValueError('営業セーブの現在状態が不正です。') from error
    config=RelationshipConfig.from_dict(data['interaction_config'])
    store=RelationshipStore(data['relationship_path'])
    current=store._read()
    persisted=validate_progress(core,data['relationships'],current)
    if legacy is not None:
        core=restore(checkpoint(core,set(core.outcomes)-persisted))
    session=CafeInteractionSession(core,store,config)
    session.persisted=persisted
    session.checkpoint_path=path
    session.checkpoint_baseline=copy.deepcopy(current)
    return session,data['auto_assign']


def convert_game(source, target):
    """既存セーブを別名で形式2へ変換する。関係データを巻き戻さず、旧ファイルも変更しない。"""
    from .legacy_cafe_reader import read_game
    from ..core.cafe_checkpoint import checkpoint, restore
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target or target.exists():
        raise ValueError('変換先は存在しない別のファイルを指定してください。')
    data, legacy = read_game(source)
    fields={'kind','format_version','core','interaction_config','relationship_path','relationships','policy_version','auto_assign'}
    if (set(data)!=fields or data['kind']!='cafe-save' or type(data['format_version']) is not int
            or data['format_version'] not in (1,2) or type(data['auto_assign']) is not bool
            or data['policy_version']!=AutomaticInteractionPolicy.version):
        raise ValueError('対応していない営業セーブです。')
    relation=Path(data['relationship_path'])
    if not relation.is_absolute() or target==relation.resolve() or source==relation.resolve():
        raise ValueError('営業セーブと関係データは別のファイルが必要です。')
    RelationshipConfig.from_dict(data['interaction_config'])
    core=legacy if legacy is not None else restore(data['core'])
    baseline=RelationshipStore.validate_data(data['relationships'])
    persisted=validate_progress(core,baseline,baseline)
    state=checkpoint(core,set(core.outcomes)-persisted)
    restore(state)  # 書き出す前に復元と会計集計を検証する。
    converted=dict(data,format_version=2,core=state)
    RelationshipStore(target)._write(converted)
    return target
