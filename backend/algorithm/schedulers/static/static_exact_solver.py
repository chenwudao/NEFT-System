"""静态上帝视角优化调度器（VRPTW 近完整 MIP）。

核心：
1) 任务全集已知（含未来 release 时间）；
2) 一体化 MIP 联合优化：车辆路径 + 时间窗 + 载重；
3) 优先调用 Gurobi；不可用时回退到内置搜索；
4) 计划先算完，再按 release 时间逐步执行。
"""

from __future__ import annotations

import itertools
from typing import Any, Dict, List, Optional, Tuple

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.scoring_config import (
    DISTANCE_PENALTY,
    EARLY_COMPLETION_REWARD_PER_MIN,
    OVERDUE_PENALTY_PER_MIN,
    PRIORITY_REWARD,
    TASK_ASSIGN_REWARD,
)
from backend.algorithm.snapshot import Snapshot
from backend.config import config


class StaticExactSolverScheduler(Scheduler):
    name = "static_exact_solver"

    def __init__(self) -> None:
        self._plan_signature: Tuple[int, ...] = tuple()
        self._vehicle_routes: Dict[int, List[int]] = {}
        self._vrptw_disabled_reason: Optional[str] = None
        # 静态模式只做一次全局优化：首次建好计划后，不再重复求解。
        self._plan_built_once: bool = False

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        commands: List[Command] = []
        planning_vehicles = [
            v for v in snapshot.vehicles
            if str(getattr(v.status, "value", "")) != "stranded"
        ]
        if not planning_vehicles:
            return commands

        task_by_id_all = {t.id: t for t in snapshot.tasks}
        all_pending = [t for t in snapshot.tasks if str(getattr(t.status, "value", "")) == "pending"]

        # 路上车辆：优先按静态计划的既定顺序送下一站。
        for v in snapshot.idle_vehicles_not_at_warehouse():
            undelivered = snapshot.vehicle_undelivered_tasks(v)
            undelivered_ids = {t.id for t in undelivered}
            planned = self._vehicle_routes.get(v.id, [])
            next_tid = next((tid for tid in planned if tid in undelivered_ids), None)
            if next_tid is not None and next_tid in task_by_id_all:
                t = task_by_id_all[next_tid]
                commands.append(utils.make_deliver_command(v, t, assigned_tasks=[]))
            else:
                commands.append(utils.decide_en_route(v, snapshot))

        wh_vehicles = list(snapshot.idle_vehicles_at_warehouse())
        pending = list(snapshot.available_tasks())
        if not wh_vehicles:
            return commands
        if not all_pending:
            for v in wh_vehicles:
                commands.append(utils.decide_at_warehouse(v, snapshot, lambda *_: []))
            return commands

        # 静态模式只优化一次（全局已知时间线），后续按同一计划执行。
        if not self._plan_built_once:
            signature = (
                tuple(sorted(t.id for t in all_pending)),
                tuple(sorted(v.id for v in planning_vehicles)),
            )
            self._vehicle_routes = self._build_global_plan(planning_vehicles, all_pending, snapshot)
            self._plan_signature = signature
            self._plan_built_once = True

        planned_global = {
            tid
            for tids in self._vehicle_routes.values()
            for tid in tids
        }
        for v in wh_vehicles:
            route_ids = [tid for tid in self._vehicle_routes.get(v.id, []) if tid in task_by_id_all]
            if not route_ids:
                # 兜底：若全局路由缺失，至少从当前可释放任务中拿一单，避免“回仓-充电-不分配”循环。
                available_now = [
                    t for t in pending
                    if int(getattr(t, "create_time", 0)) <= int(snapshot.timestamp)
                    and t.id not in planned_global
                ]
                if available_now:
                    available_now.sort(key=lambda t: snapshot.distance(v.position, t.position))
                    fallback = available_now[0]
                    commands.append(utils.make_deliver_command(v, fallback, assigned_tasks=[fallback.id]))
                else:
                    commands.append(utils.make_idle_command(v))
                continue
            # 仅执行“已释放”的任务，未来任务只参与规划不提前执行
            released = [
                task_by_id_all[tid]
                for tid in route_ids
                if int(getattr(task_by_id_all[tid], "create_time", 0)) <= int(snapshot.timestamp)
                and str(getattr(task_by_id_all[tid].status, "value", "")) == "pending"
            ]
            if not released:
                commands.append(utils.make_idle_command(v))
                continue
            # 静态计划里，车辆在仓库时一次性装载自己后续要送的任务序列。
            commands.append(
                utils.make_deliver_command(
                    v,
                    released[0],
                    assigned_tasks=[t.id for t in released],
                )
            )
        return commands

    # ------------------------------------------------------------------
    # 规划
    # ------------------------------------------------------------------
    def _build_global_plan(self, vehicles, tasks, snapshot: Snapshot) -> Dict[int, List[int]]:
        opt_cfg = config.get_optimization_config()
        static_cfg = opt_cfg.get("static") or {}
        solver = str(static_cfg.get("solver", "gurobi")).lower()
        max_exact_tasks = int(static_cfg.get("max_exact_tasks", 10))
        strict = bool(static_cfg.get("strict_global_optimum", True))
        gap_th = float(static_cfg.get("mip_gap_threshold", 0.02))
        full_exact_enabled = bool(static_cfg.get("full_exact_global", True))
        full_exact_max_tasks = int(static_cfg.get("full_exact_max_tasks", max_exact_tasks))

        # 0) 小规模时优先做“全局穷举精确搜索”（包含充电/时间窗/电量可行）。
        if full_exact_enabled and len(tasks) <= max(1, full_exact_max_tasks):
            exact_plan = self._full_exact_global_with_charging(vehicles, tasks, snapshot)
            if exact_plan is not None:
                print(
                    f"[STATIC] Full exact global search accepted "
                    f"(tasks={len(tasks)}, vehicles={len(vehicles)})."
                )
                return exact_plan
            if strict:
                raise RuntimeError(
                    "[STRICT_STATIC] full exact global search failed to build feasible plan."
                )

        # 1) 优先尝试“一体化 VRPTW MIP”。
        route_plan = self._try_vrptw_solver(solver, vehicles, tasks, snapshot)
        if route_plan is not None:
            return self._repair_plan_with_energy(vehicles, tasks, route_plan, snapshot)
        if strict:
            msg = self._vrptw_disabled_reason or "VRPTW solver did not return OPTIMAL."
            raise RuntimeError(f"[STRICT_STATIC] global optimum not proven: {msg}")
        if self._vrptw_disabled_reason:
            print(f"[STATIC] VRPTW exact solver not accepted, fallback enabled: {self._vrptw_disabled_reason} (gap_th={gap_th:.4f})")

        # 2) 回退：先分配后排序。
        assign = self._try_solver_assignment(solver, vehicles, tasks, snapshot)
        if assign is None:
            # 3) 求解器不可用时：任务不大则全局精确分配，否则近似。
            if len(tasks) <= max_exact_tasks:
                assign = self._exact_assignment(vehicles, tasks, snapshot)
            else:
                assign = self._greedy_assignment(vehicles, tasks, snapshot)

        # 4) 每辆车内部再做顺序最优（小规模精确 / 大规模贪心）。
        route_map: Dict[int, List[int]] = {v.id: [] for v in vehicles}
        for v in vehicles:
            local = assign.get(v.id, [])
            ordered = self._best_order_for_vehicle(v, local, snapshot)
            route_map[v.id] = [t.id for t in ordered]
        return self._repair_plan_with_energy(vehicles, tasks, route_map, snapshot)

    def _repair_plan_with_energy(self, vehicles, tasks, route_map: Dict[int, List[int]], snapshot: Snapshot) -> Dict[int, List[int]]:
        """对求解器产出的全局计划做电量可行性修复。

        说明：
        - 上帝视角静态求解首先给出全局序列；
        - 这里再用“可中途充电”的链路仿真做可执行性过滤；
        - 不可执行任务会尝试重分配到其他车辆（保持载重约束），减少执行期卡住。
        """
        if not vehicles or not tasks:
            return route_map

        t_by_id = {t.id: t for t in tasks}
        v_by_id = {v.id: v for v in vehicles}
        repaired: Dict[int, List[int]] = {v.id: [] for v in vehicles}
        rem_cap: Dict[int, float] = {v.id: float(v.get_remaining_load()) for v in vehicles}
        dropped: List[int] = []

        # 1) 先按原计划顺序做“可行前缀”保留。
        for vid, tids in route_map.items():
            v = v_by_id.get(vid)
            if v is None:
                continue
            seq = []
            for tid in tids:
                t = t_by_id.get(tid)
                if t is None:
                    continue
                if float(t.weight) > rem_cap[vid] + 1e-9:
                    dropped.append(tid)
                    continue
                cand = seq + [t]
                if self._is_chain_feasible(v, cand, snapshot):
                    seq = cand
                    rem_cap[vid] -= float(t.weight)
                else:
                    dropped.append(tid)
            repaired[vid] = [t.id for t in seq]

        # 2) 把被丢弃的任务尝试重分配到其他车辆（增量最优，且必须可行）。
        for tid in dropped:
            t = t_by_id.get(tid)
            if t is None:
                continue
            best_vid = None
            best_gain = float("-inf")
            for v in vehicles:
                vid = v.id
                if float(t.weight) > rem_cap[vid] + 1e-9:
                    continue
                base_seq = [t_by_id[x] for x in repaired[vid] if x in t_by_id]
                base_obj = self._sequence_objective(v, base_seq, snapshot)
                cand_seq = base_seq + [t]
                if not self._is_chain_feasible(v, cand_seq, snapshot):
                    continue
                cand_obj = self._sequence_objective(v, cand_seq, snapshot)
                gain = cand_obj - base_obj
                if gain > best_gain:
                    best_gain = gain
                    best_vid = vid
            if best_vid is not None:
                repaired[best_vid].append(tid)
                rem_cap[best_vid] -= float(t.weight)

        return repaired

    def _full_exact_global_with_charging(self, vehicles, tasks, snapshot: Snapshot) -> Optional[Dict[int, List[int]]]:
        """全局穷举：任务分配 + 车内顺序联合最优（含充电时序仿真）。"""
        if not vehicles:
            return {}
        if not tasks:
            return {v.id: [] for v in vehicles}

        now_ts = float(int(snapshot.timestamp))
        sched_cfg = config.get_scheduling_config() or {}
        charge_until_pct = float(sched_cfg.get("charge_until_pct", 90.0))
        charge_until_pct = max(1.0, min(100.0, charge_until_pct))
        margin = float(sched_cfg.get("battery_safety_margin", 1.15))
        margin = max(1.0, margin)

        # 优先扩展更紧急任务，减少搜索树宽度。
        ordered_tasks = sorted(
            list(tasks),
            key=lambda t: (
                float(getattr(t, "deadline", 0.0)),
                float(getattr(t, "create_time", 0.0)),
                -float(getattr(t, "priority", 0.0)),
            ),
        )
        vehicles_by_id = {v.id: v for v in vehicles}
        states: Dict[int, Dict[str, Any]] = {
            v.id: {
                "route": [],
                "cap": float(v.get_remaining_load()),
                "cur_xy": (float(v.position.x), float(v.position.y)),
                "battery": float(v.battery),
                "cur_ts": now_ts,
                "cum_dist": 0.0,
                "score": 0.0,
            }
            for v in vehicles
        }

        best_score = float("-inf")
        best_routes: Optional[Dict[int, List[int]]] = None

        optimistic_per_task = []
        for t in ordered_tasks:
            release_ts = max(now_ts, float(getattr(t, "create_time", now_ts)))
            early_minutes = max(0.0, float(t.deadline) - release_ts) / 60.0
            optimistic = (
                float(TASK_ASSIGN_REWARD)
                + float(t.priority) * float(PRIORITY_REWARD)
                + early_minutes * float(EARLY_COMPLETION_REWARD_PER_MIN)
            )
            optimistic_per_task.append(max(0.0, optimistic))
        optimistic_suffix = [0.0] * (len(ordered_tasks) + 1)
        for i in range(len(ordered_tasks) - 1, -1, -1):
            optimistic_suffix[i] = optimistic_suffix[i + 1] + optimistic_per_task[i]

        def dfs(i: int, cur_states: Dict[int, Dict[str, Any]]) -> None:
            nonlocal best_score, best_routes
            cur_total = sum(float(st["score"]) for st in cur_states.values())
            if cur_total + optimistic_suffix[i] <= best_score + 1e-9:
                return

            if i >= len(ordered_tasks):
                if cur_total > best_score:
                    best_score = cur_total
                    best_routes = {
                        vid: list(st["route"]) for vid, st in cur_states.items()
                    }
                return

            task = ordered_tasks[i]
            progressed = False
            # 先试当前“最有希望”的车辆（截止时间更早 + 更近 + 剩余载重更大）
            candidate_vids = sorted(
                [v.id for v in vehicles if float(task.weight) <= float(cur_states[v.id]["cap"]) + 1e-9],
                key=lambda vid: (
                    snapshot.distance(cur_states[vid]["cur_xy"], task.position),
                    -float(cur_states[vid]["cap"]),
                ),
            )

            for vid in candidate_vids:
                vehicle = vehicles_by_id[vid]
                nxt = self._simulate_append_task_with_charging(
                    vehicle=vehicle,
                    state=cur_states[vid],
                    task=task,
                    snapshot=snapshot,
                    margin=margin,
                    charge_until_pct=charge_until_pct,
                )
                if nxt is None:
                    continue
                progressed = True
                new_states = dict(cur_states)
                new_states[vid] = nxt
                dfs(i + 1, new_states)

            # 严格全局求解里，每个任务必须被服务；若无可行车辆则该分支失败。
            if not progressed:
                return

        dfs(0, states)
        if best_routes is None:
            return None
        return best_routes

    def _simulate_append_task_with_charging(
        self,
        *,
        vehicle,
        state: Dict[str, Any],
        task,
        snapshot: Snapshot,
        margin: float,
        charge_until_pct: float,
    ) -> Optional[Dict[str, Any]]:
        """从当前车辆状态增量追加一个任务，返回新状态；不可行返回 None。"""
        if float(task.weight) > float(state["cap"]) + 1e-9:
            return None

        cur_xy = (float(state["cur_xy"][0]), float(state["cur_xy"][1]))
        cur_ts = float(state["cur_ts"])
        battery = float(state["battery"])
        cum_dist = float(state["cum_dist"])
        total_score = float(state["score"])
        speed = max(1e-6, float(getattr(vehicle, "speed", 10.0)))
        power = max(1e-6, float(getattr(vehicle, "charging_power", 0.022)))

        target_xy = (float(task.position.x), float(task.position.y))
        stations = list(getattr(snapshot, "charging_stations", []) or [])
        max_charge_target = max(
            0.0, min(float(vehicle.max_battery), float(vehicle.max_battery) * charge_until_pct / 100.0)
        )

        # 尝试在去任务点前插入充电站（必要时可重复，但限制迭代防死循环）。
        for _ in range(max(2, len(stations) + 2)):
            d_task = snapshot.distance(cur_xy, target_xy)
            if d_task == float("inf"):
                return None
            extra = 0.0
            if stations:
                extra = utils.min_distance_to_any_station(target_xy, stations, snapshot)
                if extra == float("inf"):
                    return None
            need = utils.energy_required_for_distance(vehicle, float(d_task) + float(extra)) * margin
            if battery + 1e-9 >= need:
                break

            choice = self._choose_best_recharge_stop(
                vehicle=vehicle,
                cur_xy=cur_xy,
                cur_ts=cur_ts,
                battery=battery,
                target_xy=target_xy,
                snapshot=snapshot,
                max_charge_target=max_charge_target,
                margin=margin,
            )
            if choice is None:
                return None
            station_xy, d_to_station, charge_to = choice

            # 去充电站
            consume = utils.energy_required_for_distance(vehicle, d_to_station)
            if consume == float("inf") or battery + 1e-9 < consume:
                return None
            battery -= consume
            cum_dist += float(d_to_station)
            cur_ts += float(d_to_station) / speed
            cur_xy = station_xy

            # 充电
            if charge_to > battery + 1e-9:
                cur_ts += (float(charge_to) - battery) / power
                battery = float(charge_to)
        else:
            return None

        # 送达任务点
        d_task = snapshot.distance(cur_xy, target_xy)
        if d_task == float("inf"):
            return None
        consume = utils.energy_required_for_distance(vehicle, d_task)
        if consume == float("inf") or battery + 1e-9 < consume:
            return None
        battery -= consume
        cum_dist += float(d_task)
        arrival_ts = cur_ts + float(d_task) / speed

        release_ts = float(getattr(task, "create_time", cur_ts))
        completion_ts = max(arrival_ts, release_ts)
        early_minutes = max(0.0, float(task.deadline) - completion_ts) / 60.0
        overdue_minutes = max(0.0, completion_ts - float(task.deadline)) / 60.0
        score = (
            float(TASK_ASSIGN_REWARD)
            + float(task.priority) * float(PRIORITY_REWARD)
            - cum_dist * float(DISTANCE_PENALTY)
            + early_minutes * float(EARLY_COMPLETION_REWARD_PER_MIN)
            - overdue_minutes * float(OVERDUE_PENALTY_PER_MIN)
        )
        total_score += max(0.0, float(score))

        nxt = dict(state)
        nxt["route"] = list(state["route"]) + [int(task.id)]
        nxt["cap"] = float(state["cap"]) - float(task.weight)
        nxt["cur_xy"] = target_xy
        nxt["battery"] = battery
        nxt["cur_ts"] = completion_ts
        nxt["cum_dist"] = cum_dist
        nxt["score"] = total_score
        return nxt

    def _choose_best_recharge_stop(
        self,
        *,
        vehicle,
        cur_xy: Tuple[float, float],
        cur_ts: float,
        battery: float,
        target_xy: Tuple[float, float],
        snapshot: Snapshot,
        max_charge_target: float,
        margin: float,
    ) -> Optional[Tuple[Tuple[float, float], float, float]]:
        """在当前位置为去 target 选择一站式补能点，返回(站点xy,到站距离,充到电量)。"""
        stations = list(getattr(snapshot, "charging_stations", []) or [])
        if not stations:
            return None

        speed = max(1e-6, float(getattr(vehicle, "speed", 10.0)))
        power = max(1e-6, float(getattr(vehicle, "charging_power", 0.022)))
        best: Optional[Tuple[Tuple[float, float], float, float]] = None
        best_eta = float("inf")
        best_trip = float("inf")

        for st in stations:
            st_xy = (float(st.position.x), float(st.position.y))
            d_to = snapshot.distance(cur_xy, st_xy)
            if d_to == float("inf"):
                continue
            to_station_energy = utils.energy_required_for_distance(vehicle, d_to)
            if to_station_energy == float("inf") or battery + 1e-9 < to_station_energy:
                continue

            battery_after_arrival = battery - to_station_energy
            d_after = snapshot.distance(st_xy, target_xy)
            if d_after == float("inf"):
                continue
            extra = utils.min_distance_to_any_station(target_xy, stations, snapshot)
            if extra == float("inf"):
                continue
            need_after = utils.energy_required_for_distance(vehicle, float(d_after) + float(extra)) * margin
            if need_after > float(vehicle.max_battery) + 1e-9:
                continue

            charge_to = max(float(max_charge_target), float(need_after), float(battery_after_arrival))
            charge_to = min(float(vehicle.max_battery), charge_to)
            if charge_to + 1e-9 < need_after:
                continue

            charge_time = max(0.0, charge_to - battery_after_arrival) / power
            eta = cur_ts + float(d_to) / speed + charge_time + float(d_after) / speed
            trip = float(d_to) + float(d_after)
            if eta < best_eta - 1e-9 or (abs(eta - best_eta) <= 1e-9 and trip < best_trip):
                best_eta = eta
                best_trip = trip
                best = (st_xy, float(d_to), float(charge_to))
        return best

    def _try_vrptw_solver(self, solver: str, vehicles, tasks, snapshot: Snapshot):
        if self._vrptw_disabled_reason:
            return None
        if solver == "gurobi":
            return self._try_gurobi_vrptw(vehicles, tasks, snapshot)
        # 预留 CPLEX
        return None

    def _try_gurobi_vrptw(self, vehicles, tasks, snapshot: Snapshot):
        """一体化 VRPTW MIP：x(k,i,j), 到达时刻 t(k,i), 迟到变量 tard(i)。"""
        try:
            import gurobipy as gp  # type: ignore
            from gurobipy import GRB  # type: ignore
        except Exception:
            return None

        if not vehicles or not tasks:
            return {v.id: [] for v in vehicles}

        # 节点编码：
        # 0: start depot, 1..N: tasks, N+1: end depot
        N = len(tasks)
        start = 0
        end = N + 1
        task_nodes = list(range(1, N + 1))
        nodes = [start] + task_nodes + [end]
        task_by_node = {i + 1: tasks[i] for i in range(N)}
        node_by_tid = {tasks[i].id: i + 1 for i in range(N)}

        wh = snapshot.warehouse_xy
        now_ts = int(snapshot.timestamp)
        speed = max(1e-6, min(float(getattr(v, "speed", 10.0)) for v in vehicles))

        # 距离与旅行时间矩阵
        dist = {}
        travel = {}
        for i in nodes:
            for j in nodes:
                if i == j:
                    continue
                if i == end or j == start:
                    continue
                if i == start:
                    a = wh
                else:
                    ti = task_by_node[i]
                    a = (ti.position.x, ti.position.y)
                if j == end:
                    b = wh
                else:
                    tj = task_by_node[j]
                    b = (tj.position.x, tj.position.y)
                d = snapshot.distance(a, b)
                if d == float("inf"):
                    d = 1e9
                dist[(i, j)] = float(d)
                travel[(i, j)] = float(d) / speed

        release = {}
        deadline = {}
        latest = {}
        weight = {}
        static_cfg = (config.get_optimization_config().get("static") or {})
        max_lateness_s = float(static_cfg.get("max_lateness_s", 7200.0))
        for n in task_nodes:
            t = task_by_node[n]
            release[n] = max(0.0, float(t.create_time) - float(now_ts))
            deadline[n] = max(0.0, float(t.deadline) - float(now_ts))
            latest[n] = deadline[n] + max_lateness_s
            weight[n] = float(t.weight)

        m = gp.Model("neft_static_vrptw")
        m.Params.OutputFlag = 1 if bool(static_cfg.get("live_gap_log", True)) else 0
        strict = bool(static_cfg.get("strict_global_optimum", True))
        gap_th = float(static_cfg.get("mip_gap_threshold", 0.02))
        m.Params.MIPGap = 0.0 if strict else max(0.0, gap_th)
        tl = static_cfg.get("time_limit_s", None)
        if tl is not None:
            m.Params.TimeLimit = float(tl)
        tuning = static_cfg.get("gurobi_tuning") or {}
        if "mip_focus" in tuning:
            m.Params.MIPFocus = int(tuning.get("mip_focus"))
        if "heuristics" in tuning:
            m.Params.Heuristics = float(tuning.get("heuristics"))
        if "cuts" in tuning:
            m.Params.Cuts = int(tuning.get("cuts"))
        if "presolve" in tuning:
            m.Params.Presolve = int(tuning.get("presolve"))
        if "threads" in tuning:
            m.Params.Threads = int(tuning.get("threads"))

        K = [v.id for v in vehicles]
        v_by_id = {v.id: v for v in vehicles}
        max_cap = max(float(v.get_remaining_load()) for v in vehicles) if vehicles else 0.0
        max_route_time = max(36000.0, max(latest.values()) + 600.0) if latest else 36000.0

        # x[k,i,j] 是否走弧 i->j
        x = {}
        for k in K:
            for i in nodes:
                for j in nodes:
                    if i == j or i == end or j == start:
                        continue
                    x[(k, i, j)] = m.addVar(vtype=GRB.BINARY, name=f"x_{k}_{i}_{j}")

        # y[k,n] 车辆k是否服务任务n
        y = {(k, n): m.addVar(vtype=GRB.BINARY, name=f"y_{k}_{n}") for k in K for n in task_nodes}

        # t[k,n] 车辆k到达节点n的时刻（仿真秒）
        tvar = {(k, n): m.addVar(lb=0.0, ub=latest[n], vtype=GRB.CONTINUOUS, name=f"t_{k}_{n}")
                for k in K for n in task_nodes}

        # 每个任务的完成时刻 c[n] 与迟到 tard[n]
        c = {n: m.addVar(lb=0.0, ub=latest[n], vtype=GRB.CONTINUOUS, name=f"c_{n}") for n in task_nodes}
        tard = {n: m.addVar(lb=0.0, ub=max_lateness_s, vtype=GRB.CONTINUOUS, name=f"tard_{n}") for n in task_nodes}

        # start / end 是否启用
        use_k = {k: m.addVar(vtype=GRB.BINARY, name=f"use_{k}") for k in K}

        # ---- 约束 ----
        # 每任务恰好由一辆车服务一次
        for n in task_nodes:
            m.addConstr(gp.quicksum(y[(k, n)] for k in K) == 1, name=f"serve_once_{n}")

        # 车辆流平衡
        for k in K:
            # 起点/终点
            m.addConstr(
                gp.quicksum(x[(k, start, j)] for j in task_nodes) == use_k[k],
                name=f"start_out_{k}",
            )
            m.addConstr(
                gp.quicksum(x[(k, i, end)] for i in task_nodes) == use_k[k],
                name=f"end_in_{k}",
            )
            # 任务点入=出=是否服务
            for n in task_nodes:
                m.addConstr(
                    gp.quicksum(x[(k, i, n)] for i in [start] + task_nodes if i != n) == y[(k, n)],
                    name=f"in_{k}_{n}",
                )
                m.addConstr(
                    gp.quicksum(x[(k, n, j)] for j in task_nodes + [end] if j != n) == y[(k, n)],
                    name=f"out_{k}_{n}",
                )
            # 载重约束（总分配重量）
            m.addConstr(
                gp.quicksum(weight[n] * y[(k, n)] for n in task_nodes) <= float(v_by_id[k].get_remaining_load()),
                name=f"cap_{k}",
            )

        # 时间窗与弧时序（使用更紧的弧级大M）
        for k in K:
            for n in task_nodes:
                # release
                m.addConstr(tvar[(k, n)] >= release[n] - latest[n] * (1 - y[(k, n)]), name=f"rel_{k}_{n}")
                # 关联 c[n]
                m.addConstr(c[n] >= tvar[(k, n)] - latest[n] * (1 - y[(k, n)]), name=f"c_lb_{k}_{n}")
                m.addConstr(c[n] <= tvar[(k, n)] + latest[n] * (1 - y[(k, n)]), name=f"c_ub_{k}_{n}")

            # start->j
            for j in task_nodes:
                m_start_j = max(0.0, travel[(start, j)] - release[j])
                m.addConstr(
                    tvar[(k, j)] >= travel[(start, j)] - m_start_j * (1 - x[(k, start, j)]),
                    name=f"time_start_{k}_{j}",
                )
            # i->j
            for i in task_nodes:
                for j in task_nodes:
                    if i == j:
                        continue
                    m_ij = max(0.0, latest[i] + travel[(i, j)] - release[j])
                    m.addConstr(
                        tvar[(k, j)] >= tvar[(k, i)] + travel[(i, j)] - m_ij * (1 - x[(k, i, j)]),
                        name=f"time_{k}_{i}_{j}",
                    )

        # tardiness
        for n in task_nodes:
            m.addConstr(tard[n] >= c[n] - deadline[n], name=f"tard_lb_{n}")
            m.addConstr(tard[n] >= 0.0, name=f"tard_nonneg_{n}")

        # ---- 目标函数 ----
        # 用与系统评分一致的线性代理：
        # maximize [priority + early(等价为-completion) - overdue - distance]
        # 常数项省略，只优化可变部分。
        total_distance = gp.quicksum(
            dist[(i, j)] * x[(k, i, j)]
            for k in K
            for i in nodes
            for j in nodes
            if (k, i, j) in x
        )
        total_tard = gp.quicksum(tard[n] for n in task_nodes)
        priority_term = gp.quicksum(
            float(task_by_node[n].priority) * float(PRIORITY_REWARD)
            for n in task_nodes
        )
        assign_term = float(TASK_ASSIGN_REWARD) * len(task_nodes)

        obj = (
            assign_term
            + priority_term
            - float(DISTANCE_PENALTY) * total_distance
            - float(OVERDUE_PENALTY_PER_MIN) / 60.0 * total_tard
        )
        m.setObjective(obj, GRB.MAXIMIZE)

        try:
            m.optimize()
        except Exception as exc:
            # 典型情况：size-limited license 模型过大
            self._vrptw_disabled_reason = str(exc)
            return None

        strict = bool(((config.get_optimization_config().get("static") or {}).get("strict_global_optimum", True)))
        gap_th = float(((config.get_optimization_config().get("static") or {}).get("mip_gap_threshold", 0.02)))
        if strict:
            if m.status != GRB.OPTIMAL:
                self._vrptw_disabled_reason = f"Gurobi status={int(m.status)} (STRICT requires OPTIMAL)."
                return None
        else:
            # 非严格：允许 time_limit/suboptimal，但必须有可行解且 MIPGap 在阈值内
            if m.status not in (GRB.OPTIMAL, GRB.TIME_LIMIT, GRB.SUBOPTIMAL):
                self._vrptw_disabled_reason = f"Gurobi status={int(m.status)} (accepted: OPTIMAL/TIME_LIMIT/SUBOPTIMAL)."
                return None
            if int(getattr(m, "SolCount", 0)) <= 0:
                self._vrptw_disabled_reason = "No feasible incumbent solution."
                return None
            mip_gap = float(getattr(m, "MIPGap", 1.0))
            if m.status != GRB.OPTIMAL and mip_gap > gap_th + 1e-9:
                self._vrptw_disabled_reason = (
                    f"MIPGap={mip_gap:.6f} exceeds threshold={gap_th:.6f}."
                )
                return None

        # 提取每车任务顺序
        out: Dict[int, List[int]] = {k: [] for k in K}
        for k in K:
            # follow arcs from start to end
            succ = {}
            for i in nodes:
                for j in nodes:
                    if (k, i, j) in x and x[(k, i, j)].X > 0.5:
                        succ[i] = j
            cur = start
            seen = set()
            while cur in succ:
                nxt = succ[cur]
                if nxt == end or nxt in seen:
                    break
                seen.add(nxt)
                tid = task_by_node[nxt].id
                out[k].append(tid)
                cur = nxt

            # 若出现提取异常，按时刻变量兜底
            if not out[k]:
                visited = [n for n in task_nodes if y[(k, n)].X > 0.5]
                visited.sort(key=lambda n: tvar[(k, n)].X)
                out[k] = [task_by_node[n].id for n in visited]

        return out

    def _try_solver_assignment(self, solver: str, vehicles, tasks, snapshot: Snapshot):
        if solver == "gurobi":
            return self._try_gurobi_assignment(vehicles, tasks, snapshot)
        if solver == "cplex":
            return self._try_cplex_assignment(vehicles, tasks, snapshot)
        return None

    def _try_gurobi_assignment(self, vehicles, tasks, snapshot: Snapshot):
        try:
            import gurobipy as gp  # type: ignore
            from gurobipy import GRB  # type: ignore
        except Exception:
            return None

        m = gp.Model("neft_static_assign")
        m.Params.OutputFlag = 0
        x = {}
        now_ts = int(snapshot.timestamp)

        for v in vehicles:
            for t in tasks:
                x[(v.id, t.id)] = m.addVar(vtype=GRB.BINARY, name=f"x_{v.id}_{t.id}")

        # 每个任务必须分配给且仅分配给一辆车
        for t in tasks:
            m.addConstr(gp.quicksum(x[(v.id, t.id)] for v in vehicles) == 1)

        # 载重约束
        for v in vehicles:
            m.addConstr(
                gp.quicksum(float(t.weight) * x[(v.id, t.id)] for t in tasks) <= float(v.get_remaining_load())
            )

        # 近似收益（分配层，不含序列项）：priority / deadline - 距离成本
        obj = []
        for v in vehicles:
            for t in tasks:
                d = snapshot.distance(v.position, t.position)
                if d == float("inf"):
                    # 不可达直接禁用
                    m.addConstr(x[(v.id, t.id)] == 0)
                    continue
                urgency = 1.0 / max(60.0, float(t.deadline) - float(now_ts))
                utility = (
                    float(TASK_ASSIGN_REWARD)
                    + float(t.priority) * float(PRIORITY_REWARD)
                    + urgency * 5000.0
                    - float(d) * float(DISTANCE_PENALTY)
                )
                obj.append(utility * x[(v.id, t.id)])
        m.setObjective(gp.quicksum(obj), GRB.MAXIMIZE)
        m.optimize()

        if m.status != GRB.OPTIMAL:
            return None
        out = {v.id: [] for v in vehicles}
        t_by_id = {t.id: t for t in tasks}
        for v in vehicles:
            for t in tasks:
                if x[(v.id, t.id)].X > 0.5:
                    out[v.id].append(t_by_id[t.id])
        return out

    def _try_cplex_assignment(self, vehicles, tasks, snapshot: Snapshot):
        # CPLEX Python API 依赖较重，这里做轻量探测；未安装直接回退。
        try:
            import cplex  # type: ignore  # noqa: F401
        except Exception:
            return None
        # 当前版本先不手写 CPLEX 建模，交给内置精确/近似分配。
        return None

    def _exact_assignment(self, vehicles, tasks, snapshot: Snapshot):
        best_obj = float("-inf")
        best_assign = {v.id: [] for v in vehicles}
        cap = {v.id: float(v.get_remaining_load()) for v in vehicles}
        current = {v.id: [] for v in vehicles}

        def upper_bound(idx: int) -> float:
            # 粗上界：剩余任务按“任务奖励+优先级奖励”全加
            rem = tasks[idx:]
            return sum(float(TASK_ASSIGN_REWARD) + float(t.priority) * float(PRIORITY_REWARD) for t in rem)

        def dfs(i: int, cur_obj_hint: float):
            nonlocal best_obj, best_assign
            if i >= len(tasks):
                total = 0.0
                for v in vehicles:
                    seq = self._best_order_for_vehicle(v, current[v.id], snapshot)
                    if current[v.id] and not seq:
                        return
                    total += self._sequence_objective(v, seq, snapshot)
                if total > best_obj:
                    best_obj = total
                    best_assign = {vid: list(ts) for vid, ts in current.items()}
                return

            if cur_obj_hint + upper_bound(i) <= best_obj + 1e-9:
                return

            t = tasks[i]
            for v in vehicles:
                if float(t.weight) > cap[v.id] + 1e-9:
                    continue
                cap[v.id] -= float(t.weight)
                current[v.id].append(t)
                dfs(i + 1, cur_obj_hint + float(TASK_ASSIGN_REWARD) + float(t.priority) * float(PRIORITY_REWARD))
                current[v.id].pop()
                cap[v.id] += float(t.weight)

        dfs(0, 0.0)
        return best_assign

    def _greedy_assignment(self, vehicles, tasks, snapshot: Snapshot):
        out = {v.id: [] for v in vehicles}
        rem_cap = {v.id: float(v.get_remaining_load()) for v in vehicles}
        for t in sorted(tasks, key=lambda x: (float(x.deadline), -float(x.priority))):
            best_vid = None
            best_gain = float("-inf")
            for v in vehicles:
                if float(t.weight) > rem_cap[v.id] + 1e-9:
                    continue
                d = snapshot.distance(v.position, t.position)
                if d == float("inf"):
                    continue
                gain = float(t.priority) * float(PRIORITY_REWARD) - float(d) * float(DISTANCE_PENALTY)
                if gain > best_gain:
                    best_gain = gain
                    best_vid = v.id
            if best_vid is not None:
                out[best_vid].append(t)
                rem_cap[best_vid] -= float(t.weight)
        return out

    def _best_order_for_vehicle(self, vehicle, tasks, snapshot: Snapshot):
        if not tasks:
            return []
        # 任务较少时枚举顺序，保证“车内路径”精确最优；较多时退化贪心链。
        if len(tasks) > 8:
            ordered_xy = utils.greedy_chain(
                (vehicle.position.x, vehicle.position.y),
                [(t.position.x, t.position.y) for t in tasks],
                snapshot,
            )
            id_by_xy = {(t.position.x, t.position.y): t for t in tasks}
            ordered = [id_by_xy[xy] for xy in ordered_xy if xy in id_by_xy]
            return ordered if self._is_chain_feasible(vehicle, ordered, snapshot) else []

        best = []
        best_obj = float("-inf")
        for perm in itertools.permutations(tasks, len(tasks)):
            seq = list(perm)
            if not self._is_chain_feasible(vehicle, seq, snapshot):
                continue
            obj = self._sequence_objective(vehicle, seq, snapshot)
            if obj > best_obj:
                best_obj = obj
                best = seq
        return best

    def _is_chain_feasible(self, vehicle, seq, snapshot: Snapshot) -> bool:
        waypoints = [(t.position.x, t.position.y) for t in seq]
        d = utils.estimate_chain_distance_with_recharge(
            vehicle,
            waypoints,
            snapshot,
            require_final_station_buffer=True,
        )
        return d != float("inf")

    def _sequence_objective(self, vehicle, seq, snapshot: Snapshot) -> float:
        if not seq:
            return 0.0
        cur = (vehicle.position.x, vehicle.position.y)
        cumulative_dist = 0.0
        now_ts = int(snapshot.timestamp)
        speed = max(1e-6, float(getattr(vehicle, "speed", 10.0)))
        total = 0.0
        cur_ts = float(now_ts)
        for t in seq:
            d = snapshot.distance(cur, t.position)
            if d == float("inf"):
                return float("-inf")
            cumulative_dist += float(d)
            arrival_ts = cur_ts + float(d) / speed
            release_ts = float(getattr(t, "create_time", now_ts))
            completion_ts = max(arrival_ts, release_ts)
            early_minutes = max(0.0, float(t.deadline) - completion_ts) / 60.0
            overdue_minutes = max(0.0, completion_ts - float(t.deadline)) / 60.0
            score = (
                float(TASK_ASSIGN_REWARD)
                + float(t.priority) * float(PRIORITY_REWARD)
                - cumulative_dist * float(DISTANCE_PENALTY)
                + early_minutes * float(EARLY_COMPLETION_REWARD_PER_MIN)
                - overdue_minutes * float(OVERDUE_PENALTY_PER_MIN)
            )
            total += max(0.0, float(score))
            cur = (t.position.x, t.position.y)
            cur_ts = completion_ts
        return total

