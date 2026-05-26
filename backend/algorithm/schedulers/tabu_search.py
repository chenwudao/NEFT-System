"""元启发式方法：Tabu Search。

思路：
1) 在候选任务 top-k 上先构造一个可行初始序列；
2) 邻域操作采用“交换两个位置”；
3) 用 tabu 表阻止短期回退；
4) 目标函数：任务奖励 - 路程惩罚；
5) 输出当前找到的最优可行序列。
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.scoring_config import calculate_assignment_score
from backend.algorithm.snapshot import Snapshot
from backend.config import config


class TabuSearchScheduler(Scheduler):
    name = "tabu_search"

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        commands: List[Command] = []

        for v in snapshot.idle_vehicles_not_at_warehouse():
            commands.append(utils.decide_en_route(v, snapshot))

        claimed = set()
        now_ts = int(snapshot.timestamp or time.time())
        sched_cfg = config.get_scheduling_config()
        tabu_cfg = sched_cfg.get("tabu") or {}
        top_k = int(tabu_cfg.get("top_k", 10))
        iterations = int(tabu_cfg.get("iterations", 140))
        tabu_tenure = int(tabu_cfg.get("tenure", 20))

        def eval_sequence(vehicle, ordered: List, snap: Snapshot) -> float:
            if not ordered:
                return float("-inf")
            waypoints = [(t.position.x, t.position.y) for t in ordered]
            dist = utils.estimate_chain_distance_with_recharge(
                vehicle, waypoints, snap, require_final_station_buffer=True
            )
            if dist == float("inf"):
                return float("-inf")
            reward = 0.0
            cur = (vehicle.position.x, vehicle.position.y)
            for t in ordered:
                seg = snap.distance(cur, t.position)
                if seg == float("inf"):
                    return float("-inf")
                reward += calculate_assignment_score(t, vehicle, seg, now_ts)
                cur = (t.position.x, t.position.y)
            return reward - (dist / 12000.0)

        def pick_batch(vehicle, tasks, snap):
            unclaimed = [t for t in tasks if t.id not in claimed]
            unclaimed = utils.feasible_tasks_for(vehicle, unclaimed)
            if not unclaimed:
                return []

            # 候选池：先按 priority + 紧迫度 + 距离排序，截断 top-k
            ranked = sorted(
                unclaimed,
                key=lambda t: (
                    -float(t.priority),
                    float(t.deadline),
                    snap.distance(vehicle.position, t.position),
                ),
            )[: max(4, top_k)]

            # 初始解：增量加入，保持可行
            current = []
            remain = float(vehicle.get_remaining_load())
            for t in ranked:
                if float(t.weight) > remain + 1e-9:
                    continue
                cand = current + [t]
                if eval_sequence(vehicle, cand, snap) == float("-inf"):
                    continue
                current = cand
                remain -= float(t.weight)

            if not current:
                return []

            best = list(current)
            best_score = eval_sequence(vehicle, best, snap)

            # tabu(move) = expire_iteration
            tabu: Dict[Tuple[int, int], int] = {}

            for it in range(max(1, iterations)):
                n = len(current)
                best_neighbor: Optional[List] = None
                best_neighbor_score = float("-inf")
                best_move: Optional[Tuple[int, int]] = None

                for i in range(n):
                    for j in range(i + 1, n):
                        move = (current[i].id, current[j].id)
                        cand = list(current)
                        cand[i], cand[j] = cand[j], cand[i]
                        sc = eval_sequence(vehicle, cand, snap)
                        if sc == float("-inf"):
                            continue

                        is_tabu = tabu.get(move, -1) > it
                        # 特赦准则：若优于全局最优，即使 tabu 也允许
                        if is_tabu and sc <= best_score + 1e-9:
                            continue
                        if sc > best_neighbor_score:
                            best_neighbor_score = sc
                            best_neighbor = cand
                            best_move = move

                if best_neighbor is None:
                    break

                current = best_neighbor
                if best_move is not None:
                    tabu[best_move] = it + max(1, tabu_tenure)

                if best_neighbor_score > best_score:
                    best_score = best_neighbor_score
                    best = list(best_neighbor)

            return best

        for v in snapshot.idle_vehicles_at_warehouse():
            cmd = utils.decide_at_warehouse(v, snapshot, pick_batch)
            if cmd.action == "deliver":
                claimed.update(cmd.assigned_tasks)
            commands.append(cmd)

        return commands

