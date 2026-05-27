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

            start_xy = (vehicle.position.x, vehicle.position.y)
            unclaimed.sort(key=lambda t: snap.distance(vehicle.position, t.position))

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
            # nearest_task 特化：
            # 在仓库阶段仅在“低电阈值”时充电，避免开局出现
            # “仓库 -> 充电站 -> 仓库”的主动空转。
            if utils.needs_charge(v):
                station = utils.best_charging_station(v, snapshot)
                if station is not None:
                    commands.append(utils.make_charge_command(v, station))
                else:
                    commands.append(utils.make_idle_command(v))
                continue

            picked = pick_batch(v, available, snapshot)
            if not picked:
                commands.append(utils.make_idle_command(v))
                continue

            picked = utils.feasible_task_batch_for(v, picked)
            if not picked:
                commands.append(utils.make_idle_command(v))
                continue

            ordered = utils.greedy_chain(
                (v.position.x, v.position.y),
                [(t.position.x, t.position.y) for t in picked],
                snapshot,
            )
            if not ordered:
                commands.append(utils.make_idle_command(v))
                continue

            id_by_xy = {(t.position.x, t.position.y): t for t in picked}
            first_task = id_by_xy.get(ordered[0])
            if first_task is None:
                commands.append(utils.make_idle_command(v))
                continue

            cmd = utils.make_deliver_command(
                v,
                first_task,
                assigned_tasks=[t.id for t in picked],
            )
            claimed.update(cmd.assigned_tasks)
            commands.append(cmd)

        return commands
