"""最小生成树批量派单：展示"一次接一批任务、用 MST 规划访问顺序"的思路。

* 在仓库：把"按载重能装下的一批任务"一次性接走，用 MST + DFS 决定访问顺序，
  下一步 target 就是顺序中的第一个点。
* 在外面：按 MST 顺序跳到下一个未送点，送完回仓库。
"""

from __future__ import annotations

from typing import List

from backend.algorithm import utils
from backend.algorithm.scheduler import (
    ACTION_DELIVER,
    ACTION_RETURN,
    Command,
    Scheduler,
)
from backend.algorithm.snapshot import Snapshot
from backend.algorithm.utils import (
    feasible_tasks_for,
    make_charge_command,
    make_deliver_command,
    make_idle_command,
    make_return_command,
    mst_order,
    needs_charge,
    nearest_station,
)


class MstBatchScheduler(Scheduler):
    name = "mst_batch"

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        commands: List[Command] = []

        # 在外面：跟着车上的任务用 MST 顺序跑
        for v in snapshot.idle_vehicles_not_at_warehouse():
            if needs_charge(v):
                station = nearest_station(v, snapshot.charging_stations, snapshot)
                if station is not None:
                    commands.append(make_charge_command(v, station))
                    continue

            undelivered = snapshot.vehicle_undelivered_tasks(v)
            if not undelivered:
                commands.append(make_return_command(v, snapshot))
                continue

            start = (v.position.x, v.position.y)
            pts = [(t.position.x, t.position.y) for t in undelivered]
            order = mst_order(start, pts, snapshot)
            if not order:
                commands.append(make_return_command(v, snapshot))
                continue

            first_xy = order[0]
            first_task = next(
                t for t in undelivered
                if (t.position.x, t.position.y) == first_xy
            )
            commands.append(make_deliver_command(v, first_task))

        # 在仓库：批量抢货
        claimed = set()

        for v in snapshot.idle_vehicles_at_warehouse():
            if needs_charge(v):
                station = nearest_station(v, snapshot.charging_stations, snapshot)
                if station is not None:
                    commands.append(make_charge_command(v, station))
                    continue

            available = [
                t for t in snapshot.available_tasks() if t.id not in claimed
            ]
            picked = feasible_tasks_for(v, available)
            if not picked:
                commands.append(make_idle_command(v))
                continue

            # 按重量降序贪心装到装不下为止
            picked.sort(key=lambda t: -t.weight)
            batch = []
            capacity = v.get_remaining_load()
            for t in picked:
                if t.weight <= capacity:
                    batch.append(t)
                    capacity -= t.weight

            if not batch:
                commands.append(make_idle_command(v))
                continue

            claimed.update(t.id for t in batch)

            start = (v.position.x, v.position.y)
            pts = [(t.position.x, t.position.y) for t in batch]
            order = mst_order(start, pts, snapshot)
            id_by_xy = {(t.position.x, t.position.y): t for t in batch}
            first_task = id_by_xy[order[0]]

            commands.append(
                make_deliver_command(
                    v, first_task, assigned_tasks=[t.id for t in batch]
                )
            )

        return commands
