"""调度算法的工具箱。

把几乎所有算法都会重复写的小逻辑集中在这里，按需组合即可。
分为三类：
    1. 度量 / 查询         distance_to / nearest_task / feasible_tasks ...
    2. 路径组合            greedy_chain / mst_order
    3. 指令构造            make_deliver_command / make_charge_command / make_return_command / make_idle_command
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


def needs_charge(vehicle: Vehicle) -> bool:
    """电量是否低于 config 里设置的 low_battery_pct。"""
    pct = vehicle.get_battery_percentage()
    thresh = float(config.get_scheduling_config().get("low_battery_pct", 20.0))
    return pct <= thresh


def can_reach_with_battery(
    vehicle: Vehicle, target_xy: Tuple[float, float], snapshot: Snapshot
) -> bool:
    """粗判：从当前位置走到 target 再走到最近充电站所需电量是否够。

    这是保守估计；写算法时不想考虑这一层可以直接忽略。
    """
    dist = snapshot.distance(vehicle.position, target_xy)
    if dist == float("inf"):
        return False
    # 再加一段"到最近充电站"的余量
    station = nearest_station(vehicle, snapshot.charging_stations, snapshot)
    if station is not None:
        dist += snapshot.distance(target_xy, station.position)
    need = dist * vehicle.unit_energy_consumption
    return vehicle.battery >= need


# ======================================================================
# 2. 路径组合（算法用来决定"顺路怎么走"）
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

    # 根据 parent 建邻接表，从 start 做 DFS
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
        # 子节点按距离近的先走
        adj[u].sort(key=lambda x: snapshot.distance(nodes[u], nodes[x]))
        for v in adj[u]:
            if not visited[v]:
                dfs(v)

    dfs(0)
    return [nodes[i] for i in order_idx]


# ======================================================================
# 3. 指令构造
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
    """让车去一个"特殊坐标"。

    典型用途：
      - 多个任务点的 MST/质心汇聚节点
      - 两辆车的接力碰头点（比如两车当前位置的中间节点）
      - 任何"先把车挪到这个点再说"的需求
    到达后车会变 IDLE，具体下一步由调度器继续决定。
    """
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
    """纯检查：src 能否把这些 task 交给 dst。不改任何状态。

    `tasks_by_id` 一般用 `{t.id: t for t in snapshot.tasks}` 传进来。
    用于算法在出接力命令前先做校验。
    """
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
    """构造"原地接力"指令：把 src 车上的这些 task 交给 dst 车。

    前置（由算法自己保证；执行层会再兜底检查一次）：
      - src / dst 当前坐标已经重合
      - dst 剩余载重够
      - 每个 task.assigned_vehicle_id == src.id
    执行层（DynamicSchedulingModule）会调用 DataManager.transfer_cargo。
    """
    return Command(
        vehicle_id=src.id,
        action=ACTION_HANDOFF,
        target_vehicle_id=dst.id,
        task_ids_to_transfer=list(task_ids),
    )


# ======================================================================
# 4. 常用组合：车在仓库时的一揽子决策
# ======================================================================


def decide_at_warehouse(
    vehicle: Vehicle,
    snapshot: Snapshot,
    pick_tasks: Callable[[Vehicle, List[Task], Snapshot], List[Task]],
) -> Command:
    """在仓库时的标准决策：

    1) 若电量低 → 就近充电
    2) 否则让传入的 `pick_tasks` 决定要接哪些任务
       - 有任务 → 装货 + 用 greedy_chain 排顺序，发第一跳 deliver
       - 无任务 → idle（等下一轮）

    `pick_tasks` 自己决定怎么选，比如：
        lambda v, ts, snap: [min(ts, key=lambda t: snap.distance(v.position, t.position))]
    """
    # 低电量优先充电
    if needs_charge(vehicle):
        station = nearest_station(vehicle, snapshot.charging_stations, snapshot)
        if station is not None:
            return make_charge_command(vehicle, station)

    pending = snapshot.available_tasks()
    if not pending:
        return make_idle_command(vehicle)

    picked = pick_tasks(vehicle, pending, snapshot)
    if not picked:
        return make_idle_command(vehicle)

    # 尊重配置里的单次任务数上限
    max_trip = config.get_scheduling_config().get("max_tasks_per_trip")
    if max_trip is not None:
        picked = picked[: int(max_trip)]

    # 载重约束兜底
    picked = feasible_tasks_for(vehicle, picked)
    if not picked:
        return make_idle_command(vehicle)

    # 用贪心把挑好的点排个顺序，下一跳就是其中第一个
    order = greedy_chain(
        (vehicle.position.x, vehicle.position.y),
        [(t.position.x, t.position.y) for t in picked],
        snapshot,
    )
    id_by_xy = {(t.position.x, t.position.y): t for t in picked}
    first_task = id_by_xy[order[0]]

    return make_deliver_command(
        vehicle,
        first_task,
        assigned_tasks=[t.id for t in picked],
    )


def decide_en_route(vehicle: Vehicle, snapshot: Snapshot) -> Command:
    """车刚到某个任务点（不在仓库），决定下一步。

    - 车上还有没送的任务 → 去最近的那个
    - 都送完了 → 回仓库
    - 电量紧急 → 先去充电
    """
    if needs_charge(vehicle):
        station = nearest_station(vehicle, snapshot.charging_stations, snapshot)
        if station is not None:
            return make_charge_command(vehicle, station)

    undelivered = snapshot.vehicle_undelivered_tasks(vehicle)
    if not undelivered:
        return make_return_command(vehicle, snapshot)

    nxt = min(
        undelivered,
        key=lambda t: snapshot.distance(vehicle.position, t.position),
    )
    return make_deliver_command(vehicle, nxt)
