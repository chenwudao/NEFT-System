"""Q-learning 调度策略（在线表格型）。

动作空间：每次从候选任务中选择一个“下一任务”加入批次。
状态离散化：
- 电量桶（低/中/高）
- 载重利用率桶
- 待选任务数桶
奖励代理：
- priority 奖励 - 距离惩罚 - 逾期风险惩罚
"""

from __future__ import annotations

import random
import time
from collections import defaultdict
from typing import Dict, List, Tuple

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.snapshot import Snapshot


class QLearningScheduler(Scheduler):
    name = "q_learning"

    def __init__(self):
        self.q: Dict[Tuple[Tuple[int, int, int], int], float] = defaultdict(float)
        self.alpha = 0.2
        self.gamma = 0.85
        self.epsilon = 0.15
        self.rng = random.Random(42)

    @staticmethod
    def _bucket_state(vehicle, candidates_count: int) -> Tuple[int, int, int]:
        b_pct = float(vehicle.get_battery_percentage())
        if b_pct < 35:
            b_bucket = 0
        elif b_pct < 70:
            b_bucket = 1
        else:
            b_bucket = 2

        util = 1.0 - (
            float(vehicle.get_remaining_load()) / max(1.0, float(vehicle.max_load))
        )
        if util < 0.34:
            u_bucket = 0
        elif util < 0.67:
            u_bucket = 1
        else:
            u_bucket = 2

        if candidates_count <= 3:
            c_bucket = 0
        elif candidates_count <= 8:
            c_bucket = 1
        else:
            c_bucket = 2
        return (b_bucket, u_bucket, c_bucket)

    def _reward(self, vehicle, task, snap: Snapshot, now_ts: int) -> float:
        d = snap.distance(vehicle.position, task.position)
        if d == float("inf"):
            return -1000.0
        overdue = 1.0 if float(task.deadline) < float(now_ts) else 0.0
        return float(task.priority) * 30.0 - (d / 200.0) - overdue * 80.0

    def _choose_action(self, state: Tuple[int, int, int], actions: List[int]) -> int:
        if not actions:
            return -1
        if self.rng.random() < self.epsilon:
            return self.rng.choice(actions)
        return max(actions, key=lambda a: self.q[(state, a)])

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        commands: List[Command] = []

        for v in snapshot.idle_vehicles_not_at_warehouse():
            commands.append(utils.decide_en_route(v, snapshot))

        claimed = set()
        now_ts = int(snapshot.timestamp or time.time())

        def pick_batch(vehicle, tasks, snap):
            unclaimed = [t for t in tasks if t.id not in claimed]
            unclaimed = utils.feasible_tasks_for(vehicle, unclaimed)
            if not unclaimed:
                return []

            chosen = []
            remaining = list(unclaimed)
            current_vehicle_proxy = vehicle

            while remaining:
                state = self._bucket_state(current_vehicle_proxy, len(remaining))
                actions = [t.id for t in remaining]
                a = self._choose_action(state, actions)
                if a < 0:
                    break
                task = next((t for t in remaining if t.id == a), None)
                if task is None:
                    break

                candidate = chosen + [task]
                ordered_xy = utils.greedy_chain(
                    (vehicle.position.x, vehicle.position.y),
                    [(t.position.x, t.position.y) for t in candidate],
                    snap,
                )
                id_by_xy = {(t.position.x, t.position.y): t for t in candidate}
                ordered = [id_by_xy[xy] for xy in ordered_xy if xy in id_by_xy]
                dist = utils.estimate_chain_distance_with_recharge(
                    vehicle,
                    [(t.position.x, t.position.y) for t in ordered],
                    snap,
                    require_final_station_buffer=True,
                )
                if dist == float("inf"):
                    remaining.remove(task)
                    continue

                reward = self._reward(vehicle, task, snap, now_ts)
                next_state = self._bucket_state(current_vehicle_proxy, max(0, len(remaining) - 1))
                future_q = 0.0
                if remaining:
                    future_q = max(self.q[(next_state, t.id)] for t in remaining)
                old_q = self.q[(state, a)]
                self.q[(state, a)] = old_q + self.alpha * (
                    reward + self.gamma * future_q - old_q
                )

                chosen = ordered
                remaining.remove(task)

            return chosen

        for v in snapshot.idle_vehicles_at_warehouse():
            cmd = utils.decide_at_warehouse(v, snapshot, pick_batch)
            if cmd.action == "deliver":
                claimed.update(cmd.assigned_tasks)
            commands.append(cmd)

        return commands

