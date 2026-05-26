"""贪心插入启发式（进阶版）。

流程：
1) 维护一条当前路径 route（start -> ... -> tail）；
2) 对每个候选任务计算“最佳插入位置”和“次优插入位置”；
3) 用 regret-2（次优 - 最优）优先插入“错过代价大”的任务；
4) 每次插入后做一次轻量 2-opt 本地优化；
5) 全程受载重 + 充电可达性约束。
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

            # 当前 route：起点 -> ... -> 末端。这里不强制回仓，由充电可达性兜底。
            route: List[Tuple[float, float]] = [start_xy]
            chosen = []
            remaining_load = vehicle.get_remaining_load()
            remaining = list(available)

            def chain_length(rt):
                if len(rt) <= 1:
                    return 0.0
                d = 0.0
                for i in range(len(rt) - 1):
                    seg = snap.distance(rt[i], rt[i + 1])
                    if seg == float("inf"):
                        return float("inf")
                    d += seg
                return d

            def route_feasible(rt: List[Tuple[float, float]]) -> bool:
                return (
                    utils.estimate_chain_distance_with_recharge(
                        vehicle, rt[1:], snap, require_final_station_buffer=True
                    )
                    != float("inf")
                )

            def two_opt_local(rt: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
                """对 route 做一次轻量 2-opt。"""
                if len(rt) <= 4:
                    return rt
                best = list(rt)
                best_len = chain_length(best)
                n = len(rt)
                for i in range(1, n - 2):
                    for j in range(i + 1, n - 1):
                        cand = best[:i] + list(reversed(best[i : j + 1])) + best[j + 1 :]
                        clen = chain_length(cand)
                        if clen + 1e-9 < best_len and route_feasible(cand):
                            best, best_len = cand, clen
                return best

            while remaining:
                selected_task = None
                selected_pos = None
                selected_regret = float("-inf")
                selected_best_delta = float("inf")
                for t in remaining:
                    if t.weight > remaining_load:
                        continue
                    t_xy = (t.position.x, t.position.y)

                    best_ins_len = float("inf")
                    second_ins_len = float("inf")
                    best_pos_for_t = None

                    # 可插入位置：route[1:] 之间 + 末尾追加
                    for pos in range(1, len(route) + 1):
                        cand = list(route)
                        cand.insert(pos, t_xy)
                        if not route_feasible(cand):
                            continue
                        clen = chain_length(cand)
                        if clen < best_ins_len:
                            second_ins_len = best_ins_len
                            best_ins_len = clen
                            best_pos_for_t = pos
                        elif clen < second_ins_len:
                            second_ins_len = clen

                    if best_pos_for_t is None:
                        continue

                    regret = (
                        (second_ins_len - best_ins_len)
                        if second_ins_len < float("inf")
                        else 1e6
                    )
                    if (
                        regret > selected_regret
                        or (
                            abs(regret - selected_regret) <= 1e-9
                            and best_ins_len < selected_best_delta
                        )
                    ):
                        selected_regret = regret
                        selected_best_delta = best_ins_len
                        selected_task = t
                        selected_pos = best_pos_for_t

                if selected_task is None or selected_pos is None:
                    break

                # 插入 + 局部 2-opt 优化
                candidate_route = list(route)
                candidate_route.insert(selected_pos, (selected_task.position.x, selected_task.position.y))
                candidate_route = two_opt_local(candidate_route)
                if not route_feasible(candidate_route):
                    remaining.remove(selected_task)
                    continue

                route = candidate_route
                chosen.append(selected_task)
                remaining_load -= selected_task.weight
                remaining.remove(selected_task)

            if not chosen:
                return []

            # 按 route 内出现顺序回传（不含 start_xy）
            id_by_xy = {(t.position.x, t.position.y): t for t in chosen}
            ordered = []
            for xy in route[1:]:
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
