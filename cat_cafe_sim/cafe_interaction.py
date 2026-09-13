"""営業交流の操作と関係保存。未保存結果がある間は次の営業操作を止める。"""
from dataclasses import replace
from pathlib import Path
import json

from .core.cafe_interaction import CafeInteractionCore, verify_cafe_interaction
from .core.human_cat_relationship import RelationshipConfig, verify_relationship
from .storage.relationships import RelationshipStore


class CafeInteractionSession:
    def __init__(self, core=None, store=None, interaction_config=None):
        self.core = core or CafeInteractionCore()
        self.store = store or RelationshipStore('saves/cafe_relationships.json')
        self.interaction_config = interaction_config or RelationshipConfig.load()
        if self.core.config.max_stamina != self.interaction_config.max_stamina:
            raise ValueError('営業と交流の体力上限を同じ値にしてください。')
        profile = self.store.cat_profile(self.core.cat.id)
        self.cat_name = profile['name'] if profile else self.core.cat.id
        self.persisted = set()
        from .policies.human_cat import AutomaticInteractionPolicy
        self.policy = AutomaticInteractionPolicy()

    @property
    def pending(self):
        return set(self.core.outcomes) - self.persisted

    def _ready(self):
        if self.pending:
            raise ValueError('未保存の交流結果があります。先に保存を再試行してください。')

    def start(self, customer_id, cat_id=None):
        self._ready()
        if cat_id is not None and cat_id != self.core.cat.id:
            raise ValueError('営業に参加している猫を選んでください。')
        config = replace(self.interaction_config,
                         ticks=min(self.interaction_config.ticks, self.core.config.opening_ticks-self.core.tick))
        interaction = self.store.begin(config, self.core.cat.id, customer_id, stamina=self.core.cat.stamina)
        self.core.start(interaction)

    def step(self, action=None, target_type=None):
        self._ready()
        self.core.step(action, target_type)
        self.persist()

    def automatic_step(self, *, auto_assign=True):
        """最大1営業tick進める。手動割り当て待ちではFalseを返す。"""
        self._ready()
        if self.core.closed:
            return False
        if self.core.active is None:
            cat = self.core.cat
            available = cat.health_status == 'healthy' and not cat.cannot_continue and cat.stamina > 0
            if self.core.queue and available:
                if not auto_assign:
                    return False
                self.start(self.core.queue[0], cat.id)
        if self.core.active:
            active = self.core.active
            action, target = self.policy.choose(active.observation(), active.valid_actions())
            self.step(action, target)
        else:
            self.step()
        return True

    def finish(self):
        self.core.finish()
        self.persist()

    def persist(self):
        for session_id, log in self.core.outcomes.items():
            if session_id not in self.persisted:
                self.store.apply(verify_relationship(log))
                self.persisted.add(session_id)

    def save_log(self, path):
        path = Path(path)
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
    gui = sub.add_parser('gui')
    gui.add_argument('--manual', action='store_true', help='検証用の手動コマンド画面')
    gui.add_argument('--relationships', type=Path, default=Path('saves/cafe_relationships.json'))
    replay = sub.add_parser('replay'); replay.add_argument('path', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'gui':
            import tkinter as tk
            from .cafe_interaction_gui import CafeInteractionWindow, ManualCafeInteractionWindow
            session = CafeInteractionSession(store=RelationshipStore(args.relationships))
            root = tk.Tk()
            window = ManualCafeInteractionWindow if args.manual else CafeInteractionWindow
            window(root, session)
            root.mainloop()
            return
        if args.command == 'replay':
            core = verify_cafe_interaction(json.loads(args.path.read_text(encoding='utf-8')))
        else:
            if args.output.resolve() == args.relationships.resolve():
                raise ValueError('営業ログと関係保存先は別のファイルにしてください。')
            core = CafeInteractionCore(Config.load(args.config) if args.config else None)
            session = CafeInteractionSession(core, RelationshipStore(args.relationships))
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
