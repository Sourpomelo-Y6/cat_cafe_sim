"""巨大な形式1セーブを、1操作ずつ検証して読み込む。全履歴を保持しない。"""
import json
import mmap
import re

from ..core.human_cat_types import unique_object

# JSON文字列は括弧を含んでも1トークンとして飛ばす。文字列の妥当性はjson.loadsで検証する。
TOKENS=re.compile(rb'"(?:[^"\\]|\\.)*"|[{}\[\]]')
STRING=re.compile(rb'"(?:[^"\\]|\\.)*"')
SCALAR=re.compile(rb'[^\s,}\]]+')


class JsonFile:
    def __init__(self, data):
        self.data=data

    def ws(self, i):
        while i<len(self.data) and self.data[i] in b' \t\r\n':i+=1
        return i

    def span(self, i):
        i=self.ws(i)
        if i>=len(self.data):raise ValueError('incomplete JSON')
        first=self.data[i]
        if first in (123,91):
            depth=0
            for match in TOKENS.finditer(self.data,i):
                token=match.group()
                if token in (b'{',b'['):depth+=1
                elif token in (b'}',b']'):
                    depth-=1
                    if depth==0:return i,match.end()
            raise ValueError('incomplete JSON container')
        match=(STRING if first==34 else SCALAR).match(self.data,i)
        if not match:raise ValueError('invalid JSON value')
        return i,match.end()

    def value(self, span):
        return json.loads(self.data[span[0]:span[1]],object_pairs_hook=unique_object)

    def members(self, start):
        i=self.ws(start)
        if self.data[i]!=123:raise ValueError('expected JSON object')
        i=self.ws(i+1);seen=set()
        if self.data[i]==125:return
        while True:
            key_span=self.span(i);key=self.value(key_span)
            if not isinstance(key,str) or key in seen:raise ValueError('duplicate or invalid key')
            seen.add(key)
            i=self.ws(key_span[1])
            if self.data[i]!=58:raise ValueError('expected colon')
            value_span=self.span(i+1)
            yield key,value_span
            i=self.ws(value_span[1])
            if self.data[i]==125:return
            if self.data[i]!=44:raise ValueError('expected comma')
            i=self.ws(i+1)

    def array(self, start):
        i=self.ws(start)
        if self.data[i]!=91:raise ValueError('expected JSON array')
        i=self.ws(i+1)
        if self.data[i]==93:return
        while True:
            span=self.span(i)
            yield self.value(span)
            i=self.ws(span[1])
            if self.data[i]==93:return
            if self.data[i]!=44:raise ValueError('expected comma')
            i=self.ws(i+1)


def read_game(path):
    from ..core.cafe_interaction import CafeInteractionCore
    from ..core.multi_seat_cafe import MultiSeatCafeCore
    from ..core.config import Config
    from ..core.models import StartState
    from ..core.cafe_replay import apply_operation
    with open(path,'rb') as stream:
        if not stream.seek(0,2):raise ValueError('empty save')
        stream.seek(0)
        with mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ) as data:
            reader=JsonFile(data)
            outer=reader.span(0)
            if reader.ws(outer[1])!=len(data):raise ValueError('trailing JSON data')
            fields=dict(reader.members(outer[0]))
            if 'format_version' not in fields:raise ValueError('missing save version')
            version=reader.value(fields['format_version'])
            if version!=1:
                return reader.value(outer),None
            payload={key:reader.value(span) for key,span in fields.items() if key!='core'}
            core_fields=dict(reader.members(fields['core'][0]))
            metadata={key:reader.value(span) for key,span in core_fields.items() if key!='operations'}
            version=metadata.get('format_version')
            if version not in (1,2,3) or metadata.get('mode_id')!='cafe-human-cat':
                raise ValueError('unsupported legacy cafe log')
            cls=MultiSeatCafeCore if version==3 else CafeInteractionCore
            core=cls(Config.from_dict(metadata['config']),seed=metadata['seed'],
                     start_state=StartState(**metadata['start_state']),cat_ids=metadata.get('cat_ids'))
            for item in reader.array(core_fields['operations'][0]):
                core.operations.clear();core.records.clear()
                apply_operation(core,item['operation'])
                if not core.operations or core.operations[-1]!=item:
                    raise ValueError('legacy cafe replay mismatch')
            final=core.log();final.pop('operations')
            if final!=metadata:raise ValueError('legacy cafe metadata or summary mismatch')
            payload['core']=None
            return payload,core
