"""SA 得分搜索装批：在最大可行装批空间内用模拟退火寻找最高得分方案。

与 dfs_score_search 使用相同的最大可行装批定义与得分函数；用 SA 近似搜索，
在 pending 较多时比 DFS 更快，理论上可接近 DFS 最优结果。
"""

from __future__ import annotations

import math
import random
from typing import Dict, List, Optional, Set, Tuple

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.scoring_config import (
    calculate_assignment_score,
    calculate_batch_chain_score,
)
from backend.algorithm.snapshot import Snapshot
from backend.config import config
from backend.data.task import Task
from backend.data.vehicle import Vehicle


def _evaluate_batch(
    vehicle: Vehicle,
    tasks: List[Task],
    snapshot: Snapshot,
    now_ts: int,
) -> Tuple[Optional[float], Optional[List[Task]], Optional[float]]:
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


def _batch_feasible(
    vehicle: Vehicle,
    batch_ids: Set[int],
    by_id: Dict[int, Task],
    eval_cache: Dict[frozenset, Tuple[Optional[float], Optional[List[Task]], Optional[float]]],
    snapshot: Snapshot,
    now_ts: int,
) -> bool:
    if not batch_ids:
        return False
    key = frozenset(batch_ids)
    if key not in eval_cache:
        selected = [by_id[i] for i in key]
        eval_cache[key] = _evaluate_batch(vehicle, selected, snapshot, now_ts)
    return eval_cache[key][0] is not None


def _is_maximal_feasible_batch(
    vehicle: Vehicle,
    batch_ids: Set[int],
    by_id: Dict[int, Task],
    pool: List[Task],
    snapshot: Snapshot,
    eval_cache: Dict[frozenset, Tuple[Optional[float], Optional[List[Task]], Optional[float]]],
    now_ts: int,
) -> bool:
    if not _batch_feasible(vehicle, batch_ids, by_id, eval_cache, snapshot, now_ts):
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


def _extend_to_maximal(
    vehicle: Vehicle,
    batch_ids: Set[int],
    by_id: Dict[int, Task],
    pool: List[Task],
    snapshot: Snapshot,
    eval_cache: Dict[frozenset, Tuple[Optional[float], Optional[List[Task]], Optional[float]]],
    now_ts: int,
) -> Set[int]:
    state = set(batch_ids)
    if not _batch_feasible(vehicle, state, by_id, eval_cache, snapshot, now_ts):
        return set()

    cap = float(vehicle.get_remaining_load())
    changed = True
    while changed:
        changed = False
        used = sum(float(by_id[i].weight) for i in state)
        for task in sorted(pool, key=lambda t: t.id):
            if task.id in state:
                continue
            if float(task.weight) > cap - used + 1e-9:
                continue
            cand = set(state)
            cand.add(task.id)
            if _batch_feasible(vehicle, cand, by_id, eval_cache, snapshot, now_ts):
                state = cand
                used += float(task.weight)
                changed = True
    return state


def _greedy_initial_maximal(
    vehicle: Vehicle,
    pool: List[Task],
    snapshot: Snapshot,
    now_ts: int,
    eval_cache: Dict[frozenset, Tuple[Optional[float], Optional[List[Task]], Optional[float]]],
) -> Set[int]:
    by_id = {t.id: t for t in pool}
    cap = float(vehicle.get_remaining_load())
    ranked = sorted(
        pool,
        key=lambda t: calculate_assignment_score(
            t,
            vehicle,
            snapshot.distance(vehicle.position, t.position),
            now_ts,
        ),
        reverse=True,
    )

    state: Set[int] = set()
    used = 0.0
    for task in ranked:
        if float(task.weight) > cap - used + 1e-9:
            continue
        cand = set(state)
        cand.add(task.id)
        if _batch_feasible(vehicle, cand, by_id, eval_cache, snapshot, now_ts):
            state = cand
            used += float(task.weight)

    return _extend_to_maximal(
        vehicle, state, by_id, pool, snapshot, eval_cache, now_ts
    )


def find_best_maximal_batch_sa(
    vehicle: Vehicle,
    tasks: List[Task],
    snapshot: Snapshot,
) -> List[Task]:
    pool = utils.feasible_tasks_for(vehicle, tasks)
    if not pool:
        return []

    by_id = {t.id: t for t in pool}
    now_ts = int(snapshot.timestamp or 0)
    eval_cache: Dict[
        frozenset, Tuple[Optional[float], Optional[List[Task]], Optional[float]]
    ] = {}

    sa_cfg = config.get_scheduling_config().get("sa") or {}
    iterations = max(1, int(sa_cfg.get("iterations", 1500)))
    t_start = float(sa_cfg.get("t_start", 1000.0))
    t_end = max(1e-9, float(sa_cfg.get("t_end", 1.0)))
    seed = int(sa_cfg.get("seed", 42))
    rng = random.Random(seed + int(vehicle.id) * 997 + now_ts)

    def score_of(state: Set[int]) -> float:
        key = frozenset(state)
        _, _, score = eval_cache.get(key, (None, None, None))
        return float(score) if score is not None else float("-inf")

    def try_best(state: Set[int], best_ids: Set[int], best_score: float):
        if not _is_maximal_feasible_batch(
            vehicle, state, by_id, pool, snapshot, eval_cache, now_ts
        ):
            return best_ids, best_score
        sc = score_of(state)
        if sc > best_score + 1e-9:
            return set(state), sc
        return best_ids, best_score

    current = _greedy_initial_maximal(vehicle, pool, snapshot, now_ts, eval_cache)
    if not current:
        return []

    best_ids = set(current)
    best_score = score_of(current)
    current_score = best_score
    pool_ids = [t.id for t in pool]

    def neighbor(state: Set[int]) -> Set[int]:
        if not state:
            return set()
        nxt = set(state)
        move = rng.choice(("remove_add", "swap", "remove_extend"))
        if move == "remove_add":
            nxt.remove(rng.choice(list(nxt)))
            outside = [tid for tid in pool_ids if tid not in nxt]
            if outside:
                nxt.add(rng.choice(outside))
        elif move == "swap":
            nxt.remove(rng.choice(list(nxt)))
            outside = [tid for tid in pool_ids if tid not in nxt]
            if outside:
                nxt.add(rng.choice(outside))
        else:
            if len(nxt) <= 1:
                return set(state)
            nxt.remove(rng.choice(list(nxt)))

        if not _batch_feasible(vehicle, nxt, by_id, eval_cache, snapshot, now_ts):
            return set(state)
        return _extend_to_maximal(
            vehicle, nxt, by_id, pool, snapshot, eval_cache, now_ts
        )

    for step in range(iterations):
        if not current:
            current = _greedy_initial_maximal(
                vehicle, pool, snapshot, now_ts, eval_cache
            )
            if not current:
                break
            current_score = score_of(current)
            best_ids, best_score = try_best(current, best_ids, best_score)
            continue

        temperature = t_start * ((t_end / t_start) ** (step / max(1, iterations - 1)))
        candidate = neighbor(current)
        if not candidate:
            continue

        cand_score = score_of(candidate)
        delta = cand_score - current_score
        if delta >= 0 or rng.random() < math.exp(delta / max(temperature, 1e-9)):
            current = candidate
            current_score = cand_score
        best_ids, best_score = try_best(current, best_ids, best_score)

    if not best_ids:
        return []
    _, ordered, _ = eval_cache.get(frozenset(best_ids), (None, None, None))
    return list(ordered) if ordered else []


class SaScoreSearchScheduler(Scheduler):
    name = "sa_score_search"

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        commands: List[Command] = []

        for v in snapshot.idle_vehicles_not_at_warehouse():
            commands.append(utils.decide_en_route(v, snapshot))

        claimed = set()

        def pick_batch(vehicle, task_list, snap):
            unclaimed = [t for t in task_list if t.id not in claimed]
            return find_best_maximal_batch_sa(vehicle, unclaimed, snap)

        for v in snapshot.idle_vehicles_at_warehouse():
            cmd = utils.decide_at_warehouse(v, snapshot, pick_batch)
            if cmd.assigned_tasks:
                claimed.update(cmd.assigned_tasks)
            commands.append(cmd)

        return commands
