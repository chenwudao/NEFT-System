"""最近任务优先：最简单的贪心策略。

* 在仓库：按“离当前点最近”贪心串成一批任务，装得下就一趟带走
* 在外面：车上还有没送的货 → 去最近的那个；否则回仓库

这是所有更复杂算法的"对照基线"。
"""

from __future__ import annotations

from typing import List

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.snapshot import Snapshot


class NearestTaskScheduler(Scheduler):
    name = "nearest_task"

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        commands: List[Command] = []

        # 1) 已经在路上、刚到某个任务点的车
        for v in snapshot.idle_vehicles_not_at_warehouse():
            commands.append(utils.decide_en_route(v, snapshot))

        # 2) 停在仓库、待命接新任务的车
        #    每轮最多把 pending 任务"抢"光：这里保证多辆车不会抢到同一个任务。
        claimed = set()
        available = list(snapshot.available_tasks())

        def pick_batch(vehicle, tasks, snap):
            unclaimed = [t for t in tasks if t.id not in claimed]
            unclaimed = utils.feasible_tasks_for(vehicle, unclaimed)
            if not unclaimed:
                return []

            ordered = []
            cur = (vehicle.position.x, vehicle.position.y)
            remaining = list(unclaimed)
            while remaining:
                nxt = min(remaining, key=lambda t: snap.distance(cur, t.position))
                ordered.append(nxt)
                remaining.remove(nxt)
                cur = (nxt.position.x, nxt.position.y)
            return utils.feasible_task_batch_for(vehicle, ordered)

        for v in snapshot.idle_vehicles_at_warehouse():
            cmd = utils.decide_at_warehouse(v, snapshot, pick_batch)
            if cmd.action == "deliver":
                claimed.update(cmd.assigned_tasks)
            commands.append(cmd)

        return commands
