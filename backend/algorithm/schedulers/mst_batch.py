"""最小生成树批量派单：展示"一次接一批任务、用 MST 规划访问顺序"的思路。

* 在仓库：把"按载重能装下的一批任务"一次性接走，用 MST + DFS 决定访问顺序，
  下一步 target 就是顺序中的第一个点。
* 在外面：按 MST 顺序跳到下一个未送点，送完回仓库。

充电逻辑：统一走 utils 里的 decide_en_route + 自定义 pick_tasks 模板，
保证"电量不够跑完整条 chain"时优先去充电站。
"""

from __future__ import annotations

from typing import List

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.snapshot import Snapshot
from backend.algorithm.utils import (
    best_charging_station,
    can_complete_chain,
    decide_en_route,
    feasible_tasks_for,
    make_charge_command,
    make_deliver_command,
    make_idle_command,
    mst_order,
    needs_charge,
)
from backend.config import config


class MstBatchScheduler(Scheduler):
    name = "mst_batch"

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        commands: List[Command] = []

        # 在外面：复用模板（含充电预判 + MST 重排）
        for v in snapshot.idle_vehicles_not_at_warehouse():
            # 路上若有未送的任务，用 MST 顺序代替"最近一个"作为下一站
            undelivered = snapshot.vehicle_undelivered_tasks(v)
            if not undelivered:
                commands.append(decide_en_route(v, snapshot))
                continue

            if needs_charge(v):
                station = best_charging_station(v, snapshot)
                if station is not None:
                    commands.append(make_charge_command(v, station))
                    continue

            start = (v.position.x, v.position.y)
            pts = [(t.position.x, t.position.y) for t in undelivered]
            order = mst_order(start, pts, snapshot)
            if not order:
                commands.append(decide_en_route(v, snapshot))
                continue

            # 电量预判：能否跑完 chain + 回仓
            chain = list(order) + [snapshot.warehouse_xy]
            if not can_complete_chain(v, chain, snapshot, require_station_buffer=False):
                station = best_charging_station(v, snapshot)
                if station is not None:
                    commands.append(make_charge_command(v, station))
                    continue

            first_xy = order[0]
            first_task = next(
                t for t in undelivered
                if (t.position.x, t.position.y) == first_xy
            )
            commands.append(make_deliver_command(v, first_task))

        # 在仓库：批量抢货（按重量贪心装载）
        claimed = set()

        def pick_batch(vehicle, tasks, snap):
            available = [t for t in tasks if t.id not in claimed]
            available = feasible_tasks_for(vehicle, available)
            if not available:
                return []
            # 按重量降序，能装就装
            available.sort(key=lambda t: -t.weight)
            batch: list = []
            capacity = vehicle.get_remaining_load()
            for t in available:
                if t.weight <= capacity:
                    batch.append(t)
                    capacity -= t.weight
            return batch

        for v in snapshot.idle_vehicles_at_warehouse():
            cmd = utils.decide_at_warehouse(v, snapshot, pick_batch)
            if cmd.action == "deliver":
                claimed.update(cmd.assigned_tasks)
            commands.append(cmd)

        return commands
