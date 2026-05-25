"""贪心插入启发式（Insertion Heuristic）：批量在仓库时，迭代往车辆"路径"中
插入边际成本最小（或综合得分最优）的任务，直到再插入会违约束为止。

特点：
- 同时考虑路径距离与时效，目标：最小化 batch 内"额外里程 - 任务收益"
- 单批任务数量不设上限，仅受 vehicle.max_load 限制
- 没货可接时回退为 idle / 充电

适合"一次出车送多单"且任务点比较密集时显著优于纯 nearest_task。
"""

from __future__ import annotations

from typing import List, Tuple

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.snapshot import Snapshot


class InsertionHeuristicScheduler(Scheduler):
    name = "insertion_heuristic"

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        commands: List[Command] = []

        for v in snapshot.idle_vehicles_not_at_warehouse():
            commands.append(utils.decide_en_route(v, snapshot))

        claimed = set()

        def pick_batch(vehicle, tasks, snap):
            available = [t for t in tasks if t.id not in claimed]
            available = utils.feasible_tasks_for(vehicle, available)
            if not available:
                return []

            start_xy: Tuple[float, float] = (vehicle.position.x, vehicle.position.y)
            wh_xy = snap.warehouse_xy

            # 当前 route：起点 -> ... -> 仓库。初始仅含 start -> warehouse。
            route: List[Tuple[float, float]] = [start_xy, wh_xy]
            chosen = []
            remaining_load = vehicle.get_remaining_load()
            remaining = list(available)

            def chain_length(rt):
                d = 0.0
                for i in range(len(rt) - 1):
                    seg = snap.distance(rt[i], rt[i + 1])
                    if seg == float("inf"):
                        return float("inf")
                    d += seg
                return d

            cur_len = chain_length(route)

            while remaining:
                best_task = None
                best_pos = None
                best_score = float("-inf")
                best_new_len = None

                for t in remaining:
                    if t.weight > remaining_load:
                        continue
                    t_xy = (t.position.x, t.position.y)
                    # 在 route 的每个"边"上尝试插入 t_xy（除最后一个位置）
                    for pos in range(1, len(route)):
                        prev = route[pos - 1]
                        nxt = route[pos]
                        d_prev_t = snap.distance(prev, t_xy)
                        d_t_nxt = snap.distance(t_xy, nxt)
                        d_prev_nxt = snap.distance(prev, nxt)
                        if (d_prev_t == float("inf") or d_t_nxt == float("inf")
                                or d_prev_nxt == float("inf")):
                            continue
                        delta = d_prev_t + d_t_nxt - d_prev_nxt
                        # 得分：高优先级、低边际增量 → 高分
                        bonus = float(t.priority) * 500.0
                        score = bonus - delta * 0.5
                        if score > best_score:
                            best_score = score
                            best_task = t
                            best_pos = pos
                            best_new_len = cur_len + delta

                if best_task is None or best_pos is None:
                    break

                # 把候选 task 插入 route 并做电量预判
                candidate_route = list(route)
                candidate_route.insert(best_pos, (best_task.position.x, best_task.position.y))
                # waypoints 不含 vehicle.position 自身
                if not utils.can_complete_chain(
                    vehicle, candidate_route[1:], snap, require_station_buffer=False
                ):
                    # 装下这个就回不去了 → 跳过
                    remaining.remove(best_task)
                    continue

                route = candidate_route
                cur_len = best_new_len if best_new_len is not None else chain_length(route)
                chosen.append(best_task)
                remaining_load -= best_task.weight
                remaining.remove(best_task)

            if not chosen:
                return []

            # 按 route 内出现顺序回传（不含 start_xy 和 wh_xy）
            id_by_xy = {(t.position.x, t.position.y): t for t in chosen}
            ordered = []
            for xy in route[1:-1]:
                t = id_by_xy.get(xy)
                if t is not None:
                    ordered.append(t)
            return ordered

        for v in snapshot.idle_vehicles_at_warehouse():
            cmd = utils.decide_at_warehouse(v, snapshot, pick_batch)
            if cmd.action == "deliver":
                claimed.update(cmd.assigned_tasks)
            commands.append(cmd)

        return commands
