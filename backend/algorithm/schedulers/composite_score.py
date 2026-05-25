"""复合评分策略：综合"优先级、距离、紧迫度、重量"等多因素计算任务得分。

每辆车在仓库时，给所有候选任务打分，选得分最高的（同分按距离近优先）。

评分公式（可在 SCHEDULING_CONFIG.composite_weights 中调整权重）：
    score = priority_weight * (priority / max_priority)
          + urgency_weight  * urgency       (deadline 越近越高)
          + load_weight     * (weight / max_load)
          - distance_weight * (distance / scale_distance)

紧迫度 = max(0, 1 - (deadline - now) / urgency_window)，window 默认 2h。
"""

from __future__ import annotations

import time
from typing import Dict, List

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.snapshot import Snapshot
from backend.config import config


def _composite_weights() -> Dict[str, float]:
    """读 SCHEDULING_CONFIG.composite_weights；不存在时给默认值。"""
    sched_cfg = config.get_scheduling_config()
    base = {
        "priority":       1.0,
        "urgency":        1.5,
        "load":           0.3,
        "distance":       1.0,
        "scale_distance": 10000.0,   # 10km 作为距离归一化基准
        "urgency_window": 7200.0,    # 2h
    }
    overrides = sched_cfg.get("composite_weights") or {}
    base.update({k: float(v) for k, v in overrides.items() if v is not None})
    return base


class CompositeScoreScheduler(Scheduler):
    name = "composite_score"

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        commands: List[Command] = []

        for v in snapshot.idle_vehicles_not_at_warehouse():
            commands.append(utils.decide_en_route(v, snapshot))

        claimed = set()
        weights = _composite_weights()
        now = float(snapshot.timestamp or time.time())

        task_cfg = config.get_task_config()
        max_priority = max(1, int(task_cfg.get("max_priority", 5)))

        def pick_best(vehicle, tasks, snap):
            unclaimed = [t for t in tasks if t.id not in claimed]
            unclaimed = utils.feasible_tasks_for(vehicle, unclaimed)
            if not unclaimed:
                return []

            scale_dist = weights["scale_distance"] or 1.0
            urgency_window = weights["urgency_window"] or 1.0
            max_load = max(1.0, float(vehicle.max_load))

            def score(t):
                d = snap.distance(vehicle.position, t.position)
                if d == float("inf"):
                    return -float("inf")
                remaining = max(0.0, float(t.deadline) - now)
                urgency = max(0.0, 1.0 - remaining / urgency_window)
                return (
                    weights["priority"] * (float(t.priority) / max_priority)
                    + weights["urgency"] * urgency
                    + weights["load"] * (float(t.weight) / max_load)
                    - weights["distance"] * (d / scale_dist)
                )

            unclaimed.sort(
                key=lambda t: (-score(t), snap.distance(vehicle.position, t.position))
            )
            return [unclaimed[0]]

        for v in snapshot.idle_vehicles_at_warehouse():
            cmd = utils.decide_at_warehouse(v, snapshot, pick_best)
            if cmd.action == "deliver":
                claimed.update(cmd.assigned_tasks)
            commands.append(cmd)

        return commands
