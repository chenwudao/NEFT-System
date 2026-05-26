"""DFS 评分搜索策略（元启发式 + 精确枚举）。

仓库内针对每辆车做 DFS 子集搜索：
1) 仅按载重剪枝枚举任务子集；
2) 对每个子集按 greedy_chain 排序并评估可行性；
3) 目标函数：任务总收益 - 路程惩罚；
4) 取目标值最高的可行集合。
"""

from __future__ import annotations

import time
from typing import Dict, List, Set, Tuple

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.scoring_config import calculate_assignment_score
from backend.algorithm.snapshot import Snapshot


class DfsScoreSearchScheduler(Scheduler):
    name = "dfs_score_search"

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        commands: List[Command] = []

        for v in snapshot.idle_vehicles_not_at_warehouse():
            commands.append(utils.decide_en_route(v, snapshot))

        claimed = set()
        now_ts = int(snapshot.timestamp or time.time())

        def pick_batch(vehicle, tasks, snap):
            unclaimed = [t for t in tasks if t.id not in claimed]
            unclaimed = utils.feasible_tasks_for(vehicle, unclaimed)
            if not unclaimed:
                return []

            start_xy = (vehicle.position.x, vehicle.position.y)
            by_id = {t.id: t for t in unclaimed}
            ids = list(by_id.keys())
            cap = max(0.0, float(vehicle.get_remaining_load()))
            scale_dist = 12000.0

            eval_cache: Dict[Tuple[int, ...], Tuple[bool, List, float]] = {}

            def eval_state(state: Set[int]) -> Tuple[bool, List, float]:
                key = tuple(sorted(state))
                cached = eval_cache.get(key)
                if cached is not None:
                    return cached

                if not key:
                    out = (True, [], 0.0)
                    eval_cache[key] = out
                    return out

                selected = [by_id[i] for i in key]
                if sum(float(t.weight) for t in selected) > cap + 1e-9:
                    out = (False, [], float("-inf"))
                    eval_cache[key] = out
                    return out

                ordered_xy = utils.greedy_chain(
                    start_xy, [(t.position.x, t.position.y) for t in selected], snap
                )
                if not ordered_xy:
                    out = (False, [], float("-inf"))
                    eval_cache[key] = out
                    return out

                id_by_xy = {(t.position.x, t.position.y): t for t in selected}
                ordered = [id_by_xy[xy] for xy in ordered_xy if xy in id_by_xy]
                waypoints = [(t.position.x, t.position.y) for t in ordered]
                dist = utils.estimate_chain_distance_with_recharge(
                    vehicle, waypoints, snap, require_final_station_buffer=True
                )
                if dist == float("inf"):
                    out = (False, ordered, float("-inf"))
                    eval_cache[key] = out
                    return out

                # 任务收益：用 assignment score 的单段近似累计
                reward = 0.0
                cur = start_xy
                for t in ordered:
                    seg = snap.distance(cur, t.position)
                    if seg == float("inf"):
                        out = (False, ordered, float("-inf"))
                        eval_cache[key] = out
                        return out
                    reward += calculate_assignment_score(t, vehicle, seg, now_ts)
                    cur = (t.position.x, t.position.y)

                objective = reward - (dist / scale_dist)
                out = (True, ordered, objective)
                eval_cache[key] = out
                return out

            best_state: Set[int] = set()
            best_obj = float("-inf")

            def dfs(idx: int, state: Set[int], cur_w: float) -> None:
                nonlocal best_state, best_obj
                if idx >= len(ids):
                    if not state:
                        return
                    ok, _ord, obj = eval_state(state)
                    if ok and obj > best_obj:
                        best_obj = obj
                        best_state = set(state)
                    return

                tid = ids[idx]
                t = by_id[tid]
                # 不选
                dfs(idx + 1, state, cur_w)
                # 选（载重剪枝）
                nw = cur_w + float(t.weight)
                if nw <= cap + 1e-9:
                    state.add(tid)
                    dfs(idx + 1, state, nw)
                    state.remove(tid)

            dfs(0, set(), 0.0)
            ok, ordered, _obj = eval_state(best_state)
            return ordered if ok else []

        for v in snapshot.idle_vehicles_at_warehouse():
            cmd = utils.decide_at_warehouse(v, snapshot, pick_batch)
            if cmd.action == "deliver":
                claimed.update(cmd.assigned_tasks)
            commands.append(cmd)

        return commands

