"""调度算法的工具箱。

把几乎所有算法都会重复写的小逻辑集中在这里，按需组合即可。
分为五类：
    1. 度量 / 查询         distance_to / nearest_task / feasible_tasks ...
    2. 电量与充电          can_reach_target / energy_required_for / best_charging_station ...
    3. 路径组合            greedy_chain / mst_order
    4. 指令构造            make_deliver_command / make_charge_command / ...
    5. 决策模板            decide_at_warehouse / decide_en_route

电量预判机制（重点）：
    所有算法都应通过 `decide_at_warehouse` / `decide_en_route` 模板
    使用，模板内部会做"是否能到下一目标点 + 缓冲到最近充电站"的硬约束检查。
    若不够电，先派去 `best_charging_station`（综合距离 + 负荷压力）。
"""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from backend.config import config
from backend.data.charging_station import ChargingStation
from backend.data.task import Task
from backend.data.vehicle import Vehicle

from .scheduler import (
    ACTION_CHARGE,
    ACTION_DELIVER,
    ACTION_GOTO_NODE,
    ACTION_HANDOFF,
    ACTION_IDLE,
    ACTION_RETURN,
    Command,
)
from .snapshot import Snapshot


# ======================================================================
# 1. 度量与查询
# ======================================================================


def distance_to(vehicle: Vehicle, target, snapshot: Snapshot) -> float:
    return snapshot.distance(vehicle.position, target)


def feasible_tasks_for(vehicle: Vehicle, tasks: List[Task]) -> List[Task]:
    """过滤出这辆车还能装下的任务（按剩余载重）。"""
    capacity = vehicle.get_remaining_load()
    return [t for t in tasks if t.weight <= capacity]


def feasible_task_batch_for(vehicle: Vehicle, tasks: List[Task]) -> List[Task]:
    """按输入顺序贪心装一批任务，保证总重量不超过车辆剩余载重。"""
    max_trip = config.get_scheduling_config().get("max_tasks_per_trip")
    max_trip_n = int(max_trip) if max_trip is not None else None
    remaining = vehicle.get_remaining_load()
    batch: List[Task] = []
    for task in tasks:
        if max_trip_n is not None and len(batch) >= max_trip_n:
            break
        if task.weight <= remaining + 1e-9:
            batch.append(task)
            remaining -= task.weight
    return batch


def nearest_task(
    vehicle: Vehicle, tasks: List[Task], snapshot: Snapshot
) -> Optional[Task]:
    """离车最近、装得下的 PENDING 任务；若无返回 None。"""
    candidates = feasible_tasks_for(vehicle, tasks)
    if not candidates:
        return None
    return min(candidates, key=lambda t: snapshot.distance(vehicle.position, t.position))


def nearest_station(
    vehicle: Vehicle, stations: List[ChargingStation], snapshot: Snapshot
) -> Optional[ChargingStation]:
    """离车最近的充电站；若无返回 None。"""
    if not stations:
        return None
    return min(stations, key=lambda s: snapshot.distance(vehicle.position, s.position))


# ======================================================================
# 2. 电量与充电
# ======================================================================


def _safety_margin() -> float:
    """安全余量系数：从 config 拿，默认 1.15（15% 余量）。"""
    return float(config.get_scheduling_config().get("battery_safety_margin", 1.15))


def needs_charge(vehicle: Vehicle) -> bool:
    """电量是否低于 config 里设置的 low_battery_pct（百分比阈值）。"""
    pct = vehicle.get_battery_percentage()
    thresh = float(config.get_scheduling_config().get("low_battery_pct", 20.0))
    return pct <= thresh


def energy_required_for_distance(vehicle: Vehicle, distance_m: float) -> float:
    """根据距离估算需要的能量（kWh 等效）。"""
    if distance_m == float("inf") or distance_m < 0:
        return float("inf")
    return float(distance_m) * float(vehicle.unit_energy_consumption)


def min_distance_to_any_station(
    xy: Tuple[float, float], stations: List[ChargingStation], snapshot: Snapshot
) -> float:
    """从一个点出发，到最近充电站的路网距离；没有站则 0。"""
    if not stations:
        return 0.0
    best = float("inf")
    for st in stations:
        d = snapshot.distance(xy, (st.position.x, st.position.y))
        if d < best:
            best = d
    return best if best != float("inf") else float("inf")


def can_reach_target(
    vehicle: Vehicle,
    target_xy: Tuple[float, float],
    snapshot: Snapshot,
    *,
    require_station_buffer: bool = True,
) -> bool:
    """判断车辆是否还有足够电量从当前位置走到 target_xy。

    若 require_station_buffer=True，额外要求：
        到达 target 后还要能到最近一个充电站（避免"送到了但回不来"）。

    任何不可达 / 距离无穷大的情况都视为 False。
    """
    d = snapshot.distance(vehicle.position, target_xy)
    if d == float("inf"):
        return False

    extra = 0.0
    if require_station_buffer and snapshot.charging_stations:
        d_buf = min_distance_to_any_station(
            target_xy, snapshot.charging_stations, snapshot
        )
        if d_buf == float("inf"):
            return False
        extra = d_buf

    need = energy_required_for_distance(vehicle, d + extra) * _safety_margin()
    return vehicle.battery + 1e-9 >= need


def can_reach_with_battery(
    vehicle: Vehicle, target_xy: Tuple[float, float], snapshot: Snapshot
) -> bool:
    """保守判断（向后兼容）：到 target 再到最近充电站是否够电。"""
    return can_reach_target(vehicle, target_xy, snapshot, require_station_buffer=True)


def can_reach_charging_station(
    vehicle: Vehicle, station: ChargingStation, snapshot: Snapshot
) -> bool:
    """判断车辆当前电量是否足够到达指定充电站。"""
    return can_reach_target(
        vehicle,
        (station.position.x, station.position.y),
        snapshot,
        require_station_buffer=False,
    )


def can_complete_chain(
    vehicle: Vehicle,
    waypoints: List[Tuple[float, float]],
    snapshot: Snapshot,
    *,
    require_station_buffer: bool = True,
) -> bool:
    """判断车辆是否能依次走完整条路径（含从 vehicle.position 出发的第一段）。

    waypoints 为按访问顺序排列的点（不含车辆当前位置）。最后一个点之后是否
    还要预留"到最近充电站"的余量，由 require_station_buffer 控制。
    """
    if not waypoints:
        return True

    total_d = 0.0
    cur = (vehicle.position.x, vehicle.position.y)
    for nxt in waypoints:
        d = snapshot.distance(cur, nxt)
        if d == float("inf"):
            return False
        total_d += d
        cur = nxt

    extra = 0.0
    if require_station_buffer and snapshot.charging_stations:
        d_buf = min_distance_to_any_station(cur, snapshot.charging_stations, snapshot)
        if d_buf == float("inf"):
            return False
        extra = d_buf

    need = energy_required_for_distance(vehicle, total_d + extra) * _safety_margin()
    return vehicle.battery + 1e-9 >= need


def best_charging_station(
    vehicle: Vehicle, snapshot: Snapshot
) -> Optional[ChargingStation]:
    """综合距离 + 充电站负荷压力，挑一个当前电量可达的"最优"充电站。

    评分 = 距离(米) + 排队/负荷惩罚。这样：
        - 距离一样，负荷低的优先；
        - 负荷一样，更近的优先；
        - 路网不可达或当前电量不可达的站直接排除。
    """
    if not snapshot.charging_stations:
        return None

    sched_cfg = config.get_scheduling_config()
    load_weight = float(sched_cfg.get("charge_load_weight_m", 8000.0))
    queue_weight = float(sched_cfg.get("charge_queue_weight_m", 2000.0))

    best = None
    best_cost = float("inf")
    for st in snapshot.charging_stations:
        d = snapshot.distance(vehicle.position, (st.position.x, st.position.y))
        if d == float("inf"):
            continue
        if not can_reach_charging_station(vehicle, st, snapshot):
            continue
        load_pen = float(getattr(st, "load_pressure", 0.0)) * load_weight
        # 排队车辆数（>capacity 时才算真的有排队）
        waiting = max(0, int(getattr(st, "queue_count", 0)) - int(getattr(st, "capacity", 0)))
        queue_pen = waiting * queue_weight
        cost = d + load_pen + queue_pen
        if cost < best_cost:
            best_cost = cost
            best = st
    return best


# ======================================================================
# 3. 路径组合（算法用来决定"顺路怎么走"）
# ======================================================================


def greedy_chain(
    start_xy: Tuple[float, float],
    points: List[Tuple[float, float]],
    snapshot: Snapshot,
) -> List[Tuple[float, float]]:
    """贪心 TSP：每次挑离当前位置最近的点，直到把所有点都排完。"""
    remaining = list(points)
    order: List[Tuple[float, float]] = []
    cur = start_xy
    while remaining:
        nxt = min(remaining, key=lambda p: snapshot.distance(cur, p))
        order.append(nxt)
        remaining.remove(nxt)
        cur = nxt
    return order


def mst_order(
    start_xy: Tuple[float, float],
    points: List[Tuple[float, float]],
    snapshot: Snapshot,
) -> List[Tuple[float, float]]:
    """基于最小生成树 + DFS 前序得到一条访问顺序。

    适合"一次派多个点、想让总路程尽量短"的批量场景。
    """
    if not points:
        return []
    nodes = [start_xy] + list(points)
    n = len(nodes)

    # Prim 建 MST
    in_tree = [False] * n
    parent = [-1] * n
    min_edge = [float("inf")] * n
    min_edge[0] = 0.0
    for _ in range(n):
        u = -1
        best = float("inf")
        for i in range(n):
            if not in_tree[i] and min_edge[i] < best:
                best = min_edge[i]
                u = i
        if u == -1:
            break
        in_tree[u] = True
        for v in range(n):
            if not in_tree[v]:
                d = snapshot.distance(nodes[u], nodes[v])
                if d < min_edge[v]:
                    min_edge[v] = d
                    parent[v] = u

    adj: List[List[int]] = [[] for _ in range(n)]
    for v in range(1, n):
        if parent[v] >= 0:
            adj[parent[v]].append(v)
            adj[v].append(parent[v])

    visited = [False] * n
    order_idx: List[int] = []

    def dfs(u: int) -> None:
        visited[u] = True
        if u != 0:
            order_idx.append(u)
        adj[u].sort(key=lambda x: snapshot.distance(nodes[u], nodes[x]))
        for v in adj[u]:
            if not visited[v]:
                dfs(v)

    dfs(0)
    return [nodes[i] for i in order_idx]


# ======================================================================
# 4. 指令构造
# ======================================================================


def make_idle_command(vehicle: Vehicle) -> Command:
    return Command(vehicle_id=vehicle.id, action=ACTION_IDLE)


def make_return_command(
    vehicle: Vehicle, snapshot: Snapshot
) -> Command:
    """让车回仓库（通常用于"车上的货送完了"或"找不到可做的任务"）。"""
    return Command(
        vehicle_id=vehicle.id,
        action=ACTION_RETURN,
        target_xy=snapshot.warehouse_xy,
    )


def make_charge_command(
    vehicle: Vehicle, station: ChargingStation
) -> Command:
    return Command(
        vehicle_id=vehicle.id,
        action=ACTION_CHARGE,
        target_xy=(station.position.x, station.position.y),
        station_id=station.id,
    )


def make_deliver_command(
    vehicle: Vehicle,
    task: Task,
    assigned_tasks: Optional[List[int]] = None,
) -> Command:
    """让车去送某个任务点。

    `assigned_tasks` 仅在"本轮在仓库把一批任务一次性塞上车"时需要——
    它告诉执行层"除了 task 外，这些任务也请挂到车上"。
    半路从一个任务点跳到下一个任务点时传 None 即可。
    """
    return Command(
        vehicle_id=vehicle.id,
        action=ACTION_DELIVER,
        target_xy=(task.position.x, task.position.y),
        task_id=task.id,
        assigned_tasks=list(assigned_tasks) if assigned_tasks else [],
    )


def make_goto_node_command(
    vehicle: Vehicle, target_xy: Tuple[float, float]
) -> Command:
    """让车去一个"特殊坐标"。到达后车会变 IDLE，由调度器再决定下一步。"""
    return Command(
        vehicle_id=vehicle.id,
        action=ACTION_GOTO_NODE,
        target_xy=(float(target_xy[0]), float(target_xy[1])),
    )


# ----------------------------------------------------------------------
# 接力 / 货物转交辅助
# ----------------------------------------------------------------------


def same_position(a: Vehicle, b: Vehicle, eps: float = 1e-4) -> bool:
    """两辆车是否在同一坐标（xy 差都小于 eps）。"""
    return (
        abs(a.position.x - b.position.x) < eps
        and abs(a.position.y - b.position.y) < eps
    )


def can_transfer_cargo(
    src: Vehicle, dst: Vehicle, task_ids: List[int], tasks_by_id: dict,
    eps: float = 1e-4,
) -> bool:
    """纯检查：src 能否把这些 task 交给 dst。不改任何状态。"""
    if src.id == dst.id or src.is_stranded() or dst.is_stranded():
        return False
    if not same_position(src, dst, eps):
        return False
    total_w = 0.0
    for tid in task_ids:
        t = tasks_by_id.get(tid)
        if t is None or t.assigned_vehicle_id != src.id:
            return False
        total_w += t.weight
    return dst.get_remaining_load() + 1e-9 >= total_w


def make_handoff_command(
    src: Vehicle, dst: Vehicle, task_ids: List[int]
) -> Command:
    """构造"原地接力"指令：把 src 车上的这些 task 交给 dst 车。"""
    return Command(
        vehicle_id=src.id,
        action=ACTION_HANDOFF,
        target_vehicle_id=dst.id,
        task_ids_to_transfer=list(task_ids),
    )


# ======================================================================
# 5. 常用组合：决策模板（所有"每车独立决策"算法的基础）
# ======================================================================


def _need_charge_at_warehouse(
    vehicle: Vehicle,
    snapshot: Snapshot,
    planned_chain: Optional[List[Tuple[float, float]]] = None,
) -> bool:
    """在仓库判断"是否该先充电"。两条件取或：
        1) 当前电量百分比已低于阈值；
        2) 如果给定了 planned_chain（仓库→各任务点→仓库），跑完它电量不够。
    """
    if needs_charge(vehicle):
        return True
    if planned_chain:
        # 加上从最后一个任务点回仓库的一段
        warehouse_xy = snapshot.warehouse_xy
        full = list(planned_chain) + [warehouse_xy]
        # 不需要再加"到充电站"的 buffer（回仓库本身就解决了能量）
        if not can_complete_chain(vehicle, full, snapshot, require_station_buffer=False):
            return True
    return False


def decide_at_warehouse(
    vehicle: Vehicle,
    snapshot: Snapshot,
    pick_tasks: Callable[[Vehicle, List[Task], Snapshot], List[Task]],
) -> Command:
    """在仓库时的标准决策：

    1) 若电量已低于阈值 → 就近充电（综合负荷）
    2) 否则让 pick_tasks 决定要接哪些任务；用贪心排序
    3) 二次预判：电量能否跑完"仓库 → 各任务点 → 仓库"；不够则改去充电
    4) 没有可接的任务 → idle
    """
    # 1) 阈值充电（先 cheap check）
    if needs_charge(vehicle):
        station = best_charging_station(vehicle, snapshot)
        if station is not None:
            return make_charge_command(vehicle, station)
        return make_idle_command(vehicle)

    pending = snapshot.available_tasks()
    if not pending:
        return make_idle_command(vehicle)

    picked = pick_tasks(vehicle, pending, snapshot)
    if not picked:
        return make_idle_command(vehicle)

    picked = feasible_task_batch_for(vehicle, picked)
    if not picked:
        return make_idle_command(vehicle)

    order = greedy_chain(
        (vehicle.position.x, vehicle.position.y),
        [(t.position.x, t.position.y) for t in picked],
        snapshot,
    )
    id_by_xy = {(t.position.x, t.position.y): t for t in picked}

    # 3) 电量预判：在仓库就跑完整条 chain（含回仓）
    if _need_charge_at_warehouse(vehicle, snapshot, planned_chain=order):
        # 不够电跑完整批任务时，先尝试缩小批量；不要因为一批太大就直接去充电。
        for n in range(len(picked) - 1, 0, -1):
            reduced = picked[:n]
            reduced_order = greedy_chain(
                (vehicle.position.x, vehicle.position.y),
                [(t.position.x, t.position.y) for t in reduced],
                snapshot,
            )
            if not _need_charge_at_warehouse(
                vehicle, snapshot, planned_chain=reduced_order
            ):
                reduced_by_xy = {(t.position.x, t.position.y): t for t in reduced}
                first_task = reduced_by_xy[reduced_order[0]]
                return make_deliver_command(
                    vehicle,
                    first_task,
                    assigned_tasks=[t.id for t in reduced],
                )

        # 缩到 1 单仍然不够 → 先充电
        station = best_charging_station(vehicle, snapshot)
        if station is not None:
            return make_charge_command(vehicle, station)
        # 找不到充电站：尝试只接第一个任务（缩小负担）
        first_task = id_by_xy[order[0]]
        if can_reach_target(vehicle, order[0], snapshot, require_station_buffer=True):
            return make_deliver_command(vehicle, first_task, assigned_tasks=[first_task.id])
        return make_idle_command(vehicle)

    first_task = id_by_xy[order[0]]
    return make_deliver_command(
        vehicle,
        first_task,
        assigned_tasks=[t.id for t in picked],
    )


def decide_en_route(vehicle: Vehicle, snapshot: Snapshot) -> Command:
    """车不在仓库的标准决策。

    - 阈值充电  → 就近充电
    - 还有未送达任务 → 先选下一站；预判"下一站 + 后续未送 + 回仓"电量
      不够则改去充电
    - 都送完了 → 回仓库；不够回则改去充电
    """
    if needs_charge(vehicle):
        station = best_charging_station(vehicle, snapshot)
        if station is not None:
            return make_charge_command(vehicle, station)
        # 没有充电站可用：还是尝试继续，最坏会 STRANDED（属于算法的"惩罚"）

    undelivered = snapshot.vehicle_undelivered_tasks(vehicle)

    if not undelivered:
        # 直接回仓
        warehouse_xy = snapshot.warehouse_xy
        if not can_reach_target(vehicle, warehouse_xy, snapshot, require_station_buffer=False):
            # 电量不足回仓，先去充电
            station = best_charging_station(vehicle, snapshot)
            if station is not None:
                return make_charge_command(vehicle, station)
        return make_return_command(vehicle, snapshot)

    # 选下一个最近的未送任务点
    nxt = min(
        undelivered,
        key=lambda t: snapshot.distance(vehicle.position, t.position),
    )
    target_xy = (nxt.position.x, nxt.position.y)

    # 路径预判：下一站 + 后续所有未送 + 回仓
    rest_xy: List[Tuple[float, float]] = [target_xy]
    for t in undelivered:
        if t.id == nxt.id:
            continue
        rest_xy.append((t.position.x, t.position.y))
    rest_xy.append(snapshot.warehouse_xy)

    if not can_complete_chain(vehicle, rest_xy, snapshot, require_station_buffer=False):
        # 不够电跑完 → 去充电
        station = best_charging_station(vehicle, snapshot)
        if station is not None:
            return make_charge_command(vehicle, station)
        # 找不到站；至少看能不能继续去这个最近的任务点（车上的货还能交付）
        if not can_reach_target(vehicle, target_xy, snapshot, require_station_buffer=True):
            # 实在不行回仓
            return make_return_command(vehicle, snapshot)

    return make_deliver_command(vehicle, nxt)
