import random


class FixedCatPolicy:
    version = "fixed-cat-v1"

    def choose(self, observation):
        # 非公開の好みを参照せず、交流種類を交互に選ぶ。
        return 4 if observation["previous_action"] == 1 else 1


class RandomCatPolicy:
    version = "random-cat-v1"

    def __init__(self, seed):
        self.rng = random.Random(f"{seed}:policy")

    def choose(self, observation):
        return self.rng.randrange(7)


class FixedManagerPolicy:
    version = "fifo-manager-v1"

    def choose(self, observation):
        from cat_cafe_sim.core import Command
        if observation["queue"] and observation["seat"]["customer_id"] is None and not observation["cat"]["cannot_continue"]:
            return Command("assign", observation["queue"][0])
        return Command("wait")
