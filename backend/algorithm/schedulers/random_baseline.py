"""随机基线：每辆在仓库车随机排列候选任务，再装一批。

仅作对比基线（量化指标的下界参考）。线上不要用。
"""

from __future__ import annotations

import random
from typing import List

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.snapshot import Snapshot


class RandomBaselineScheduler(Scheduler):
    name = "random_baseline"

    def __init__(self, seed: int | None = None):
        self._rng = random.Random(seed) if seed is not None else random.Random()

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        commands: List[Command] = []

        for v in snapshot.idle_vehicles_not_at_warehouse():
            commands.append(utils.decide_en_route(v, snapshot))

        claimed = set()

        def pick_random(vehicle, tasks, snap):
            unclaimed = [t for t in tasks if t.id not in claimed]
            unclaimed = utils.feasible_tasks_for(vehicle, unclaimed)
            if not unclaimed:
                return []
            self._rng.shuffle(unclaimed)
            return utils.feasible_task_batch_for(vehicle, unclaimed)

        for v in snapshot.idle_vehicles_at_warehouse():
            cmd = utils.decide_at_warehouse(v, snapshot, pick_random)
            if cmd.action == "deliver":
                claimed.update(cmd.assigned_tasks)
            commands.append(cmd)

        return commands
