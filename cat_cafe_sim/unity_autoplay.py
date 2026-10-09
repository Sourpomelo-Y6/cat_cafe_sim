"""Unityのおまかせ。通常操作を小さい単位で進め、回答待ちは利用者へ返す。"""
import copy
import json
import time
import uuid

from .cafe_autoplay import AutoPlayer, REASONS
from .cafe_autoplay_gui import autoplay_available, objective_targets
from .core import cafe_goal, cafe_bond_goal, cafe_patron, cafe_player

MODES = dict(basic='基礎営業',clear='安定経営',fast='積極経営')
OBJECTIVES = dict(popularity='人気',bond='好感度',patron='有力者')
NOTES = ('基礎営業は出勤・休養、安定経営・積極経営は投資や選んだ目標への交流・加入・派遣も任せます。'
         '費用と日程は通常操作と同じです。回答待ちのイベント・目標結果・期限切れ・ゲームオーバーで停止します。'
         'おまかせ中は自動配置し、終了後に元の割り当て設定へ戻します。中止は送信中の小さい操作単位が終わってから行います。'
         '終了後に保存してください。再接続・保存再開だけでは自動実行を再開しません。')


def problem(session):
    if not autoplay_available(session):
        return '経営ルールと挑戦中の人気・好感度・有力者目標が必要です。目標結果や未保存の交流結果を先に確認してください。'
    try:session._ready()
    except (ValueError,OSError) as error:return str(error)
    return ''


def metrics(session):
    c=session.core
    return dict(funds=c.funds,popularity=(c.management or {}).get('popularity',0),
                cats={key:dict(fatigue=cat.fatigue,stress=(c.management or {}).get('stress',{}).get(key,0),health=cat.health_status,activity=c.activity(key)) for key,cat in c.cats.items()})


def summary(session,before):
    after=metrics(session)
    rows=[f"資金：{before['funds']:g} → {after['funds']:g} / 人気：{before['popularity']:g} → {after['popularity']:g}"]
    from .core.cafe_activities import ACTIVITY_LABELS
    for key,cat in after['cats'].items():
        old=before['cats'].get(key,cat);name=session.profiles.get(key,{}).get('name',key)
        health=dict(healthy='健康',sick='療養')
        rows.append(f"{name}：疲労 {old['fatigue']:g} → {cat['fatigue']:g} / ストレス {old['stress']:g} → {cat['stress']:g} / {health.get(old['health'],old['health'])} → {health.get(cat['health'],cat['health'])} / {ACTIVITY_LABELS[old['activity']]} → {ACTIVITY_LABELS[cat['activity']]}")
    return '\n'.join(rows)


def projection(session,run=None):
    reason=problem(session);targets=objective_targets(session.core)
    running=bool(run and run['running'])
    return dict(running=running,reason=reason,can_start=not running and not reason,notes=NOTES,
                objectives=[dict(choice=k,label=OBJECTIVES[k],can_start=not running and not reason and target['status']=='active',status=target['status']) for k,target in targets.items()],
                modes=[dict(choice=k,label=v) for k,v in MODES.items()],report=report(run) if run else None)


def start(session,objective,mode,days,auto_assign):
    reason=problem(session);target=objective_targets(session.core).get(objective)
    if reason or not target or target['status']!='active':raise ValueError(reason or '挑戦中の対象目標を選んでください。')
    if mode not in MODES or type(days) is not int or not 1<=days<=10:raise ValueError('方針と1〜10日の進行日数を指定してください。')
    lines=[];player=AutoPlayer(session,objective=objective,mode=mode,max_days=days,stop_on_goal=True,emit=lines.append)
    lines.append('おまかせ目標：'+OBJECTIVES[objective]+f' / {days}日')
    return dict(version=1,run_id=uuid.uuid4().hex,running=True,objective=objective,mode=mode,limit=days,
                start_days=player.start_days,restore_auto_assign=auto_assign,before=metrics(session),
                days=0,operations=0,reason='',message='',summary=summary(session,metrics(session)),lines=lines,decisions=[])


def _player(session,run):
    player=AutoPlayer(session,objective=run['objective'],mode=run['mode'],max_days=run['limit'],stop_on_goal=True)
    player.start_days=run['start_days'];player.operations=run['operations']
    player.emit=run['lines'].append
    def decision(row):
        key=(row['day'],row['subject'])
        for index,old in enumerate(run['decisions']):
            if (old['day'],old['subject'])==key:run['decisions'][index]=row;break
        else:run['decisions'].append(row)
    player.on_decision=decision
    return player


def _terminal(player):
    c=player.session.core;target=objective_targets(c).get(player.objective)
    return (bool((c.management or {}).get('game_over')) or not target or target['status']!='active'
            or (c.goal['status']=='expired' and (player.objective=='popularity' or not c.goal['continued']))
            or cafe_goal.pending(c) or cafe_bond_goal.pending(c) or cafe_patron.pending(c)
            or player._days()-player.start_days>=player.max_days or player.operations>=player.max_operations)


def advance(session,run,*,cancel=False,batch_size=8):
    if not run or not run['running']:raise ValueError('実行中のおまかせはありません。')
    player=_player(session,run)
    if cancel:player.cancel()
    deadline=time.monotonic()+0.15
    for _ in range(batch_size):
        # 自分が開始したプレイヤー交流は方針どおり続ける。外部の通常操作は実行中に受け付けない。
        if not player.cancelled and not _terminal(player) and not cafe_player.active(session.core):
            try:session._ready()
            except (ValueError,OSError) as error:
                player._stop('blocked',str(error));break
        if not player.step():break
        if time.monotonic()>=deadline:break
    run['days']=player._days()-player.start_days;run['operations']=player.operations
    run['summary']=summary(session,run['before'])
    if player.result:
        run['running']=False;run['reason']=player.result.reason;run['message']=player.result.message
    return run['restore_auto_assign'] if not run['running'] else True


def report(run):
    keys=('version','run_id','running','objective','mode','limit','days','operations','reason','message','summary','lines','decisions')
    return copy.deepcopy({k:run[k] for k in keys})


def save_report(run,path):
    if run:
        if run['running']:raise ValueError('おまかせを中止してから保存してください。')
        path.write_text(json.dumps(report(run),ensure_ascii=False),encoding='utf-8')


def load_report(path):
    if not path.exists():return None
    if path.stat().st_size>8*1024*1024:raise ValueError('おまかせ記録のサイズが不正です。')
    data=json.loads(path.read_text(encoding='utf-8'))
    keys={'version','run_id','running','objective','mode','limit','days','operations','reason','message','summary','lines','decisions'}
    if not isinstance(data,dict) or set(data)!=keys or type(data['version']) is not int or data['version']!=1 or data['running'] is not False:raise ValueError('おまかせ記録の形式が不正です。')
    if any(not isinstance(data[k],str) for k in ('objective','mode','reason')) or data['objective'] not in OBJECTIVES or data['mode'] not in MODES or data['reason'] not in REASONS:raise ValueError('おまかせ記録の設定が不正です。')
    if any(type(data[k]) is not int for k in ('limit','days','operations')) or not 1<=data['limit']<=10 or not 0<=data['days']<=data['limit'] or not 0<=data['operations']<=10000:raise ValueError('おまかせ記録の日数・操作数が不正です。')
    if any(not isinstance(data[k],str) or len(data[k])>100000 for k in ('run_id','reason','message','summary')) or not isinstance(data['lines'],list) or len(data['lines'])>20000 or any(not isinstance(line,str) or len(line)>100000 for line in data['lines']):raise ValueError('おまかせ記録の文章が不正です。')
    if not isinstance(data['decisions'],list) or len(data['decisions'])>10000:raise ValueError('おまかせの判断記録が不正です。')
    for row in data['decisions']:
        if not isinstance(row,dict) or set(row)!={'day','target','choice','reason','subject','status'} or type(row['day']) is not int or row['day']<1 or any(not isinstance(row[k],str) or len(row[k])>100000 for k in ('target','choice','reason','subject','status')):raise ValueError('おまかせの判断記録が不正です。')
    return data
