"""Read-only presentation of existing cafe logs and verified file replays."""
import json
from pathlib import Path
from .core.cafe_interaction import verify_cafe_interaction
from .human_cat_gui import ACTION_NAMES, REACTION_NAMES, history_row

PAGE_SIZE = 20
NAMES = {'start':'接客開始', 'step':'営業を進行', 'next_day':'翌日へ', 'start_business':'営業開始',
         'set_shifts':'出勤・休養の設定', 'day_off':'休業', 'human_cat_action':'猫との行動',
         'interaction_completed':'交流終了', 'customer_arrived':'来店', 'customer_departed':'退店',
         'player_begin':'プレイヤー交流開始', 'player_step':'プレイヤー交流の行動', 'player_finish':'プレイヤー交流終了'}
FIELDS = {'kind':'内容', 'day':'日目', 'tick':'営業時刻', 'cat_id':'猫', 'customer_id':'お客さん',
          'seat_id':'席', 'session_id':'交流ID', 'operation':'操作', 'events':'出来事', 'commands':'席ごとの行動',
          'interaction':'交流', 'record':'行動記録', 'result':'結果', 'before':'変更前', 'after':'変更後',
          'action':'行動', 'reaction':'反応', 'stamina':'体力', 'engagement':'関心', 'tension':'テンション',
          'affinity_pending':'親しみの見込み', 'affinity_delta':'親しみ増減', 'funds':'資金', 'revenue':'接客売上',
          'popularity':'人気', 'completed_interactions':'終了した交流', 'reason':'理由', 'working_cats':'出勤猫'}


def format_value(value, depth=0):
    if isinstance(value, dict):
        return '\n'.join('  '*depth+FIELDS.get(key,key)+'：'+('\n'+format_value(item,depth+1) if isinstance(item,(dict,list)) else format_value(item))
                         for key,item in value.items() if key!='state_digest')
    if isinstance(value, list):
        return '\n'.join('  '*depth+'・'+('\n'+format_value(item,depth+1) if isinstance(item,(dict,list)) else format_value(item)) for item in value) or 'なし'
    if value is None:return 'なし'
    if isinstance(value,bool):return 'はい' if value else 'いいえ'
    if isinstance(value,(int,float)):return f'{value:g}'
    return ACTION_NAMES.get(value,REACTION_NAMES.get(value,NAMES.get(value,str(value))))


def event_details(event):
    record=event.get('record')
    if isinstance(record,dict) and 'reaction' in record and 'after' in record:
        row=history_row(record)
        lines=[f"営業時刻：{event.get('tick','記録なし')} / 席：{event.get('seat_id','記録なし')}",
               f"交流{row[0]}ターン目 / 行動：{row[1]} / 反応：{row[2]}"]
        for key,label in (('engagement','関心'),('stamina','体力'),('tension','テンション'),('affinity_pending','親しみの見込み')):
            if key in record.get('before',{}) and key in record['after']:
                lines.append(f"{label}：{record['before'][key]:g} → {record['after'][key]:g}")
        if 'bonuses' in record:lines.append(f"ボーナス：{sum(record['bonuses'].values()):g}")
        return '\n'.join(lines)
    return format_value(event)


def load_log(path):
    source=Path(path)
    if not source.is_absolute():raise ValueError('営業ログの絶対パスを指定してください。')
    data=json.loads(source.read_text(encoding='utf-8-sig'))
    if not isinstance(data,dict):raise ValueError('営業ログの形式が不正です。')
    verify_cafe_interaction(data)
    return data


def projection(data,offset=0,source='現在の営業'):
    if type(offset) is not int or offset<0:raise ValueError('表示位置が不正です。')
    operations=data['operations'];total=len(operations)
    offset=min(offset,((total-1)//PAGE_SIZE)*PAGE_SIZE) if total else 0
    rows=[]
    for index,item in enumerate(operations[offset:offset+PAGE_SIZE],offset):
        operation=item['operation'];events=item.get('events',[])
        label=f"{index+1} / {NAMES.get(operation['kind'],operation['kind'])}"
        rows.append(dict(index=index,label=label,details=label+'\n\n出来事・行動の結果\n'+('\n\n'.join(event_details(event) for event in events) or 'この操作に出来事の記録はありません。')+'\n\n操作の記録\n'+format_value(operation)))
    return dict(offset=offset,total=total,rows=rows,source=source,
                summary='記録元：'+source+f"\nログ形式：{data['format_version']} / 操作数：{total}\n"+format_value(data['summary']),
                notes='記録されている操作と結果を表示します。再開前などの記録されていない行動は補いません。保存済みログはPythonのリプレイ検証を通過しています。' if source!='現在の営業' else '現在の営業ログです。ログは営業セーブとは別に出力します。再開前などの記録されていない行動は補いません。')
