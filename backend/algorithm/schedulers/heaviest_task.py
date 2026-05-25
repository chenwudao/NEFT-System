"""最大载重优先：按重量从大到小装一批任务。

适用场景：货物有显著的重量差异，希望"先把大件清掉"，提升每次出车的载重利用率。
"""

from __future__ import annotations

from typing import List

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.snapshot import Snapshot


class HeaviestTaskScheduler(Scheduler):
    name = "heaviest_task"

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        commands: List[Command] = []

        for v in snapshot.idle_vehicles_not_at_warehouse():
            commands.append(utils.decide_en_route(v, snapshot))

        claimed = set()

        def pick_heaviest(vehicle, tasks, snap):
            unclaimed = [t for t in tasks if t.id not in claimed]
            unclaimed = utils.feasible_tasks_for(vehicle, unclaimed)
            if not unclaimed:
                return []
            unclaimed.sort(
                key=lambda t: (
                    -t.weight,
                    snap.distance(vehicle.position, t.position),
                )
            )
            return utils.feasible_task_batch_for(vehicle, unclaimed)

        for v in snapshot.idle_vehicles_at_warehouse():
            cmd = utils.decide_at_warehouse(v, snapshot, pick_heaviest)
            if cmd.action == "deliver":
                claimed.update(cmd.assigned_tasks)
            commands.append(cmd)

        return commands
