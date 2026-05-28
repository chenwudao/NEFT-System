"""区域规划调度：K-means 分包裹 + 多车认领（可行装批 + DFS 同款得分）。

流程概要（待分配任务数 >= 5）：
    1. 对待分配任务做 K-means（k=5），每个簇为一个包裹，按总重量降序。
    2. 在仓库空闲车之间做一轮认领：
       - 能整包装下 → 参与竞争，取得分最高者（calculate_batch_chain_score）。
       - 无人能整包 → 若有回仓库空车能整包则本帧不派该包；否则在可行子集里取得分最高者做部分装批。
    3. 仍有空闲车且剩余包裹已被其他候选“覆盖” → 选离仓库最远的车，装其可行子集中任务数最少的一包。

待分配 < 5：退化为 nearest_task 的最近贪心装批。

装批与出发：统一走 utils.decide_at_warehouse（整链可行 + 首跳 A/B）。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.schedulers.dfs_score_search import _evaluate_batch
from backend.algorithm.snapshot import Snapshot
from backend.data.task import Task
from backend.data.vehicle import Vehicle, VehicleStatus

_KMEANS_K = 5
_MIN_TASKS_FOR_CLUSTER = 5
_KMEANS_MAX_ITER = 30


@dataclass
class _Package:
    index: int
    tasks: List[Task]

    @property
    def total_weight(self) -> float:
        return sum(float(t.weight) for t in self.tasks)


def _pick_nearest_batch(
    vehicle: Vehicle,
    tasks: List[Task],
    snapshot: Snapshot,
    claimed: Set[int],
) -> List[Task]:
    """与 nearest_task 一致的最近贪心最大可行前缀装批。"""
    unclaimed = [t for t in tasks if t.id not in claimed]
    unclaimed = utils.feasible_tasks_for(vehicle, unclaimed)
    if not unclaimed:
        return []

    start_xy = (vehicle.position.x, vehicle.position.y)
    unclaimed.sort(key=lambda t: snapshot.distance(vehicle.position, t.position))

    chosen: List[Task] = []
    for t in unclaimed:
        cand = chosen + [t]
        ordered = utils.greedy_chain(
            start_xy,
            [(x.position.x, x.position.y) for x in cand],
            snapshot,
        )
        if not ordered:
            break
        dist = utils.estimate_chain_distance_with_recharge(
            vehicle,
            ordered,
            snapshot,
            require_final_station_buffer=True,
        )
        if dist == float("inf"):
            break
        chosen = cand
    return chosen


def _kmeans_packages(tasks: List[Task], k: int) -> List[_Package]:
    """对任务坐标做 K-means，返回非空簇包裹。"""
    if not tasks:
        return []
    if len(tasks) <= k:
        return [_Package(i, [t]) for i, t in enumerate(tasks)]

    pts = [(float(t.position.x), float(t.position.y)) for t in tasks]
    n = len(pts)
    k = min(k, n)

    rng = random.Random(42)
    idxs = rng.sample(range(n), k)
    centroids = [pts[i] for i in idxs]

    labels = [0] * n
    for _ in range(_KMEANS_MAX_ITER):
        changed = False
        for i, p in enumerate(pts):
            best_c = 0
            best_d = float("inf")
            for c, cen in enumerate(centroids):
                dx = p[0] - cen[0]
                dy = p[1] - cen[1]
                d = dx * dx + dy * dy
                if d < best_d:
                    best_d = d
                    best_c = c
            if labels[i] != best_c:
                labels[i] = best_c
                changed = True

        sums = [[0.0, 0.0, 0] for _ in range(k)]
        for i, p in enumerate(pts):
            c = labels[i]
            sums[c][0] += p[0]
            sums[c][1] += p[1]
            sums[c][2] += 1

        for c in range(k):
            if sums[c][2] > 0:
                centroids[c] = (sums[c][0] / sums[c][2], sums[c][1] / sums[c][2])

        if not changed:
            break

    clusters: List[List[Task]] = [[] for _ in range(k)]
    for task, lab in zip(tasks, labels):
        clusters[lab].append(task)

    packages: List[_Package] = []
    for i, cluster in enumerate(clusters):
        if cluster:
            packages.append(_Package(i, cluster))
    return packages


def _returning_empty_vehicles(snapshot: Snapshot) -> List[Vehicle]:
    """正在回仓库且车上无未送达任务的车（回仓后可接新货）。"""
    return [
        v
        for v in snapshot.vehicles
        if v.status == VehicleStatus.MOVING_TO_WAREHOUSE
        and not snapshot.vehicle_undelivered_tasks(v)
    ]


def _feasible_batch(
    vehicle: Vehicle,
    tasks: List[Task],
    snapshot: Snapshot,
) -> Tuple[Optional[List[Task]], float]:
    """可行装批评估：返回 (greedy_chain 顺序任务, 得分) 或 (None, -inf)。"""
    if not tasks:
        return None, float("-inf")
    pool = utils.feasible_tasks_for(vehicle, tasks)
    if len(pool) != len(tasks):
        return None, float("-inf")
    now_ts = int(snapshot.timestamp or 0)
    _, ordered, score = _evaluate_batch(vehicle, pool, snapshot, now_ts)
    if ordered is None or score is None:
        return None, float("-inf")
    return ordered, float(score)


def _best_feasible_subset_by_score(
    vehicle: Vehicle,
    tasks: List[Task],
    snapshot: Snapshot,
) -> Tuple[List[Task], float]:
    """在包裹任务池中求得分最高的可行子集（不要求最大可行）。"""
    pool = utils.feasible_tasks_for(vehicle, tasks)
    if not pool:
        return [], float("-inf")

    by_id = {t.id: t for t in pool}
    ids = sorted(by_id.keys())
    cap = float(vehicle.get_remaining_load())
    now_ts = int(snapshot.timestamp or 0)

    best_ids: Set[int] = set()
    best_score = float("-inf")

    def consider(state: Set[int]) -> None:
        nonlocal best_ids, best_score
        if not state:
            return
        selected = [by_id[i] for i in state]
        _, ordered, score = _evaluate_batch(vehicle, selected, snapshot, now_ts)
        if ordered is None or score is None:
            return
        if score > best_score + 1e-9 or (
            abs(score - best_score) <= 1e-9 and len(state) > len(best_ids)
        ):
            best_score = score
            best_ids = set(state)

    def dfs(idx: int, state: Set[int], cur_weight: float) -> None:
        if idx >= len(ids):
            consider(state)
            return
        dfs(idx + 1, state, cur_weight)
        tid = ids[idx]
        w = float(by_id[tid].weight)
        if cur_weight + w <= cap + 1e-9:
            state.add(tid)
            consider(state)
            dfs(idx + 1, state, cur_weight + w)
            state.remove(tid)

    if len(ids) <= 14:
        dfs(0, set(), 0.0)
    else:
        pool_sorted = sorted(pool, key=lambda t: -float(t.weight))
        state: Set[int] = set()
        cur_w = 0.0
        for t in pool_sorted:
            if cur_w + float(t.weight) <= cap + 1e-9:
                state.add(t.id)
                cur_w += float(t.weight)
        consider(state)

    if not best_ids:
        return [], float("-inf")
    ordered, sc = _feasible_batch(vehicle, [by_id[i] for i in best_ids], snapshot)
    return list(ordered) if ordered else [], sc


def _warehouse_distance(vehicle: Vehicle, snapshot: Snapshot) -> float:
    return snapshot.distance(vehicle.position, snapshot.warehouse_xy)


def _build_regional_assignments(
    snapshot: Snapshot,
    pending: List[Task],
    warehouse_vehicles: List[Vehicle],
) -> Dict[int, List[Task]]:
    """本帧区域规划：vehicle_id -> 拟装任务列表。"""
    packages = _kmeans_packages(pending, _KMEANS_K)
    packages.sort(key=lambda p: p.total_weight, reverse=True)

    returning = _returning_empty_vehicles(snapshot)
    assignments: Dict[int, List[Task]] = {v.id: [] for v in warehouse_vehicles}
    assigned_vehicles: Set[int] = set()
    taken_packages: Set[int] = set()
    # (vehicle_id, package_index, score) 已进入“考虑在内”的候选
    considered: List[Tuple[int, int, float]] = []

    # --- 阶段 1：整包可装 → 取得分最高车 ---
    for pkg in packages:
        if pkg.index in taken_packages:
            continue
        candidates: List[Tuple[Vehicle, List[Task], float]] = []
        for v in warehouse_vehicles:
            if v.id in assigned_vehicles:
                continue
            ordered, score = _feasible_batch(v, pkg.tasks, snapshot)
            if ordered is not None and len(ordered) == len(pkg.tasks):
                candidates.append((v, ordered, score))

        if not candidates:
            continue

        best_v, best_tasks, best_score = max(candidates, key=lambda x: x[2])
        assignments[best_v.id] = best_tasks
        assigned_vehicles.add(best_v.id)
        taken_packages.add(pkg.index)
        considered.append((best_v.id, pkg.index, best_score))

    # --- 阶段 2：无人能整包 ---
    for pkg in packages:
        if pkg.index in taken_packages:
            continue

        ret_can_full = False
        for rv in returning:
            ordered, _ = _feasible_batch(rv, pkg.tasks, snapshot)
            if ordered is not None and len(ordered) == len(pkg.tasks):
                ret_can_full = True
                break
        if ret_can_full:
            continue

        best: Optional[Tuple[Vehicle, List[Task], float]] = None
        for v in warehouse_vehicles:
            if v.id in assigned_vehicles:
                continue
            subset, score = _best_feasible_subset_by_score(v, pkg.tasks, snapshot)
            if not subset:
                continue
            if best is None or score > best[2] + 1e-9:
                best = (v, subset, score)

        if best is None:
            continue

        bv, btasks, bscore = best
        assignments[bv.id] = btasks
        assigned_vehicles.add(bv.id)
        taken_packages.add(pkg.index)
        considered.append((bv.id, pkg.index, bscore))

    # --- 阶段 3：空闲车且包裹已被其他候选覆盖 → 最远车装任务数最少的可行子集 ---
    remaining_pkgs = [p for p in packages if p.index not in taken_packages]
    if not remaining_pkgs:
        return assignments

    idle_vehicles = [v for v in warehouse_vehicles if v.id not in assigned_vehicles]
    if not idle_vehicles:
        return assignments

    pkg_by_index = {p.index: p for p in packages}

    def _covered_by_others(pkg_index: int, exclude_vid: int) -> bool:
        for vid, pidx, _ in considered:
            if pidx == pkg_index and vid != exclude_vid:
                return True
        pkg = pkg_by_index.get(pkg_index)
        if pkg is None:
            return False
        for v in warehouse_vehicles:
            if v.id == exclude_vid or v.id in assigned_vehicles:
                continue
            ordered, _ = _feasible_batch(v, pkg.tasks, snapshot)
            if ordered:
                return True
        return False

    idle_vehicles.sort(key=lambda v: _warehouse_distance(v, snapshot), reverse=True)
    for v in idle_vehicles:
        options: List[Tuple[int, List[Task], int]] = []
        for pkg in remaining_pkgs:
            if not _covered_by_others(pkg.index, v.id):
                continue
            subset, _ = _best_feasible_subset_by_score(v, pkg.tasks, snapshot)
            if subset:
                options.append((len(subset), subset, pkg.index))
        if not options:
            continue
        options.sort(key=lambda x: (x[0], -x[2]))
        _, tasks, pidx = options[0]
        assignments[v.id] = tasks
        assigned_vehicles.add(v.id)
        taken_packages.add(pidx)
        remaining_pkgs = [p for p in remaining_pkgs if p.index != pidx]

    return assignments


class RegionalPlanningScheduler(Scheduler):
    name = "regional_planning"

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        commands: List[Command] = []

        for v in snapshot.idle_vehicles_not_at_warehouse():
            commands.append(utils.decide_en_route(v, snapshot))

        claimed: Set[int] = set()
        pending = list(snapshot.available_tasks())
        warehouse_vs = list(snapshot.idle_vehicles_at_warehouse())

        use_cluster = len(pending) >= _MIN_TASKS_FOR_CLUSTER
        frame_plan: Dict[int, List[Task]] = {}
        if use_cluster and warehouse_vs and pending:
            frame_plan = _build_regional_assignments(snapshot, pending, warehouse_vs)

        def pick_batch(vehicle: Vehicle, tasks: List[Task], snap: Snapshot) -> List[Task]:
            unclaimed = [t for t in tasks if t.id not in claimed]
            if not unclaimed:
                return []

            if not use_cluster:
                return _pick_nearest_batch(vehicle, tasks, snap, claimed)

            planned = frame_plan.get(vehicle.id, [])
            if not planned:
                return []
            plan_ids = {t.id for t in planned}
            return [t for t in unclaimed if t.id in plan_ids]

        for v in warehouse_vs:
            cmd = utils.decide_at_warehouse(v, snapshot, pick_batch)
            if cmd.assigned_tasks:
                claimed.update(cmd.assigned_tasks)
            commands.append(cmd)

        return commands
