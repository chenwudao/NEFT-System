"""调度算法的工具箱。

把几乎所有算法都会重复写的小逻辑集中在这里，按需组合即可。
分为五类：
    1. 度量 / 查询         distance_to / nearest_task / feasible_tasks ...
    2. 电量与充电          can_reach_target / energy_required_for / best_charging_station ...
    3. 路径组合            greedy_chain / mst_order
    4. 指令构造            make_deliver_command / make_charge_command / ...
    5. 决策模板            decide_at_warehouse / decide_en_route

电量预判机制（重点）：
    仓库：`decide_at_warehouse` — 无货且无 pending 则 idle（`try_idle_at_warehouse`）；有货再按首跳 A/B 派单。
    路上：`decide_en_route`（含阈值充电与首跳 A/B）。
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
    """按输入顺序贪心装一批任务，只受车辆剩余载重约束。"""
    remaining = vehicle.get_remaining_load()
    batch: List[Task] = []
    for task in tasks:
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


def _charge_level(vehicle: Vehicle) -> float:
    """充电目标电量（与派单逻辑一致，默认 charge_until_pct=90%）。"""
    sched_cfg = config.get_scheduling_config()
    charge_until_pct = max(1.0, min(100.0, float(sched_cfg.get("charge_until_pct", 90.0))))
    return float(vehicle.max_battery) * charge_until_pct / 100.0


def _energy_to_target_with_buffer(
    vehicle: Vehicle,
    from_xy: Tuple[float, float],
    target_xy: Tuple[float, float],
    snapshot: Snapshot,
    *,
    require_station_buffer: bool,
) -> float:
    """从 from_xy 到 target_xy（含充电站 buffer）所需能量，已乘安全系数。"""
    leg_d = snapshot.distance(from_xy, target_xy)
    if leg_d == float("inf"):
        return float("inf")

    extra = 0.0
    if require_station_buffer and snapshot.charging_stations:
        d_buf = min_distance_to_any_station(
            target_xy, snapshot.charging_stations, snapshot
        )
        if d_buf == float("inf"):
            return float("inf")
        extra = d_buf

    return energy_required_for_distance(vehicle, leg_d + extra) * _safety_margin()


def _best_transit_station_for_target_from(
    from_xy: Tuple[float, float],
    from_battery: float,
    target_xy: Tuple[float, float],
    vehicle: Vehicle,
    snapshot: Snapshot,
    *,
    require_station_buffer: bool = True,
    prefer_load_cost: bool = True,
) -> Optional[ChargingStation]:
    """选中转充电站：当前位置/电量可达，且充到 charge_until_pct 后可到目标并留 buffer。"""
    stations = list(getattr(snapshot, "charging_stations", []) or [])
    if not stations:
        return None

    charge_level = _charge_level(vehicle)
    margin = _safety_margin()
    load_weight = 0.0
    queue_weight = 0.0
    if prefer_load_cost:
        sched_cfg = config.get_scheduling_config()
        load_weight = float(sched_cfg.get("charge_load_weight_m", 8000.0))
        queue_weight = float(sched_cfg.get("charge_queue_weight_m", 2000.0))

    best_station = None
    best_cost = float("inf")
    for st in stations:
        st_xy = (float(st.position.x), float(st.position.y))
        d_to_st = snapshot.distance(from_xy, st_xy)
        if d_to_st == float("inf"):
            continue
        need_to_st = energy_required_for_distance(vehicle, d_to_st) * margin
        if from_battery + 1e-9 < need_to_st:
            continue

        d_st_to_target = snapshot.distance(st_xy, target_xy)
        if d_st_to_target == float("inf"):
            continue

        extra = 0.0
        if require_station_buffer:
            d_target_to_station = min_distance_to_any_station(target_xy, stations, snapshot)
            if d_target_to_station == float("inf"):
                continue
            extra = d_target_to_station

        need_after_charge = energy_required_for_distance(
            vehicle, float(d_st_to_target) + float(extra)
        ) * margin
        if charge_level + 1e-9 < need_after_charge:
            continue

        waiting = max(
            0,
            int(getattr(st, "queue_count", 0)) - int(getattr(st, "capacity", 0)),
        )
        cost = (
            float(d_to_st)
            + float(getattr(st, "load_pressure", 0.0)) * load_weight
            + waiting * queue_weight
        )
        if cost < best_cost:
            best_cost = cost
            best_station = st
    return best_station


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


def estimate_chain_distance_with_recharge(
    vehicle: Vehicle,
    waypoints: List[Tuple[float, float]],
    snapshot: Snapshot,
    *,
    require_final_station_buffer: bool = True,
) -> float:
    """估算车辆完成一条任务链的实际车程（允许中途绕行充电站）。

    每段先尝试直达；不够则模拟先去充电站（充到 charge_until_pct，默认 90%）
    再继续。装批判定与派单的中转充电逻辑一致。

    返回值：
      - 可行时：车行驶总距离（米），不含回仓；
      - 不可行时：float("inf")。
    """
    if not waypoints:
        return 0.0

    if float(getattr(vehicle, "max_battery", 0.0)) <= 0:
        return float("inf")

    stations = list(getattr(snapshot, "charging_stations", []) or [])
    charge_level = _charge_level(vehicle)
    cur = (float(vehicle.position.x), float(vehicle.position.y))
    battery = float(vehicle.battery)
    total_d = 0.0

    for i, target in enumerate(waypoints):
        while True:
            need_buffer = require_final_station_buffer or (i < len(waypoints) - 1)
            need = _energy_to_target_with_buffer(
                vehicle,
                cur,
                target,
                snapshot,
                require_station_buffer=need_buffer,
            )
            if need == float("inf"):
                return float("inf")

            if battery + 1e-9 >= need:
                leg_d = snapshot.distance(cur, target)
                total_d += leg_d
                battery -= energy_required_for_distance(vehicle, leg_d)
                cur = target
                break

            # 直达不够：尝试先去充电站（充到 charge_until_pct）再送下一任务点
            if not stations:
                return float("inf")
            transit = _best_transit_station_for_target_from(
                cur,
                battery,
                target,
                vehicle,
                snapshot,
                require_station_buffer=need_buffer,
                prefer_load_cost=False,
            )
            if transit is None:
                return float("inf")

            st_xy = (float(transit.position.x), float(transit.position.y))
            d_to_station = snapshot.distance(cur, st_xy)
            if d_to_station == float("inf"):
                return float("inf")
            total_d += d_to_station
            battery = charge_level
            cur = st_xy

    return total_d


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


def path_midpoint(
    a_xy: Tuple[float, float],
    b_xy: Tuple[float, float],
    snapshot: Snapshot,
) -> Tuple[float, float]:
    """两点最短路径上按路网距离折半的中间节点。"""
    path = snapshot.path(a_xy, b_xy)
    if not path:
        return (float(a_xy[0]), float(a_xy[1]))
    if len(path) == 1:
        return path[0]

    seg_lens: List[float] = []
    total = 0.0
    for i in range(len(path) - 1):
        seg = snapshot.distance(path[i], path[i + 1])
        seg_lens.append(seg)
        total += seg
    if total <= 1e-9:
        return path[0]

    half = total / 2.0
    acc = 0.0
    for i, seg in enumerate(seg_lens):
        if acc + seg >= half - 1e-9:
            return path[i + 1] if (half - acc) > seg / 2.0 else path[i]
        acc += seg
    return path[-1]


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


def best_transit_station_for_target(
    vehicle: Vehicle,
    target_xy: Tuple[float, float],
    snapshot: Snapshot,
) -> Optional[ChargingStation]:
    """选择中转充电站：当前可达，且充到阈值后可到目标并预留到最近充电站缓冲。"""
    return _best_transit_station_for_target_from(
        (float(vehicle.position.x), float(vehicle.position.y)),
        float(vehicle.battery),
        target_xy,
        vehicle,
        snapshot,
        require_station_buffer=True,
        prefer_load_cost=True,
    )


def try_idle_at_warehouse(vehicle: Vehicle, snapshot: Snapshot) -> Optional[Command]:
    """车在仓库、车上无在途任务、且无 pending 可接时返回 idle，否则 None（不移动）。"""
    if snapshot.vehicle_undelivered_tasks(vehicle):
        return None
    if snapshot.available_tasks():
        return None
    return make_idle_command(vehicle)


def command_for_warehouse_batch(
    vehicle: Vehicle,
    snapshot: Snapshot,
    picked: List[Task],
) -> Command:
    """仓库已选好一批货：首跳条件 A 则 deliver；否则 B 则先去中转站充电；否则 idle。"""
    picked = feasible_task_batch_for(vehicle, picked)
    if not picked:
        return make_idle_command(vehicle)

    order = greedy_chain(
        (vehicle.position.x, vehicle.position.y),
        [(t.position.x, t.position.y) for t in picked],
        snapshot,
    )
    if not order:
        return make_idle_command(vehicle)

    id_by_xy = {(t.position.x, t.position.y): t for t in picked}
    first_task = id_by_xy.get(order[0])
    if first_task is None:
        return make_idle_command(vehicle)

    first_xy = (float(first_task.position.x), float(first_task.position.y))
    batch_ids = [t.id for t in picked]

    if can_reach_target(vehicle, first_xy, snapshot, require_station_buffer=True):
        return make_deliver_command(
            vehicle,
            first_task,
            assigned_tasks=batch_ids,
        )

    transit = best_transit_station_for_target(vehicle, first_xy, snapshot)
    if transit is not None:
        return make_charge_command(vehicle, transit)

    return make_idle_command(vehicle)


def decide_at_warehouse(
    vehicle: Vehicle,
    snapshot: Snapshot,
    pick_tasks: Callable[[Vehicle, List[Task], Snapshot], List[Task]],
) -> Command:
    """在仓库时的标准决策：

    1) 车上无货且无 pending → idle（**不**空车充电、不移动）
    2) 仅车上有货、无 pending → 按在途货派单（首跳 A/B）
    3) 有 pending → pick_tasks，再按首跳 A/B 派 deliver 或 charge
    """
    idle = try_idle_at_warehouse(vehicle, snapshot)
    if idle is not None:
        return idle

    on_board = snapshot.vehicle_undelivered_tasks(vehicle)
    pending = snapshot.available_tasks()

    if not pending:
        if on_board:
            return command_for_warehouse_batch(vehicle, snapshot, on_board)
        return make_idle_command(vehicle)

    picked = pick_tasks(vehicle, pending, snapshot)
    if not picked:
        if on_board:
            return command_for_warehouse_batch(vehicle, snapshot, on_board)
        return make_idle_command(vehicle)

    return command_for_warehouse_batch(vehicle, snapshot, picked)


def decide_en_route(vehicle: Vehicle, snapshot: Snapshot) -> Command:
    """车不在仓库的标准决策。

    - 阈值充电 → 就近充电
    - 还有未送达任务 → 首跳条件 A/B
    - 都送完了 → 回仓库
    """
    if needs_charge(vehicle):
        station = best_charging_station(vehicle, snapshot)
        if station is not None:
            return make_charge_command(vehicle, station)

    undelivered = snapshot.vehicle_undelivered_tasks(vehicle)

    if not undelivered:
        warehouse_xy = snapshot.warehouse_xy
        if not can_reach_target(vehicle, warehouse_xy, snapshot, require_station_buffer=True):
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

    # 首跳安全：下一站后必须还能去充电站；
    # 若不满足，尝试先去中转充电站补能再送。
    if not can_reach_target(vehicle, target_xy, snapshot, require_station_buffer=True):
        transit = best_transit_station_for_target(vehicle, target_xy, snapshot)
        if transit is not None:
            return make_charge_command(vehicle, transit)
        return make_idle_command(vehicle)

    return make_deliver_command(vehicle, nxt)
