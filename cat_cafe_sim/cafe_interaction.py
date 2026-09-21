"""営業交流の操作と関係保存。未保存結果がある間は次の営業操作を止める。"""
from dataclasses import asdict, replace
from pathlib import Path
import json

from .core.multi_seat_cafe import MultiSeatCafeCore
from .core.cafe_interaction import CafeInteractionCore, verify_cafe_interaction
from .core.human_cat_relationship import RelationshipConfig, verify_relationship
from .storage.relationships import RelationshipStore


class CafeInteractionSession:
    def __init__(self, core=None, store=None, interaction_config=None, *, cat_ids=None, cafe_config=None, seat_count=None):
        self.store = store or RelationshipStore('saves/cafe_relationships.json')
        if core is not None and (cat_ids is not None or cafe_config is not None or seat_count is not None):
            raise ValueError('coreと営業設定・参加猫は同時に指定できません。')
        profiles = {row['cat_id']:row for row in self.store.list_cats()}
        if core is None:
            ids = list(cat_ids) if cat_ids is not None else list(profiles) or ['cat-1']
            if cat_ids is not None and any(key not in profiles for key in ids):
                raise ValueError('参加する猫は先に登録してください。')
            if seat_count not in (None,1,2):
                raise ValueError('席数は1または2を指定してください。')
            core_type = CafeInteractionCore if seat_count == 1 else MultiSeatCafeCore
            core = core_type(cafe_config, cat_ids=ids, compact=True)
            from .core.cafe_health import HealthRules
            core.set_shifts(ids)
            core.enable_health(asdict(HealthRules.load()))
        self.core = core
        self.profiles = profiles
        self.affinities = {(r['cat_id'],r['customer_id']):r['affinity'] for r in self.store.list_relationships()}
        from .core.human_cat_types import load_presets
        self.presets = load_presets()
        self.interaction_config = interaction_config or RelationshipConfig.load()
        if self.core.config.max_stamina != self.interaction_config.max_stamina:
            raise ValueError('営業と交流の体力上限を同じ値にしてください。')
        self.persisted = set()
        self.checkpoint_path = None
        self.checkpoint_baseline = None
        from .policies.human_cat import AutomaticInteractionPolicy
        self.policy = AutomaticInteractionPolicy()

    @property
    def cat_name(self):
        return self.profiles.get(self.core.cat.id, {}).get('name', self.core.cat.id)

    @property
    def active_interactions(self):
        if isinstance(self.core,MultiSeatCafeCore):
            return self.core.interactions
        return {self.core.seat.id:self.core.active} if self.core.active else {}

    @property
    def free_seats(self):
        seats = self.core.seats if isinstance(self.core,MultiSeatCafeCore) else {self.core.seat.id:self.core.seat}
        return [key for key in seats if key not in self.active_interactions]

    def available_cats(self):
        return [cat for cat in self.core.cats.values()
                if self.core.activity(cat.id)=='cafe' and cat.id in self.core.working_cats and cat.health_status == 'healthy' and not cat.cannot_continue and cat.stamina > 0
                and cat.id not in {item.cat_id for item in self.active_interactions.values()}]

    def cat_choices(self, customer_id=None):
        from .core.human_cat_types import Personality
        rows = []
        for cat_id,cat in self.core.cats.items():
            profile = self.profiles.get(cat_id)
            personality = Personality.from_dict(profile['personality']) if profile else self.interaction_config.personality
            label = next((name for name,value in self.presets.items() if value == personality), 'カスタム')
            rows.append(dict(cat_id=cat_id,name=profile['name'] if profile else cat_id,personality=label,
                             stamina=cat.stamina,fatigue=cat.fatigue,health_status=cat.health_status,
                             recovery_days_remaining=cat.recovery_days_remaining,working=cat_id in self.core.working_cats,affinity=self.affinities.get((cat_id,customer_id),0),
                             available=cat in self.available_cats()))
        return rows

    @property
    def pending(self):
        return set(self.core.outcomes) - self.persisted

    def _ready(self):
        from .storage.cafe_saves import check_link
        check_link(self)
        if self.pending:
            raise ValueError('未保存の交流結果があります。先に保存を再試行してください。')
        self.core.require_events_resolved()

    def play_with_player(self, cat_id):
        self._ready()
        from .core.cafe_player import SET_TICKS
        from .core.human_cat_types import Personality
        config = self.interaction_config
        profile = self.profiles.get(cat_id)
        if profile:
            config = replace(config, personality=Personality.from_dict(profile['personality']))
        config = replace(config, ticks=SET_TICKS, max_stamina=self.core.config.max_stamina)
        self.core.play_with_player(cat_id, config.to_dict())

    def player_command(self, action=None, target_type=None, *, finish=False):
        from .storage.cafe_saves import check_link
        check_link(self)
        if self.pending:
            raise ValueError('先に交流結果の保存を再試行してください。')
        self.core.player_command(action, target_type, finish=finish)

    def dispatch(self, cat_id, rules=None):
        self._ready()
        self.core.dispatch(cat_id, rules)

    def open_recruitment(self):
        if self.core.recruitment is not None:
            return
        self._ready()
        from .core.cafe_recruitment import candidates
        data = self.store._read()
        used = set(self.core.cats) | set(data.get('cats', {})) | {row['cat_id'] for row in data['pairs']}
        self.core.open_recruitment(candidates(used))

    def recruit_cat(self, cat_id):
        import copy
        from .core.human_cat_types import Personality
        from .storage.relationships import RelationshipConflict
        self._ready()
        # Validate the complete change before touching the shared relationship file.
        updated = copy.deepcopy(self.core)
        updated.recruit_cat(cat_id)
        row = updated.recruitment['candidates'][cat_id]
        data = self.store._read()
        if cat_id in data.get('cats', {}) or any(p['cat_id'] == cat_id for p in data['pairs']):
            raise RelationshipConflict('この候補の猫IDはすでに関係データに登録されています。')
        profile = self.store._register(data, cat_id, row['name'], Personality.from_dict(row['personality']))
        profiles = dict(self.profiles, **{cat_id: dict(cat_id=cat_id, **profile)})
        baseline = copy.deepcopy(data) if self.checkpoint_baseline is not None else None
        self.store._write(data)
        self.core = updated
        self.profiles = profiles
        self.checkpoint_baseline = baseline

    def enable_management(self, rules=None):
        self._ready()
        self.core.enable_management(rules)

    def resolve_missing(self, event_id):
        from .storage.cafe_saves import check_link
        check_link(self)
        if self.pending:
            raise ValueError('先に接客結果の保存を再試行してください。')
        self.core.resolve_missing(event_id)

    def configure_adoption(self, enabled):
        self._ready()
        self.core.configure_adoption(enabled)

    def resolve_adoption(self, event_id, choice):
        from .storage.cafe_saves import check_link
        check_link(self)
        if self.pending:
            raise ValueError('先に交流結果の保存を再試行してください。')
        self.core.resolve_adoption(event_id, choice)

    def resolve_activity(self, event_id):
        from .storage.cafe_saves import check_link
        check_link(self)
        if self.pending:
            raise ValueError('先に交流結果の保存を再試行してください。')
        self.core.resolve_activity(event_id)

    def set_shifts(self, working_cats):
        self._ready()
        from .core.cafe_health import HealthRules
        health_rules = None if self.core.health_rules else asdict(HealthRules.load())
        self.core.set_shifts(working_cats)
        if health_rules is not None:
            self.core.enable_health(health_rules)

    def day_off(self):
        self._ready()
        if not self.core.can_set_shifts:
            raise ValueError('休業は営業開始前に選んでください。')
        if not self.core.shift_rules or not self.core.health_rules:
            self.set_shifts(sorted(self.core.working_cats))
        self.core.day_off()

    def next_day(self):
        self._ready()
        self.core.next_day()

    def start(self, customer_id, cat_id=None, seat_id=None):
        self._ready()
        cat_id = self.core.cat.id if cat_id is None else cat_id
        if cat_id not in self.core.cats:
            raise ValueError('営業に参加している猫を選んでください。')
        config = replace(self.interaction_config,
                         ticks=min(self.interaction_config.ticks, self.core.config.opening_ticks-self.core.tick))
        interaction = self.store.begin(config, cat_id, customer_id, stamina=self.core.cats[cat_id].stamina)
        if isinstance(self.core,MultiSeatCafeCore):
            self.core.start(interaction,seat_id)
        else:
            if seat_id not in (None,self.core.seat.id):
                raise ValueError('不明な席です。')
            self.core.start(interaction)

    def step(self, action=None, target_type=None):
        self._ready()
        if isinstance(self.core,MultiSeatCafeCore):
            if len(self.active_interactions)>1:
                raise ValueError('複数席の交流は自動進行を使ってください。')
            if not self.active_interactions and (action is not None or target_type is not None):
                raise ValueError('先に交流を開始してください。')
            self.core.step({key:(action,target_type) for key in self.active_interactions})
        else:
            self.core.step(action, target_type)
        self.persist()

    def automatic_step(self, *, auto_assign=True):
        """最大1営業tick進める。手動割り当て待ちではFalseを返す。"""
        self._ready()
        if self.core.closed:
            return False
        while self.free_seats and self.core.queue and self.available_cats():
            if not auto_assign:
                return False
            cat = min(self.available_cats(), key=lambda cat: (-cat.stamina, cat.id))
            self.start(self.core.queue[0], cat.id, self.free_seats[0])
        if isinstance(self.core,MultiSeatCafeCore):
            commands={key:self.policy.choose(active.observation(),active.valid_actions())
                      for key,active in self.active_interactions.items()}
            self.core.step(commands)
            self.persist()
        elif self.core.active:
            active=self.core.active
            self.step(*self.policy.choose(active.observation(),active.valid_actions()))
        else:
            self.step()
        return True

    def finish(self):
        self.core.require_events_resolved()
        from .storage.cafe_saves import check_link
        check_link(self)
        self.core.finish()
        self.persist()

    def persist(self):
        from .storage.cafe_saves import check_link
        check_link(self)
        for session_id, log in self.core.outcomes.items():
            if session_id not in self.persisted:
                result = self.store.apply(verify_relationship(log))
                self.affinities[(result['cat_id'],result['customer_id'])] = result['affinity_after']
                self.persisted.add(session_id)
                if self.core.compact:
                    from .core.cafe_checkpoint import receipt
                    self.core.outcomes[session_id] = receipt(log)
                if self.checkpoint_baseline is not None:
                    self.checkpoint_baseline = self.store._read()

    def save_log(self, path):
        path = Path(path)
        if self.checkpoint_path is not None and path.resolve() == self.checkpoint_path:
            raise ValueError('営業ログと営業セーブは別のファイルにしてください。')
        if path.resolve() == self.store.path.resolve():
            raise ValueError('営業ログと関係保存先は別のファイルにしてください。')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.core.log(), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def main():
    import argparse
    from .core.config import Config
    parser = argparse.ArgumentParser(description='版4交流を営業へ接続する試遊')
    sub = parser.add_subparsers(dest='command', required=True)
    run = sub.add_parser('run')
    run.add_argument('--operations', nargs='+', help='検証用の手動操作列。省略時は自動割り当て・自動交流で閉店まで進行')
    run.add_argument('--relationships', type=Path, default=Path('saves/cafe_relationships.json'))
    run.add_argument('--output', type=Path, default=Path('reports/cafe_interaction.json'))
    run.add_argument('--config', type=Path)
    run.add_argument('--seats',type=int,choices=(1,2),default=None)
    run.add_argument('--cats', nargs='+', help='営業へ参加する登録済み猫ID。省略時は全登録猫')
    gui = sub.add_parser('gui')
    gui.add_argument('--resume',type=Path,help='営業セーブを一時停止状態で開く')
    gui.add_argument('--seats',type=int,choices=(1,2),default=None)
    gui.add_argument('--cats', nargs='+', help='営業へ参加する登録済み猫ID。省略時は全登録猫')
    gui.add_argument('--manual', action='store_true', help='検証用の手動コマンド画面')
    gui.add_argument('--relationships', type=Path, default=None)
    seed = sub.add_parser('seed-playtest',help='テスト用の猫5匹を追加（既存IDは変更しない）')
    seed.add_argument('--relationships',type=Path,default=Path('saves/cafe_relationships.json'))
    compact_save = sub.add_parser('compact-save',help='既存の営業セーブを別名の軽量形式へ変換')
    compact_save.add_argument('source',type=Path)
    compact_save.add_argument('target',type=Path)
    replay = sub.add_parser('replay'); replay.add_argument('path', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'compact-save':
            from .storage.cafe_saves import convert_game
            print(convert_game(args.source,args.target))
            return
        if args.command == 'seed-playtest':
            from .storage.playtest_cats import add_playtest_cats
            print(json.dumps({'added':add_playtest_cats(RelationshipStore(args.relationships))},ensure_ascii=False))
            return
        if args.command == 'gui':
            import tkinter as tk
            from .cafe_interaction_gui import CafeInteractionWindow, ManualCafeInteractionWindow
            if args.manual and args.seats == 2:
                parser.error('検証用の手動コマンド画面は1席です。通常画面で2席を試してください。')
            auto_assign=False
            if args.resume:
                if args.manual or args.cats or args.seats is not None or args.relationships is not None:
                    parser.error('--resumeは猫・席・保存先・手動モードの指定と併用できません。')
                from .storage.cafe_saves import load_game
                session,auto_assign=load_game(args.resume)
            else:
                session = CafeInteractionSession(store=RelationshipStore(args.relationships or 'saves/cafe_relationships.json'), cat_ids=args.cats,
                                                 seat_count=1 if args.manual else args.seats)
            root = tk.Tk()
            window = ManualCafeInteractionWindow if args.manual else CafeInteractionWindow
            app=window(root, session)
            if not args.manual:
                app.auto_assign.set(auto_assign)
                app.refresh()
            root.mainloop()
            return
        if args.command == 'replay':
            core = verify_cafe_interaction(json.loads(args.path.read_text(encoding='utf-8')))
        else:
            if args.output.resolve() == args.relationships.resolve():
                raise ValueError('営業ログと関係保存先は別のファイルにしてください。')
            session = CafeInteractionSession(store=RelationshipStore(args.relationships), cat_ids=args.cats,
                                             cafe_config=Config.load(args.config) if args.config else None,
                                             seat_count=args.seats if args.seats is not None else (1 if args.operations else 2))
            core = session.core
            try:
                if args.operations is None:
                    while not core.closed:
                        session.automatic_step()
                for operation in args.operations or ():
                    if operation == 'wait': session.step()
                    elif operation == 'finish': session.finish()
                    elif operation == 'retry': session.persist()
                    elif operation.startswith('start:'): session.start(operation.split(':', 1)[1])
                    elif operation.startswith('switch:'): session.step('switch', operation.split(':', 1)[1])
                    else: session.step(operation)
            finally:
                session.save_log(args.output)
            verify_cafe_interaction(core.log())
        print(json.dumps(core.summary(), ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
