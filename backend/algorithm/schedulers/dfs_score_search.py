"""DFS 得分搜索装批：枚举所有最大可行装货方案，取得分最高者。

最大可行解定义：
    1) 载重可行，且任务链电量可行（直达或 90% 过渡充电）；
    2) 在当前待选任务池中，已装货物之后无法再装入任何其他单个任务。

目标函数：
    对每个最大可行解，按 greedy_chain 排序后，用 scoring_config.calculate_batch_chain_score
    估算累计得分（与最终任务得分公式一致：分配奖励、优先级、距离、提前/逾期）。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.scoring_config import calculate_batch_chain_score
from backend.algorithm.snapshot import Snapshot
from backend.data.task import Task
from backend.data.vehicle import Vehicle


def _evaluate_batch(
    vehicle: Vehicle,
    tasks: List[Task],
    snapshot: Snapshot,
    now_ts: int,
) -> Tuple[Optional[float], Optional[List[Task]], Optional[float]]:
    """评估一批任务：返回 (chain_dist, ordered_tasks, total_score) 或 (None, None, None)。"""
    if not tasks:
        return None, None, None

    ordered = _ordered_tasks(vehicle, tasks, snapshot)
    if not ordered:
        return None, None, None

    ordered_xy = [(t.position.x, t.position.y) for t in ordered]
    dist = utils.estimate_chain_distance_with_recharge(
        vehicle,
        ordered_xy,
        snapshot,
        require_final_station_buffer=True,
    )
    if dist == float("inf"):
        return None, None, None

    score = calculate_batch_chain_score(ordered, vehicle, snapshot, now_ts)
    if score == float("-inf"):
        return None, None, None

    return float(dist), ordered, float(score)


def _ordered_tasks(
    vehicle: Vehicle,
    tasks: List[Task],
    snapshot: Snapshot,
) -> Optional[List[Task]]:
    if not tasks:
        return None
    start_xy = (vehicle.position.x, vehicle.position.y)
    ordered_xy = utils.greedy_chain(
        start_xy,
        [(t.position.x, t.position.y) for t in tasks],
        snapshot,
    )
    if not ordered_xy:
        return None
    id_by_xy = {(t.position.x, t.position.y): t for t in tasks}
    ordered = [id_by_xy[xy] for xy in ordered_xy if xy in id_by_xy]
    if len(ordered) != len(tasks):
        return None
    return ordered


def _is_maximal_feasible_batch(
    vehicle: Vehicle,
    batch_ids: Set[int],
    by_id: Dict[int, Task],
    pool: List[Task],
    snapshot: Snapshot,
    eval_cache: Dict[frozenset, Tuple[Optional[float], Optional[List[Task]], Optional[float]]],
    now_ts: int,
) -> bool:
    if not batch_ids:
        return False

    key = frozenset(batch_ids)
    if key not in eval_cache:
        selected = [by_id[i] for i in key]
        eval_cache[key] = _evaluate_batch(vehicle, selected, snapshot, now_ts)
    if eval_cache[key][0] is None:
        return False

    cap = float(vehicle.get_remaining_load())
    used = sum(float(by_id[i].weight) for i in batch_ids)
    for task in pool:
        if task.id in batch_ids:
            continue
        if float(task.weight) > cap - used + 1e-9:
            continue
        ext_key = frozenset(batch_ids | {task.id})
        if ext_key not in eval_cache:
            ext_selected = [by_id[i] for i in ext_key]
            eval_cache[ext_key] = _evaluate_batch(
                vehicle, ext_selected, snapshot, now_ts
            )
        if eval_cache[ext_key][0] is not None:
            return False
    return True


def find_best_maximal_batch_dfs(
    vehicle: Vehicle,
    tasks: List[Task],
    snapshot: Snapshot,
) -> List[Task]:
    """DFS 枚举最大可行装批，返回得分最高的任务列表（greedy_chain 顺序）。"""
    pool = utils.feasible_tasks_for(vehicle, tasks)
    if not pool:
        return []

    by_id = {t.id: t for t in pool}
    ids = sorted(by_id.keys())
    cap = float(vehicle.get_remaining_load())
    now_ts = int(snapshot.timestamp or 0)
    eval_cache: Dict[
        frozenset, Tuple[Optional[float], Optional[List[Task]], Optional[float]]
    ] = {}

    best_ids: Set[int] = set()
    best_score = float("-inf")
    best_dist = float("inf")

    def consider(state: Set[int]) -> None:
        nonlocal best_ids, best_score, best_dist
        if not _is_maximal_feasible_batch(
            vehicle, state, by_id, pool, snapshot, eval_cache, now_ts
        ):
            return
        key = frozenset(state)
        dist, ordered, score = eval_cache[key]
        if dist is None or ordered is None or score is None:
            return
        if score > best_score + 1e-9 or (
            abs(score - best_score) <= 1e-9 and (
                len(state) > len(best_ids)
                or (len(state) == len(best_ids) and dist < best_dist)
            )
        ):
            best_score = score
            best_dist = dist
            best_ids = set(state)

    def dfs(idx: int, state: Set[int], cur_weight: float) -> None:
        if idx >= len(ids):
            consider(state)
            return

        tid = ids[idx]
        task = by_id[tid]

        dfs(idx + 1, state, cur_weight)

        next_weight = cur_weight + float(task.weight)
        if next_weight <= cap + 1e-9:
            state.add(tid)
            consider(state)
            dfs(idx + 1, state, next_weight)
            state.remove(tid)

    dfs(0, set(), 0.0)
    if not best_ids:
        return []
    key = frozenset(best_ids)
    _, ordered, _ = eval_cache.get(key, (None, None, None))
    return list(ordered) if ordered else []


class DfsScoreSearchScheduler(Scheduler):
    name = "dfs_score_search"

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        commands: List[Command] = []

        for v in snapshot.idle_vehicles_not_at_warehouse():
            commands.append(utils.decide_en_route(v, snapshot))

        claimed = set()

        def pick_batch(vehicle, tasks, snap):
            unclaimed = [t for t in tasks if t.id not in claimed]
            return find_best_maximal_batch_dfs(vehicle, unclaimed, snap)

        for v in snapshot.idle_vehicles_at_warehouse():
            cmd = utils.decide_at_warehouse(v, snapshot, pick_batch)
            if cmd.assigned_tasks:
                claimed.update(cmd.assigned_tasks)
            commands.append(cmd)

        return commands
