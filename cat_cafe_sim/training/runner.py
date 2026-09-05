from dataclasses import asdict
import random

from cat_cafe_sim.envs import CatInteractionEnv
from .encoding import StateEncoder
from .model import CatModel
from .q_learning import QLearningAgent
from .start_profiles import choose_start


def train(config, rewards, settings, *, progress=None):
    settings.validate_starts(config)
    encoder = StateEncoder.for_config(config, settings.resource_edges, settings.time_edges, settings.stamina_edges)
    if encoder.summary()["state_upper_bound"] > settings.max_states:
        raise ValueError("state budget exceeded; reduce bins before training")
    agent = QLearningAgent(encoder, learning_rate=settings.learning_rate, discount=settings.discount, seed=settings.seed)
    scenarios = random.Random(f"{settings.seed}:training-scenarios")
    starts = random.Random(f"{settings.seed}:training-starts")
    env = CatInteractionEnv(config, rewards)
    rows = []
    for episode in range(settings.episodes):
        preferences = scenarios.choice(settings.train_preferences)
        profile, start_options = choose_start(settings.train_starts, starts)
        seed = settings.scenario_seed + episode
        observation, info = env.reset(seed=seed, options={"preferences": preferences, **start_options})
        initial = dict(info["initial_state"])
        epsilon = settings.epsilon(episode)
        totals = dict.fromkeys(asdict(rewards), 0.0)
        actions = [0] * 7
        total_reward = 0.0
        while True:
            state = encoder.encode(observation)
            action = agent.act(state, info["action_mask"], epsilon=epsilon, random_ties=True)
            next_observation, reward, terminated, truncated, next_info = env.step(action)
            agent.update(state, action, reward, encoder.encode(next_observation),
                         terminated=terminated, truncated=truncated, next_mask=next_info["bootstrap_action_mask"])
            total_reward += reward
            actions[action] += 1
            for key, value in next_info["reward_breakdown"].items():
                totals[key] += value
            observation, info = next_observation, next_info
            if terminated or truncated:
                break
        rows.append({"episode": episode + 1, "scenario_seed": seed,
                     "start_profile": profile, **{f"initial_{key}": value for key, value in initial.items()},
                     "play_preference": preferences[0], "pet_preference": preferences[1],
                     "epsilon": epsilon, "reward": total_reward,
                     "departure_reason": info["departure_reason"], **info["metrics"],
                     "known_states": len(agent.table), "updates": agent.updates,
                     **{f"reward_{k}": v for k, v in totals.items()},
                     **{f"action_{i}": count for i, count in enumerate(actions)}})
        if progress is not None:
            progress(rows[-1])
    env.close()
    return CatModel(agent, config, rewards, settings), rows
