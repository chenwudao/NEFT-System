"""优先级优先：先服务高优先级任务，同优先级按距离近优先。"""

from __future__ import annotations

from typing import List

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.snapshot import Snapshot


class PriorityTaskScheduler(Scheduler):
    name = "priority_task"

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        commands: List[Command] = []

        for v in snapshot.idle_vehicles_not_at_warehouse():
            commands.append(utils.decide_en_route(v, snapshot))

        claimed = set()

        def pick_one(vehicle, tasks, snap):
            unclaimed = [t for t in tasks if t.id not in claimed]
            if not unclaimed:
                return []
            # 关键：优先级高在前；打平按距离近
            unclaimed.sort(
                key=lambda t: (
                    -t.priority,
                    snap.distance(vehicle.position, t.position),
                )
            )
            return [unclaimed[0]]

        for v in snapshot.idle_vehicles_at_warehouse():
            cmd = utils.decide_at_warehouse(v, snapshot, pick_one)
            if cmd.action == "deliver":
                claimed.update(cmd.assigned_tasks)
            commands.append(cmd)

        return commands
