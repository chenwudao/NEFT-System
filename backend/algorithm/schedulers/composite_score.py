"""复合评分策略（规划版）。

核心思路：
1) 对候选任务先按单点评分排序，截断为 top-k；
2) 在 top-k 上做 DFS + beam-search，搜索一批可行任务集合；
3) 目标：最大化“任务总评分 - 路程惩罚”；
4) 输出最优集合后再用 greedy_chain 得到访问顺序。
"""

from __future__ import annotations

import time
from typing import Dict, List, Set, Tuple

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.snapshot import Snapshot
from backend.config import config


def _composite_weights() -> Dict[str, float]:
    """读 SCHEDULING_CONFIG.composite_weights；不存在时给默认值。"""
    sched_cfg = config.get_scheduling_config()
    base = {
        "priority":       1.0,
        "urgency":        1.5,
        "load":           0.3,
        "distance":       1.0,
        "scale_distance": 10000.0,   # 10km 作为距离归一化基准
        "urgency_window": 7200.0,    # 2h
    }
    overrides = sched_cfg.get("composite_weights") or {}
    base.update({k: float(v) for k, v in overrides.items() if v is not None})
    return base


class CompositeScoreScheduler(Scheduler):
    name = "composite_score"

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        commands: List[Command] = []

        for v in snapshot.idle_vehicles_not_at_warehouse():
            commands.append(utils.decide_en_route(v, snapshot))

        claimed = set()
        weights = _composite_weights()
        now = float(snapshot.timestamp or time.time())

        task_cfg = config.get_task_config()
        max_priority = max(1, int(task_cfg.get("max_priority", 5)))

        def pick_best(vehicle, tasks, snap):
            unclaimed = [t for t in tasks if t.id not in claimed]
            unclaimed = utils.feasible_tasks_for(vehicle, unclaimed)
            if not unclaimed:
                return []

            start_xy = (vehicle.position.x, vehicle.position.y)
            scale_dist = weights["scale_distance"] or 1.0
            urgency_window = weights["urgency_window"] or 1.0
            max_load = max(1.0, float(vehicle.max_load))

            def score(t):
                d = snap.distance(vehicle.position, t.position)
                if d == float("inf"):
                    return -float("inf")
                remaining = max(0.0, float(t.deadline) - now)
                urgency = max(0.0, 1.0 - remaining / urgency_window)
                return (
                    weights["priority"] * (float(t.priority) / max_priority)
                    + weights["urgency"] * urgency
                    + weights["load"] * (float(t.weight) / max_load)
                    - weights["distance"] * (d / scale_dist)
                )

            # top-k 截断，避免 DFS 在大规模任务下爆炸
            ranked = sorted(
                unclaimed,
                key=lambda t: (-score(t), snap.distance(vehicle.position, t.position)),
            )
            top_k = int(config.get_scheduling_config().get("composite_top_k", 14))
            ranked = ranked[: max(4, top_k)]
            by_id = {t.id: t for t in ranked}

            eval_cache: Dict[Tuple[int, ...], Tuple[bool, List, float, float]] = {}

            def eval_state(state: Set[int]) -> Tuple[bool, List, float, float]:
                """返回(可行, 有序任务, 总目标值, 距离惩罚项)。"""
                key = tuple(sorted(state))
                cached = eval_cache.get(key)
                if cached is not None:
                    return cached
                if not key:
                    out = (True, [], 0.0, 0.0)
                    eval_cache[key] = out
                    return out

                picked = [by_id[i] for i in key]
                if sum(float(t.weight) for t in picked) > vehicle.get_remaining_load() + 1e-9:
                    out = (False, [], float("-inf"), float("inf"))
                    eval_cache[key] = out
                    return out

                ordered_xy = utils.greedy_chain(
                    start_xy, [(t.position.x, t.position.y) for t in picked], snap
                )
                if not ordered_xy:
                    out = (False, [], float("-inf"), float("inf"))
                    eval_cache[key] = out
                    return out
                id_by_xy = {(t.position.x, t.position.y): t for t in picked}
                ordered = [id_by_xy[xy] for xy in ordered_xy if xy in id_by_xy]
                waypoints = [(t.position.x, t.position.y) for t in ordered]

                dist = utils.estimate_chain_distance_with_recharge(
                    vehicle, waypoints, snap, require_final_station_buffer=True
                )
                if dist == float("inf"):
                    out = (False, ordered, float("-inf"), float("inf"))
                    eval_cache[key] = out
                    return out

                reward = sum(score(t) for t in ordered)
                dist_penalty = weights["distance"] * (dist / scale_dist)
                objective = reward - dist_penalty
                out = (True, ordered, objective, dist_penalty)
                eval_cache[key] = out
                return out

            # Beam DFS：每层保留前 beam_width 个状态
            beam_width = int(config.get_scheduling_config().get("composite_beam_width", 24))
            beam: List[Set[int]] = [set()]
            ids = [t.id for t in ranked]
            best_state: Set[int] = set()
            best_obj = float("-inf")

            for tid in ids:
                cand_states: List[Set[int]] = []
                for st in beam:
                    # 不选
                    cand_states.append(set(st))
                    # 选
                    st2 = set(st)
                    st2.add(tid)
                    ok, _ord, obj, _dp = eval_state(st2)
                    if ok:
                        cand_states.append(st2)
                        if obj > best_obj:
                            best_obj = obj
                            best_state = st2

                # 去重后按目标值排序取前 beam_width
                uniq: Dict[Tuple[int, ...], Set[int]] = {}
                for st in cand_states:
                    uniq[tuple(sorted(st))] = st
                scored = []
                for st in uniq.values():
                    ok, _ord, obj, _dp = eval_state(st)
                    if ok:
                        scored.append((obj, st))
                scored.sort(key=lambda x: x[0], reverse=True)
                beam = [st for _obj, st in scored[: max(4, beam_width)]]

            ok, ordered, _obj, _dp = eval_state(best_state)
            return ordered if ok else []

        for v in snapshot.idle_vehicles_at_warehouse():
            cmd = utils.decide_at_warehouse(v, snapshot, pick_best)
            if cmd.action == "deliver":
                claimed.update(cmd.assigned_tasks)
            commands.append(cmd)

        return commands
