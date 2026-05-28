"""K-means 区域标的 + 顺序拍卖多智能体调度（Cluster Auction MAS）。

每辆仓库空闲车视为一个 Agent，对聚类包裹（Lot）独立出价；协调层按包裹顺序拍卖决标。
出价 = 预测批得分 - 距离惩罚；平局时比预测得分、再比车 id。

流程（待分配 >= 5）：
    1. K-means → Lot 列表，按总重量降序拍卖。
    2. 各 Agent 本地生成 Bid（整包优先，否则部分可行子集）。
    3. 顺序拍卖：仅整包 Bid 竞争 → 胜者每帧最多赢 1 个 Lot。
    4. 无人整包：回仓空车可整包则 DEFER；否则开放部分装 Bid 再拍。
    5. 仍有空闲 Agent 且 Lot 已被他人出过可行标 → 最远车接任务数最少子集。

待分配 < 5：单任务 Lot 顺序拍卖（每车每帧最多赢 1 单）。

装批出发：utils.decide_at_warehouse（整链可行 + 首跳 A/B）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.schedulers.regional_planning import (
    _KMEANS_K,
    _MIN_TASKS_FOR_CLUSTER,
    _Package,
    _best_feasible_subset_by_score,
    _feasible_batch,
    _kmeans_packages,
    _returning_empty_vehicles,
    _warehouse_distance,
)
from backend.algorithm.snapshot import Snapshot
from backend.data.task import Task
from backend.data.vehicle import Vehicle

# 出价中的距离惩罚系数（与 scoring 距离惩罚量级接近）
_BID_DISTANCE_ALPHA = 0.02


@dataclass
class _Bid:
    vehicle_id: int
    lot_index: int
    tasks: List[Task]
    predicted_score: float
    bid_value: float
    is_full: bool


def _lot_centroid(pkg: _Package) -> Tuple[float, float]:
    if not pkg.tasks:
        return (0.0, 0.0)
    n = len(pkg.tasks)
    sx = sum(float(t.position.x) for t in pkg.tasks)
    sy = sum(float(t.position.y) for t in pkg.tasks)
    return sx / n, sy / n


def _bid_value(
    vehicle: Vehicle,
    predicted_score: float,
    centroid: Tuple[float, float],
    snapshot: Snapshot,
) -> float:
    dist = snapshot.distance(vehicle.position, centroid)
    if dist == float("inf"):
        return float("-inf")
    return predicted_score - _BID_DISTANCE_ALPHA * float(dist)


def _agent_collect_bids(
    vehicle: Vehicle,
    packages: List[_Package],
    snapshot: Snapshot,
) -> List[_Bid]:
    """Agent 本地评估：对每个 Lot 最多提交一条 Bid（整包优先，否则最高分部分批）。"""
    bids: List[_Bid] = []
    for pkg in packages:
        centroid = _lot_centroid(pkg)
        ordered, score = _feasible_batch(vehicle, pkg.tasks, snapshot)
        if ordered is not None and len(ordered) == len(pkg.tasks):
            bv = _bid_value(vehicle, score, centroid, snapshot)
            bids.append(
                _Bid(
                    vehicle_id=vehicle.id,
                    lot_index=pkg.index,
                    tasks=list(ordered),
                    predicted_score=score,
                    bid_value=bv,
                    is_full=True,
                )
            )
            continue

        subset, score = _best_feasible_subset_by_score(vehicle, pkg.tasks, snapshot)
        if not subset or score == float("-inf"):
            continue
        bv = _bid_value(vehicle, score, centroid, snapshot)
        bids.append(
            _Bid(
                vehicle_id=vehicle.id,
                lot_index=pkg.index,
                tasks=list(subset),
                predicted_score=score,
                bid_value=bv,
                is_full=False,
            )
        )
    return bids


def _pick_winner(
    lot_index: int,
    bids: List[_Bid],
    excluded_vehicles: Set[int],
    *,
    full_only: bool = False,
    partial_only: bool = False,
) -> Optional[_Bid]:
    pool = [
        b
        for b in bids
        if b.lot_index == lot_index and b.vehicle_id not in excluded_vehicles
    ]
    if full_only:
        pool = [b for b in pool if b.is_full]
    elif partial_only:
        pool = [b for b in pool if not b.is_full]

    if not pool:
        return None

    return max(
        pool,
        key=lambda b: (b.bid_value, b.predicted_score, -b.vehicle_id),
    )


def _lots_from_tasks(tasks: List[Task]) -> List[_Package]:
    """单任务拍卖：每个任务为一个 Lot。"""
    return [_Package(i, [t]) for i, t in enumerate(tasks)]


def _build_auction_assignments(
    snapshot: Snapshot,
    pending: List[Task],
    warehouse_vehicles: List[Vehicle],
    *,
    use_cluster: bool,
) -> Dict[int, List[Task]]:
    if not pending or not warehouse_vehicles:
        return {v.id: [] for v in warehouse_vehicles}

    if use_cluster:
        packages = _kmeans_packages(pending, _KMEANS_K)
    else:
        packages = _lots_from_tasks(pending)
        packages.sort(
            key=lambda p: (float(p.tasks[0].deadline), -float(p.tasks[0].weight)),
        )

    packages.sort(key=lambda p: p.total_weight, reverse=True)

    all_bids: List[_Bid] = []
    for v in warehouse_vehicles:
        all_bids.extend(_agent_collect_bids(v, packages, snapshot))

    returning = _returning_empty_vehicles(snapshot)
    assignments: Dict[int, List[Task]] = {v.id: [] for v in warehouse_vehicles}
    won_vehicles: Set[int] = set()
    taken_lots: Set[int] = set()
    considered: List[Tuple[int, int]] = []  # (vehicle_id, lot_index) 出过可行标

    for b in all_bids:
        pair = (b.vehicle_id, b.lot_index)
        if pair not in considered:
            considered.append(pair)

    # --- 拍卖阶段 1：整包竞价 ---
    for pkg in packages:
        if pkg.index in taken_lots:
            continue
        winner = _pick_winner(
            pkg.index, all_bids, won_vehicles, full_only=True
        )
        if winner is None:
            continue
        assignments[winner.vehicle_id] = winner.tasks
        won_vehicles.add(winner.vehicle_id)
        taken_lots.add(pkg.index)

    # --- 拍卖阶段 2：部分装 / 回仓 defer ---
    for pkg in packages:
        if pkg.index in taken_lots:
            continue

        for rv in returning:
            ordered, _ = _feasible_batch(rv, pkg.tasks, snapshot)
            if ordered is not None and len(ordered) == len(pkg.tasks):
                taken_lots.add(pkg.index)  # DEFER，本帧不派
                break
        else:
            pass
        if pkg.index in taken_lots:
            continue

        winner = _pick_winner(
            pkg.index, all_bids, won_vehicles, partial_only=True
        )
        if winner is None:
            continue
        assignments[winner.vehicle_id] = winner.tasks
        won_vehicles.add(winner.vehicle_id)
        taken_lots.add(pkg.index)

    # --- 拍卖阶段 3：空闲 Agent 兜底（最远车、最少任务子集）---
    pkg_by_index = {p.index: p for p in packages}
    remaining = [p for p in packages if p.index not in taken_lots]
    idle = [v for v in warehouse_vehicles if v.id not in won_vehicles]
    if not remaining or not idle:
        return assignments

    def _lot_has_other_bidder(lot_index: int, exclude_vid: int) -> bool:
        for vid, pidx in considered:
            if pidx == lot_index and vid != exclude_vid:
                return True
        return False

    idle.sort(key=lambda v: _warehouse_distance(v, snapshot), reverse=True)
    for v in idle:
        options: List[Tuple[int, List[Task], int]] = []
        for pkg in remaining:
            if not _lot_has_other_bidder(pkg.index, v.id):
                continue
            subset, _ = _best_feasible_subset_by_score(v, pkg.tasks, snapshot)
            if subset:
                options.append((len(subset), list(subset), pkg.index))
        if not options:
            continue
        options.sort(key=lambda x: (x[0], -x[2]))
        _, tasks, lot_idx = options[0]
        assignments[v.id] = tasks
        won_vehicles.add(v.id)
        taken_lots.add(lot_idx)
        remaining = [p for p in remaining if p.index != lot_idx]

    return assignments


class ClusterAuctionMasScheduler(Scheduler):
    """K-means 区域顺序拍卖多智能体调度器。"""

    name = "cluster_auction_mas"

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        commands: List[Command] = []

        for v in snapshot.idle_vehicles_not_at_warehouse():
            commands.append(utils.decide_en_route(v, snapshot))

        claimed: Set[int] = set()
        pending = list(snapshot.available_tasks())
        warehouse_vs = list(snapshot.idle_vehicles_at_warehouse())
        use_cluster = len(pending) >= _MIN_TASKS_FOR_CLUSTER

        frame_plan: Dict[int, List[Task]] = {}
        if warehouse_vs and pending:
            frame_plan = _build_auction_assignments(
                snapshot,
                pending,
                warehouse_vs,
                use_cluster=use_cluster,
            )

        def pick_batch(vehicle: Vehicle, tasks: List[Task], snap: Snapshot) -> List[Task]:
            unclaimed = [t for t in tasks if t.id not in claimed]
            if not unclaimed:
                return []
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
