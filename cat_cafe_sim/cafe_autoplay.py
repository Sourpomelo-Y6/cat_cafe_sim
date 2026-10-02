"""通常操作を一つずつ呼び出す、GUIにも依存しないテスト用自動プレイ。"""
import argparse
import json
import signal
import time
from dataclasses import dataclass
from pathlib import Path

from .core import cafe_goal, cafe_growth, cafe_management, cafe_player
from .core import cafe_adoption, cafe_customer_trust
from .core import cafe_dispatch_introduction, cafe_dispatch_trouble, cafe_dispatch_encounters
from .core import cafe_intake_request, cafe_regular_introduction, cafe_reservation, cafe_store_events


@dataclass(frozen=True)
class AutoPlayResult:
    reason: str
    days: int
    operations: int
    message: str


REASONS = dict(completed='目標達成', expired='人気目標の期限切れ',
               goal_cleared='目標の段階を達成',
               game_over='ゲームオーバー', day_limit='指定日数に到達',
               operation_limit='操作上限に到達', blocked='進行できません', cancelled='中断')


class AutoPlayer:
    """step()は最大一つの通常操作。停止要求は次の操作の前に確認する。"""

    def __init__(self, session, *, max_days=60, max_operations=10000,
                 emit=None, detailed=False, mode='basic', stop_on_goal=False, on_decision=None, objective='popularity'):
        if objective not in ('popularity', 'bond', 'patron'):
            raise ValueError('検証対象はpopularity・bond・patronを指定してください。')
        self.objective = objective
        if type(stop_on_goal) is not bool:
            raise ValueError('目標達成時の停止設定は真偽値で指定してください。')
        if mode not in ('basic', 'clear', 'fast'):
            raise ValueError('自動プレイ方針はbasic・clear・fastを指定してください。')
        for value in (max_days, max_operations):
            if type(value) is not int or value < 1:
                raise ValueError('日数・操作上限は正の整数で指定してください。')
        self.session = session
        self.mode = mode
        self.stop_on_goal = stop_on_goal
        self.max_days = max_days
        self.max_operations = max_operations
        self.emit = emit or (lambda line: None)
        self.on_decision = on_decision
        self.decisions = []
        self.detailed = detailed
        self.start_days = self._days()
        self.operations = 0
        self.cancelled = False
        self.result = None
        self.names = {key: row['name'] for key, row in session.profiles.items()}
        self.emit(f'自動プレイ方針: {"基礎営業" if mode=="basic" else ("安定経営" if mode=="clear" else "積極経営")}')

    def _name(self, key):
        return self.session.profiles.get(key, {}).get('name', self.names.get(key, key))

    def _decision(self, target, choice, reason, subject=None):
        self.decisions.append(dict(day=self.session.core.day, target=target, choice=choice, reason=reason,
                                   subject=subject or target))

    def _publish_decisions(self, status):
        if self.on_decision:
            for row in self.decisions:
                self.on_decision(dict(row, status=status))

    def _days(self):
        return len((self.session.core.goal or {}).get('days', []))

    def cancel(self):
        self.cancelled = True

    def _stop(self, reason, message=''):
        self.result = AutoPlayResult(reason, self._days()-self.start_days,
                                     self.operations, message)
        goal = self.session.core.goal
        if self.objective != 'popularity':
            from .core.cafe_bond_goal import progress as bond_progress
            from .core.cafe_patron import progress as patron_progress
            self.emit('最終状況: '+(bond_progress(self.session.core) if self.objective == 'bond' else patron_progress(self.session.core)))
        if goal and goal.get('tracking_only'):
            self.emit(f'最終状況: 人気集計 {self.session.core.management["popularity"]:g} / 資金 {self.session.core.funds:g}')
        elif goal:
            self.emit(f'最終状況: 人気第{len(goal.get("history", []))+1}段階'
                      f' / 人気 {self.session.core.management["popularity"]:g}'
                      f' / 目標 {cafe_goal.current_rules(goal)["target"]:g}'
                      f' / 不足人気 {max(0, cafe_goal.current_rules(goal)["target"]-self.session.core.management["popularity"]):g}'
                      f' / 資金 {self.session.core.funds:g}')
        self.emit(f'終了: {REASONS[reason]} / {self.result.days}日 / {self.operations}操作'
                  + (f' / {message}' if message else ''))
        return False

    def _answer(self):
        s, c = self.session, self.session.core
        if s.pending:
            return '未保存の交流結果を保存', s.persist
        if cafe_player.active(c) and self.objective=='bond' and self.mode!='basic':
            from .cafe_autoplay_objectives import player_action
            interaction = cafe_player.current(c)
            action, target = player_action(interaction)
            return f'プレイヤー交流: {action}'+(f' / {target}' if target else ''), lambda: s.player_command(action, target)
        if cafe_player.active(c):
            return '進行中のプレイヤー交流を終了', lambda: s.player_command(finish=True)
        # 依頼・紹介への回答は店舗イベントの解決が前提。先に対応する。
        event = cafe_store_events.waiting(c)
        if event:
            choice = 'repair' if event['type']=='trouble' else 'decline'
            return ('設備を修理（席数を維持）' if choice=='repair' else '支援依頼を見送り（追加支出を避ける）'), lambda: s.resolve_store_event(choice)
        for pending, action, label in (
            (cafe_intake_request.pending, s.resolve_intake_request, '保護猫の受け入れ依頼'),
            (cafe_regular_introduction.pending, s.resolve_regular_introduction, '常連からの紹介'),
            (cafe_reservation.waiting, s.resolve_reservation, '特別予約')):
            if pending(c):
                if self.mode!='basic' and pending is cafe_reservation.waiting:
                    request = cafe_reservation.waiting(c)
                    longhair = any('long_hair' in features and c.activity(key)=='cafe'
                                   and (c.cats[key].health_status=='healthy' or c.cats[key].recovery_days_remaining<=1)
                                   for key, features in (c.cat_features or {}).items())
                    days_left = cafe_goal.current_start(c.goal)+cafe_goal.current_rules(c.goal)['days']-1-request['visit_day']
                    choice = 'accept' if longhair and days_left>=0 else 'decline'
                    checks = ['長毛猫が在店（健康または翌日までに回復）' if longhair else '在店・回復予定の長毛猫がいない',
                              f'来店予定{request["visit_day"]}日目は目標期限内' if days_left>=0 else
                              f'来店予定{request["visit_day"]}日目が目標期限を超える']
                    self._decision('特別予約', '受諾' if choice=='accept' else '見送り', '／'.join(checks))
                    return f'特別予約を{"受諾" if choice=="accept" else "見送り"}（長毛猫の在店と目標期限を確認）', lambda: s.resolve_reservation(choice)
                if pending is cafe_reservation.waiting:
                    self._decision('特別予約', '見送り', '基礎営業は予約を増やさずに営業を確認する方針')
                return f'{label}を見送り（加入・予約を増やさず基礎営業を確認）', lambda action=action: action('decline')
        for waiting, action, choice, label in (
            (cafe_dispatch_introduction.waiting, s.resolve_dispatch_introduction, 'decline', '派遣先からの紹介を見送り'),
            (cafe_dispatch_trouble.waiting, s.resolve_dispatch_trouble, 'wait', '派遣トラブルは帰還を待つ（追加支出を避ける）'),
            (cafe_adoption.waiting, s.resolve_adoption, 'decline', '譲渡を見送り（現在の猫を維持）'),
            (cafe_customer_trust.waiting, s.resolve_customer_trust, 'ignore', '信頼回復を見送り（追加の介入を避ける）')):
            rows = waiting(c)
            if rows:
                event_id = rows[0]['id']
                return f'{label}: {event_id}', lambda action=action, event_id=event_id, choice=choice: action(event_id, choice)
        rows = cafe_dispatch_encounters.waiting(c)
        if rows:
            event = rows[0]
            choice = min(event['encounter']['rules']['choices'],
                         key=lambda row: (max(0, row['fatigue'])+max(0, row['stress']), row['id']))['id']
            return f'派遣イベントに回答: {choice}（疲労・ストレスの増加を抑える）', lambda: s.resolve_dispatch_choice(event['id'], choice)
        rows = [e for e in (c.activities or {}).get('events', {}).values() if e['status']=='waiting']
        if rows:
            return f'派遣帰還を確認: {rows[0]["id"]}', lambda: s.resolve_activity(rows[0]['id'])
        rows = cafe_management.waiting(c)
        if rows:
            return f'行方不明の猫の帰還を確認: {rows[0]["id"]}', lambda: s.resolve_missing(rows[0]['id'])
        for pending, choices, action, label in (
            (cafe_growth.pending, lambda c, key: ('service',), s.resolve_growth, '接客の得意分野'),
            (cafe_growth.mastery_pending, cafe_growth.mastery_choices, s.resolve_growth_mastery, '接客分類の熟練'),
            (cafe_growth.type_mastery_pending, cafe_growth.type_mastery_choices, s.resolve_growth_type_mastery, '個別行動の熟練')):
            rows = pending(c)
            if rows:
                key = sorted(rows)[0]
                options = choices(c, key)
                if not options:
                    raise ValueError(f'{key}の熟練に選択可能な候補がありません。')
                choice = options[0]
                return f'{key}: {label}を選択 {choice}（設定順の候補を採用）', lambda action=action, key=key, choice=choice: action(key, choice)
        from .core.cafe_bond_goal import pending as bond_pending
        from .core.cafe_patron import pending as patron_pending
        if bond_pending(c):
            return '好感度目標の結果を確認', s.continue_bond_goal
        if patron_pending(c):
            return '有力者目標の結果を確認', s.continue_patron
        return None

    def step(self):
        if self.result is not None:
            return False
        s, c = self.session, self.session.core
        if self.cancelled:
            return self._stop('cancelled')
        if cafe_management.is_over(c):
            return self._stop('game_over', str(c.management['game_over']))
        target = c.goal if self.objective=='popularity' else c.bond_goal if self.objective=='bond' else c.patron
        if not c.goal or not target or (self.objective=='popularity' and c.goal.get('tracking_only')):
            return self._stop('blocked', '検証対象の目標が有効なゲームを指定してください。')
        if c.goal['status']=='expired' and (self.objective=='popularity' or not c.goal['continued']):
            return self._stop('expired')
        if (self.objective!='popularity' and target['status']=='cleared') or (self.objective=='popularity' and c.goal['status']=='cleared' and cafe_goal.next_rules(c.goal) is None):
            return self._stop('completed')
        if self.stop_on_goal:
            from .core.cafe_bond_goal import pending as bond_pending
            from .core.cafe_patron import pending as patron_pending
            if c.goal['status']=='cleared' or bond_pending(c) or patron_pending(c):
                return self._stop('goal_cleared', '結果を確認してから通常操作へ戻れます。')
        if self._days()-self.start_days >= self.max_days:
            return self._stop('day_limit')
        if self.operations >= self.max_operations:
            return self._stop('operation_limit')
        before_days = self._days()
        before_operations = len(c.operations)
        day = c.day
        self.decisions = []
        try:
            decision = self._answer()
            if decision is None:
                if c.goal['status']=='cleared' and (cafe_goal.next_rules(c.goal) is not None or not c.goal['continued']):
                    decision = (('次の人気段階に挑戦（3段階まで進行）', s.advance_goal)
                                if cafe_goal.next_rules(c.goal) is not None else ('人気目標の結果を確認して継続', s.continue_goal))
                elif c.closed:
                    decision = ('翌日の営業準備へ進む', s.next_day)
                elif c.can_set_shifts:
                    if self.objective!='popularity':
                        from .cafe_autoplay_objectives import prepare as prepare_objective
                        decision = prepare_objective(self)
                    if decision is None and self.mode!='basic' and self.objective!='patron':
                        from .cafe_autoplay_strategy import prepare
                        decision = prepare(s, self.emit, self._name, report=self._decision, mode=self.mode)
                    if decision is None:
                        decision = self._basic_preparation()
                else:
                    decision = ('自動接客を1刻み進める', s.automatic_step)
            label, action = decision
            if self.detailed or action != s.automatic_step or c.can_set_shifts:
                self.emit(f'{day}日目: {label}')
            progressed = action()
            self.operations += 1
            if progressed is False:
                self._publish_decisions('進行できず')
                return self._stop('blocked', '自動接客が進みませんでした。')
            self._publish_decisions('実行済み')
            if self.detailed:
                for row in c.operations[before_operations:]:
                    self.emit('  操作・結果: '+json.dumps(dict(operation=row['operation'], events=row['events']), ensure_ascii=False))
            if self._days() > before_days:
                self.emit(f'{day}日目の結果: 資金 {c.funds:g} / 人気 {c.management["popularity"]:g}'
                          f' / 人気獲得 {c.goal["days"][-1]["gain"]:g}'
                          f' / 人気目標 {"集計のみ" if c.goal.get("tracking_only") else dict(active="挑戦中", cleared="達成", expired="期限切れ")[c.goal["status"]]}')
                if self.objective != 'popularity':
                    from .core.cafe_bond_goal import progress as bond_progress
                    from .core.cafe_patron import progress as patron_progress
                    self.emit('  '+(bond_progress(c) if self.objective=='bond' else patron_progress(c)))
                for key, cat in sorted(c.cats.items()):
                    health = dict(healthy='健康', sick='療養中').get(cat.health_status, cat.health_status)
                    self.emit(f'  {self._name(key)}: 疲労 {cat.fatigue:g} / ストレス {c.management["stress"][key]:g} / 状態 {health}')
        except (ValueError, OSError) as error:
            self._publish_decisions(f'失敗：{error}')
            return self._stop('blocked', str(error))
        return True

    def _basic_preparation(self):
        s, c = self.session, self.session.core
        workers = sorted(key for key, cat in c.cats.items()
                         if c.activity(key)=='cafe' and cat.health_status=='healthy'
                         and cat.fatigue < 60 and c.management['stress'][key] < 60)
        for key, cat in sorted(c.cats.items()):
            if c.activity(key)!='cafe':
                choice, reason = '不在', '在店していないため出勤対象外'
            elif cat.health_status!='healthy':
                choice, reason = '療養', '病気のため出勤対象外'
            else:
                choice = '出勤' if key in workers else '休養'
                reason = f'現在の疲労{cat.fatigue:g}・ストレス{c.management["stress"][key]:g}。両方60未満なら出勤'
            self._decision(self._name(key), choice, reason, key)
        if not workers:
            self._decision('営業', '休業', '健康・在店かつ疲労・ストレス60未満の猫がいないため負担を回復')
            return ('全員休養のため休業（疲労・ストレス60以上、療養・不在）', s.day_off)
        elif set(workers)!=c.working_cats or not c.shift_rules:
            resting = sorted(set(c.cats)-set(workers))
            return (f'出勤: {", ".join(map(self._name, workers))} / 休養・不在: {", ".join(map(self._name, resting)) or "なし"}（健康・在店かつ疲労・ストレス60未満）', lambda: s.set_shifts(workers))
        else:
            return ('出勤予定で営業開始（健康・在店かつ疲労・ストレス60未満）', s.automatic_step)

    def run(self):
        while self.step():
            pass
        return self.result


def main(argv=None):
    parser = argparse.ArgumentParser(description='目標を通常操作で自動プレイし、日本語ログを出力します。')
    parser.add_argument('--objective', choices=('popularity', 'bond', 'patron'), default='popularity', help='検証対象の目標（再開時も指定）')
    parser.add_argument('--directory', default='reports/autoplay', help='新規テストゲームの保存先')
    parser.add_argument('--resume', type=Path, help='再開する営業セーブ（関係データも更新します）')
    parser.add_argument('--days', type=int, default=60)
    parser.add_argument('--mode', choices=('basic', 'clear', 'fast'), default='basic', help='basic:基礎営業 / clear:安定経営 / fast:積極経営')
    parser.add_argument('--max-operations', type=int, default=10000)
    parser.add_argument('--detailed', action='store_true')
    parser.add_argument('--interval', type=float, default=0, help='日次結果後の待機秒（0〜60）')
    args = parser.parse_args(argv)
    if args.days < 1 or args.max_operations < 1 or not 0 <= args.interval <= 60:
        parser.error('日数・操作数は1以上、待機は0〜60秒で指定してください。')
    from .cafe_new_game import create_game, starting_conditions
    from .storage.cafe_saves import load_game, save_game
    session = load_game(args.resume)[0] if args.resume else create_game(args.directory, starting_conditions(args.objective))
    log_path = session.checkpoint_path.parent/'autoplay.log'
    print(f'営業セーブ: {session.checkpoint_path}\n操作ログ: {log_path}', flush=True)
    with log_path.open('a', encoding='utf-8') as log:
        def emit(line):
            print(line, flush=True)
            log.write(line+'\n'); log.flush()
        player = AutoPlayer(session, max_days=args.days, max_operations=args.max_operations,
                            emit=emit, detailed=args.detailed, mode=args.mode, objective=args.objective)
        previous = signal.signal(signal.SIGINT, lambda *_: player.cancel())
        try:
            while player.result is None:
                before_days = player._days()
                if not player.step():
                    break
                save_game(session, session.checkpoint_path, auto_assign=True)
                if args.interval and player._days()>before_days:
                    time.sleep(args.interval)
            save_game(session, session.checkpoint_path, auto_assign=True)
        except (OSError, ValueError) as error:
            player._stop('blocked', f'営業セーブの保存に失敗: {error}')
        finally:
            signal.signal(signal.SIGINT, previous)
    return 1 if player.result.reason=='blocked' else 0


if __name__=='__main__':
    raise SystemExit(main())
