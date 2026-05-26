"""超启发式策略（Hyper-heuristic UCB）。

把多个低层启发式当成“算子”，用 UCB1 在线选择当前最优算子：
- low-level heuristics: nearest / priority / deadline / heaviest
- reward proxy: 任务总优先级 - 路径代价
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.snapshot import Snapshot


def _chain_distance(vehicle, ordered: List, snap: Snapshot) -> float:
    waypoints = [(t.position.x, t.position.y) for t in ordered]
    return utils.estimate_chain_distance_with_recharge(
        vehicle, waypoints, snap, require_final_station_buffer=True
    )


class HyperHeuristicScheduler(Scheduler):
    name = "hyper_heuristic"

    def __init__(self):
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
            items.sort(key=lambda t: (-float(t.priority), snap.distance(vehicle.position, t.position)))
        elif op == "deadline":
            items.sort(key=lambda t: (float(t.deadline), snap.distance(vehicle.position, t.position)))
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

    def _ucb_score(self, op: str, total_pulls: int) -> float:
        pulls, reward_sum = self.stats[op]
        if pulls == 0:
            return float("inf")
        mean = reward_sum / pulls
        bonus = math.sqrt(2.0 * math.log(max(2, total_pulls)) / pulls)
        return mean + bonus

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

            total_pulls = sum(p for p, _r in self.stats.values()) + 1
            op = max(self.stats.keys(), key=lambda k: self._ucb_score(k, total_pulls))
            chosen = self._pick_by_op(op, vehicle, unclaimed, snap)

            # 更新算子奖励（代理）：优先级总和 - 里程/1000
            if chosen:
                ordered_xy = utils.greedy_chain(
                    (vehicle.position.x, vehicle.position.y),
                    [(t.position.x, t.position.y) for t in chosen],
                    snap,
                )
                id_by_xy = {(t.position.x, t.position.y): t for t in chosen}
                ordered = [id_by_xy[xy] for xy in ordered_xy if xy in id_by_xy]
                dist = _chain_distance(vehicle, ordered, snap)
                reward = sum(float(t.priority) for t in ordered) - (dist / 1000.0 if dist != float("inf") else 1000.0)
            else:
                reward = -5.0
            pulls, rsum = self.stats[op]
            self.stats[op] = (pulls + 1, rsum + reward)
            return chosen

        for v in snapshot.idle_vehicles_at_warehouse():
            cmd = utils.decide_at_warehouse(v, snapshot, pick_batch)
            if cmd.action == "deliver":
                claimed.update(cmd.assigned_tasks)
            commands.append(cmd)

        return commands

