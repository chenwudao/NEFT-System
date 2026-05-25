"""最早截止时间优先（EDF：Earliest Deadline First）。

每辆车在仓库时，按 deadline 从早到晚装一批任务；同 deadline 时按距离近优先。
属于"按时率优化型"策略。
"""

from __future__ import annotations

from typing import List

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.snapshot import Snapshot


class DeadlineEarliestScheduler(Scheduler):
    name = "deadline_earliest"

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        commands: List[Command] = []

        for v in snapshot.idle_vehicles_not_at_warehouse():
            commands.append(utils.decide_en_route(v, snapshot))

        claimed = set()

        def pick_edf(vehicle, tasks, snap):
            unclaimed = [t for t in tasks if t.id not in claimed]
            unclaimed = utils.feasible_tasks_for(vehicle, unclaimed)
            if not unclaimed:
                return []
            unclaimed.sort(
                key=lambda t: (
                    t.deadline,
                    snap.distance(vehicle.position, t.position),
                )
            )
            return utils.feasible_task_batch_for(vehicle, unclaimed)

        for v in snapshot.idle_vehicles_at_warehouse():
            cmd = utils.decide_at_warehouse(v, snapshot, pick_edf)
            if cmd.action == "deliver":
                claimed.update(cmd.assigned_tasks)
            commands.append(cmd)

        return commands
