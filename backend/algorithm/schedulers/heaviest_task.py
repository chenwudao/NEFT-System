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

            start_xy = (vehicle.position.x, vehicle.position.y)
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
            cmd = utils.decide_at_warehouse(v, snapshot, pick_heaviest)
            if cmd.assigned_tasks:
                claimed.update(cmd.assigned_tasks)
            commands.append(cmd)

        return commands
