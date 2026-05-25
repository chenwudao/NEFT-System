"""模拟退火 (Simulated Annealing) 元启发式调度器。

调用语义：每次调度时，对仓库待派单做一次"分配 + TSP 排序"的 SA 搜索，
目标是最小化：

    Σ(车辆 route 总距离) - α * Σ(已接任务的得分)

其中：
- "得分" 用 `scoring_config.calculate_assignment_score`，即和系统一致的评分公式
- 决策变量：每辆车从仓库出发"挑哪一批任务、按什么顺序送"

SA 跑完后，把每辆车要接的第一个任务作为下一步 deliver 指令发下去，
后续每个任务点到达后再调度，相当于"重新 SA 一次"。

由于纯 Python 实现 + 没有 numpy，循环次数控制在 1k-2k 内，开销可控。
"""

from __future__ import annotations

import math
import random
import time
from typing import Dict, List, Optional, Tuple

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.scoring_config import calculate_assignment_score
from backend.algorithm.snapshot import Snapshot
from backend.algorithm.utils import (
    best_charging_station,
    can_complete_chain,
    decide_en_route,
    make_charge_command,
    make_deliver_command,
    make_idle_command,
    needs_charge,
)
from backend.config import config
from backend.data.task import Task
from backend.data.vehicle import Vehicle


# ----------------------------------------------------------------------
# SA 解结构：assignments[vehicle_id] = ordered list of task_id
# ----------------------------------------------------------------------


def _route_distance(
    vehicle: Vehicle, task_seq: List[Task], snapshot: Snapshot
) -> float:
    """车辆从当前位置出发 → 依次访问 task_seq → 回仓库的总距离。"""
    if not task_seq:
        return 0.0
    total = 0.0
    cur = (vehicle.position.x, vehicle.position.y)
    for t in task_seq:
        nxt = (t.position.x, t.position.y)
        d = snapshot.distance(cur, nxt)
        if d == float("inf"):
            return float("inf")
        total += d
        cur = nxt
    back = snapshot.distance(cur, snapshot.warehouse_xy)
    if back == float("inf"):
        return float("inf")
    return total + back


def _evaluate(
    solution: Dict[int, List[int]],
    vehicles_by_id: Dict[int, Vehicle],
    tasks_by_id: Dict[int, Task],
    snapshot: Snapshot,
    alpha: float,
    now_ts: int,
) -> float:
    """目标函数：距离 - α × 收益。越小越好。"""
    total_dist = 0.0
    total_score = 0.0
    for vid, tids in solution.items():
        v = vehicles_by_id.get(vid)
        if v is None or not tids:
            continue
        seq = [tasks_by_id[tid] for tid in tids if tid in tasks_by_id]
        d = _route_distance(v, seq, snapshot)
        if d == float("inf"):
            return float("inf")
        total_dist += d
        # 任务得分（用单段距离近似）
        cur = (v.position.x, v.position.y)
        for t in seq:
            seg = snapshot.distance(cur, t.position)
            if seg == float("inf"):
                return float("inf")
            total_score += calculate_assignment_score(t, v, seg, now_ts)
            cur = (t.position.x, t.position.y)
    return total_dist - alpha * total_score


def _is_feasible(
    solution: Dict[int, List[int]],
    vehicles_by_id: Dict[int, Vehicle],
    tasks_by_id: Dict[int, Task],
    snapshot: Snapshot,
) -> bool:
    """硬约束：载重 + 电量能跑完整条 chain（含回仓）。"""
    for vid, tids in solution.items():
        v = vehicles_by_id.get(vid)
        if v is None:
            continue
        if not tids:
            continue
        total_w = 0.0
        chain: List[Tuple[float, float]] = []
        for tid in tids:
            t = tasks_by_id.get(tid)
            if t is None:
                return False
            total_w += t.weight
            chain.append((t.position.x, t.position.y))
        if total_w > v.get_remaining_load() + 1e-9:
            return False
        chain.append(snapshot.warehouse_xy)
        if not can_complete_chain(v, chain, snapshot, require_station_buffer=False):
            return False
    return True


def _initial_solution(
    vehicles: List[Vehicle],
    available: List[Task],
    snapshot: Snapshot,
) -> Dict[int, List[int]]:
    """贪心构造初始解：按 priority+近距离循环分配给负载最小的车。"""
    sol: Dict[int, List[int]] = {v.id: [] for v in vehicles}
    loads: Dict[int, float] = {v.id: 0.0 for v in vehicles}
    vehicles_by_id = {v.id: v for v in vehicles}

    tasks_sorted = sorted(
        available, key=lambda t: (-t.priority, t.deadline, t.weight)
    )
    for t in tasks_sorted:
        # 找能装下、距离最近的车
        candidates = [
            (v.id, snapshot.distance(v.position, t.position) + loads[v.id] * 10)
            for v in vehicles
            if loads[v.id] + t.weight <= v.max_load and t.weight <= v.get_remaining_load()
        ]
        if not candidates:
            continue
        best_vid = min(candidates, key=lambda c: c[1])[0]
        sol[best_vid].append(t.id)
        loads[best_vid] += t.weight

    # 每辆车内部用贪心 TSP 排一下
    for vid, tids in sol.items():
        v = vehicles_by_id[vid]
        if len(tids) <= 1:
            continue
        ts = [t for t in available if t.id in tids]
        ordered = utils.greedy_chain(
            (v.position.x, v.position.y),
            [(t.position.x, t.position.y) for t in ts],
            snapshot,
        )
        id_by_xy = {(t.position.x, t.position.y): t.id for t in ts}
        sol[vid] = [id_by_xy[xy] for xy in ordered]

    return sol


def _neighbor(
    solution: Dict[int, List[int]],
    vehicle_ids: List[int],
    rng: random.Random,
) -> Dict[int, List[int]]:
    """随机扰动：3 种 move 各 1/3 概率。"""
    new_sol = {vid: list(tids) for vid, tids in solution.items()}
    if not vehicle_ids:
        return new_sol

    move = rng.random()

    # 1) 同车内交换两个任务的位置
    if move < 0.34:
        vid = rng.choice(vehicle_ids)
        seq = new_sol[vid]
        if len(seq) >= 2:
            i, j = rng.sample(range(len(seq)), 2)
            seq[i], seq[j] = seq[j], seq[i]
        return new_sol

    # 2) 把一个任务从车 A 移到车 B
    if move < 0.67:
        non_empty = [vid for vid in vehicle_ids if new_sol[vid]]
        if not non_empty:
            return new_sol
        a = rng.choice(non_empty)
        b = rng.choice(vehicle_ids)
        if a == b or not new_sol[a]:
            return new_sol
        idx = rng.randrange(len(new_sol[a]))
        tid = new_sol[a].pop(idx)
        # 随机插入位置
        insert_at = rng.randint(0, len(new_sol[b]))
        new_sol[b].insert(insert_at, tid)
        return new_sol

    # 3) 反转一段子序列
    vid = rng.choice(vehicle_ids)
    seq = new_sol[vid]
    if len(seq) >= 2:
        i, j = sorted(rng.sample(range(len(seq)), 2))
        seq[i:j + 1] = list(reversed(seq[i:j + 1]))
    return new_sol


class SimulatedAnnealingScheduler(Scheduler):
    """SA 元启发式调度器。"""

    name = "simulated_annealing"

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        commands: List[Command] = []

        # 1) 路上车辆：仍按模板决策（每个 SA 内的车单独走一段 by 模板）
        for v in snapshot.idle_vehicles_not_at_warehouse():
            commands.append(decide_en_route(v, snapshot))

        # 2) 仓库车辆：对它们集合做一次 SA
        vehicles = [
            v for v in snapshot.idle_vehicles_at_warehouse()
            if not needs_charge(v)
        ]

        # 需要充电的车先安排好
        for v in snapshot.idle_vehicles_at_warehouse():
            if needs_charge(v):
                station = best_charging_station(v, snapshot)
                if station is not None:
                    commands.append(make_charge_command(v, station))
                else:
                    commands.append(make_idle_command(v))

        if not vehicles:
            return commands

        available = list(snapshot.available_tasks())
        if not available:
            for v in vehicles:
                commands.append(make_idle_command(v))
            return commands

        vehicles_by_id = {v.id: v for v in vehicles}
        tasks_by_id = {t.id: t for t in available}
        vehicle_ids = list(vehicles_by_id.keys())

        sched_cfg = config.get_scheduling_config()
        sa_cfg = sched_cfg.get("sa") or {}
        iters = int(sa_cfg.get("iterations", 1500))
        t_start = float(sa_cfg.get("t_start", 1000.0))
        t_end = float(sa_cfg.get("t_end", 1.0))
        alpha_reward = float(sa_cfg.get("alpha_reward", 2.0))  # 距离 vs 收益的权衡
        seed = sa_cfg.get("seed")

        rng = random.Random(seed) if seed is not None else random.Random()
        now_ts = int(snapshot.timestamp or time.time())

        # 初始解（不保证可行，下面 SA 会逐步过滤）
        current = _initial_solution(vehicles, available, snapshot)
        if not _is_feasible(current, vehicles_by_id, tasks_by_id, snapshot):
            # 退化：清空，让算法只挑能放进去的
            current = {vid: [] for vid in vehicle_ids}

        current_cost = _evaluate(
            current, vehicles_by_id, tasks_by_id, snapshot, alpha_reward, now_ts
        )
        best = {vid: list(tids) for vid, tids in current.items()}
        best_cost = current_cost

        # 冷却
        if iters <= 0 or t_start <= t_end:
            cooling = 1.0
        else:
            cooling = (t_end / t_start) ** (1.0 / iters)
        temperature = t_start

        for _ in range(max(0, iters)):
            cand = _neighbor(current, vehicle_ids, rng)
            if not _is_feasible(cand, vehicles_by_id, tasks_by_id, snapshot):
                temperature *= cooling
                continue
            cand_cost = _evaluate(
                cand, vehicles_by_id, tasks_by_id, snapshot, alpha_reward, now_ts
            )
            if cand_cost == float("inf"):
                temperature *= cooling
                continue
            delta = cand_cost - current_cost
            if delta <= 0 or rng.random() < math.exp(-delta / max(1e-6, temperature)):
                current = cand
                current_cost = cand_cost
                if cand_cost < best_cost:
                    best = {vid: list(tids) for vid, tids in cand.items()}
                    best_cost = cand_cost
            temperature *= cooling

        # 落地：每辆车的第一个 task 作为 deliver
        for v in vehicles:
            tids = best.get(v.id, [])
            if not tids:
                commands.append(make_idle_command(v))
                continue
            first = tasks_by_id.get(tids[0])
            if first is None:
                commands.append(make_idle_command(v))
                continue
            commands.append(make_deliver_command(v, first, assigned_tasks=list(tids)))

        return commands
