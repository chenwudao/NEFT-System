"""优先级优先：先服务高优先级任务，同优先级按距离近优先，一趟可带多单。"""

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

        def pick_batch(vehicle, tasks, snap):
            unclaimed = [t for t in tasks if t.id not in claimed]
            unclaimed = utils.feasible_tasks_for(vehicle, unclaimed)
            if not unclaimed:
                return []

            start_xy = (vehicle.position.x, vehicle.position.y)
            unclaimed.sort(
                key=lambda t: (
                    -float(t.priority),
                    snap.distance(vehicle.position, t.position),
                )
            )

            chosen = []
            for t in unclaimed:
                cand = chosen + [t]
                ordered = utils.greedy_chain(
                    start_xy,
                    [(x.position.x, x.position.y) for x in cand],
                    snap,
                )
                if not ordered:
                    break
                dist = utils.estimate_chain_distance_with_recharge(
                    vehicle,
                    ordered,
                    snap,
                    require_final_station_buffer=True,
                )
                if dist == float("inf"):
                    break
                chosen = cand
            return chosen

        for v in snapshot.idle_vehicles_at_warehouse():
            cmd = utils.decide_at_warehouse(v, snapshot, pick_batch)
            if cmd.action == "deliver":
                claimed.update(cmd.assigned_tasks)
            commands.append(cmd)

        return commands
