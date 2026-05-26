"""超启发式方法：epsilon-greedy 算子选择。

将低层启发式算子池化：
- nearest
- priority
- deadline
- heaviest

在线维护算子平均奖励，用 epsilon-greedy 在探索和利用之间折中。
"""

from __future__ import annotations

import random
from typing import Dict, List, Tuple

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.snapshot import Snapshot


def _chain_distance(vehicle, ordered: List, snap: Snapshot) -> float:
    waypoints = [(t.position.x, t.position.y) for t in ordered]
    return utils.estimate_chain_distance_with_recharge(
        vehicle, waypoints, snap, require_final_station_buffer=True
    )


class HyperHeuristicEpsScheduler(Scheduler):
    name = "hyper_heuristic_eps"

    def __init__(self):
        self.epsilon = 0.18
        self.rng = random.Random(11)
        # op -> (pulls, reward_sum)
        self.stats: Dict[str, Tuple[int, float]] = {
            "nearest": (0, 0.0),
            "priority": (0, 0.0),
            "deadline": (0, 0.0),
            "heaviest": (0, 0.0),
        }

    def _pick_by_op(self, op: str, vehicle, tasks, snap):
        items = list(tasks)
        if op == "nearest":
            items.sort(key=lambda t: snap.distance(vehicle.position, t.position))
        elif op == "priority":
            items.sort(
                key=lambda t: (-float(t.priority), snap.distance(vehicle.position, t.position))
            )
        elif op == "deadline":
            items.sort(
                key=lambda t: (float(t.deadline), snap.distance(vehicle.position, t.position))
            )
        else:  # heaviest
            items.sort(key=lambda t: (-float(t.weight), snap.distance(vehicle.position, t.position)))

        chosen = []
        start_xy = (vehicle.position.x, vehicle.position.y)
        for t in items:
            cand = chosen + [t]
            ordered_xy = utils.greedy_chain(
                start_xy, [(x.position.x, x.position.y) for x in cand], snap
            )
            id_by_xy = {(x.position.x, x.position.y): x for x in cand}
            ordered = [id_by_xy[xy] for xy in ordered_xy if xy in id_by_xy]
            if _chain_distance(vehicle, ordered, snap) == float("inf"):
                break
            chosen = cand
        return chosen

    def _choose_op(self) -> str:
        ops = list(self.stats.keys())
        if self.rng.random() < self.epsilon:
            return self.rng.choice(ops)
        def mean_reward(op: str) -> float:
            pulls, rs = self.stats[op]
            return rs / pulls if pulls > 0 else 0.0
        return max(ops, key=mean_reward)

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        commands: List[Command] = []

        for v in snapshot.idle_vehicles_not_at_warehouse():
            commands.append(utils.decide_en_route(v, snapshot))

        claimed = set()

        def pick_batch(vehicle, tasks, snap):
            unclaimed = [t for t in tasks if t.id not in claimed]
            unclaimed = utils.feasible_tasks_for(vehicle, unclaimed)
            if not unclaimed:
                return []

            op = self._choose_op()
            chosen = self._pick_by_op(op, vehicle, unclaimed, snap)

            # 奖励代理：优先级和 - 路程惩罚
            if chosen:
                ordered_xy = utils.greedy_chain(
                    (vehicle.position.x, vehicle.position.y),
                    [(t.position.x, t.position.y) for t in chosen],
                    snap,
                )
                id_by_xy = {(t.position.x, t.position.y): t for t in chosen}
                ordered = [id_by_xy[xy] for xy in ordered_xy if xy in id_by_xy]
                dist = _chain_distance(vehicle, ordered, snap)
                reward = sum(float(t.priority) for t in ordered) - (
                    dist / 1000.0 if dist != float("inf") else 1000.0
                )
            else:
                reward = -5.0

            pulls, rs = self.stats[op]
            self.stats[op] = (pulls + 1, rs + reward)
            return chosen

        for v in snapshot.idle_vehicles_at_warehouse():
            cmd = utils.decide_at_warehouse(v, snapshot, pick_batch)
            if cmd.action == "deliver":
                claimed.update(cmd.assigned_tasks)
            commands.append(cmd)

        return commands

