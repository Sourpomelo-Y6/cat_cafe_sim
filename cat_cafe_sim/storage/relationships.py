"""単一プロセス向け関係保存。結果と適用済みIDを一括置換する。"""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile

from ..core.human_cat_relationship import RelationshipInteraction, identity
from ..core.human_cat_types import bounded, unique_object


class RelationshipConflict(ValueError):
    pass


class RelationshipStore:
    def __init__(self, path):
        self.path = Path(path)

    def _read(self):
        if not self.path.exists():
            return dict(format_version=1, pairs=[], applied={})
        data = json.loads(self.path.read_text(encoding='utf-8'), object_pairs_hook=unique_object)
        if set(data) != {'format_version','pairs','applied'} or type(data['format_version']) is not int or data['format_version'] != 1:
            raise ValueError('unsupported relationship store')
        if not isinstance(data['pairs'],list) or not isinstance(data['applied'],dict):
            raise ValueError('invalid relationship store')
        seen = set()
        for pair in data['pairs']:
            if set(pair) != {'cat_id','customer_id','affinity','revision'}:
                raise ValueError('invalid pair record')
            key = identity(pair['cat_id']), identity(pair['customer_id'])
            bounded(pair['affinity'],0,100,'saved affinity')
            if key in seen or type(pair['revision']) is not int or pair['revision'] < 1:
                raise ValueError('duplicate pair or invalid revision')
            seen.add(key)
        for key, applied in data['applied'].items():
            identity(key)
            if set(applied) != {'digest','result'} or not isinstance(applied['digest'],str) or len(applied['digest']) != 64:
                raise ValueError('invalid applied session')
            if not isinstance(applied['result'],dict) or applied['result'].get('session_id') != key:
                raise ValueError('invalid stored outcome')
        return data

    def snapshot(self, cat_id, customer_id):
        identity(cat_id); identity(customer_id)
        for pair in self._read()['pairs']:
            if (pair['cat_id'],pair['customer_id']) == (cat_id,customer_id):
                return dict(affinity=pair['affinity'],revision=pair['revision'])
        return dict(affinity=0,revision=0)

    def list_relationships(self):
        """保存順で各組み合わせの直近結果を取り出す。読み取りのみ。"""
        data = self._read()
        latest = {}
        for applied in data['applied'].values():
            result = applied['result']
            key = (identity(result.get('cat_id')), identity(result.get('customer_id')))
            for name in ('affinity_before', 'affinity_after'):
                bounded(result.get(name), 0, 100, name)
            bounded(result.get('affinity_delta'), -100, 100, 'affinity_delta')
            latest[key] = result
        return [dict(pair, latest_result=copy.deepcopy(latest.get((pair['cat_id'], pair['customer_id']))))
                for pair in sorted(data['pairs'], key=lambda pair: (pair['cat_id'], pair['customer_id']))]

    def begin(self, config, cat_id, customer_id, **kwargs):
        return RelationshipInteraction(config,cat_id=cat_id,customer_id=customer_id,
                                       **self.snapshot(cat_id,customer_id),**kwargs)

    def apply(self, core):
        result = core.result()
        digest = hashlib.sha256(json.dumps(core.log(),sort_keys=True,allow_nan=False).encode()).hexdigest()
        data = self._read()
        session_id = core.session_id
        if session_id in data['applied']:
            old = data['applied'][session_id]
            if old['digest'] != digest:
                raise RelationshipConflict('session ID already belongs to a different result')
            return copy.deepcopy(old['result'])
        initial = core.initial_relationship
        pair = next((p for p in data['pairs'] if (p['cat_id'],p['customer_id']) == (core.cat_id,core.customer_id)),None)
        revision, affinity = (pair['revision'],pair['affinity']) if pair else (0,0)
        if revision != initial['revision'] or affinity != initial['affinity']:
            raise RelationshipConflict('relationship changed since this session began')
        updated = dict(cat_id=core.cat_id,customer_id=core.customer_id,
                       affinity=result['affinity_after'],revision=revision+1)
        if pair:
            data['pairs'][data['pairs'].index(pair)] = updated
        else:
            data['pairs'].append(updated)
        data['applied'][session_id] = dict(digest=digest,result=result)
        self._write(data)
        return copy.deepcopy(result)

    def _write(self, data):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=self.path.parent,prefix='.'+self.path.name+'.',delete=False) as stream:
                temp_path = Path(stream.name)
                json.dump(data,stream,ensure_ascii=False,indent=2,allow_nan=False)
                stream.write('\n');stream.flush();os.fsync(stream.fileno())
            os.replace(temp_path,self.path)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()
