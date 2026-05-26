"""静态上帝视角优化调度器（VRPTW 近完整 MIP）。

核心：
1) 任务全集已知（含未来 release 时间）；
2) 一体化 MIP 联合优化：车辆路径 + 时间窗 + 载重；
3) 优先调用 Gurobi；不可用时回退到内置搜索；
4) 计划先算完，再按 release 时间逐步执行。
"""

from __future__ import annotations

import itertools
from typing import Dict, List, Optional, Tuple

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

        # 计划签名按“全部未完成任务”而不是“当前已释放任务”，保证上帝视角全局已知。
        signature = (
            tuple(sorted(t.id for t in all_pending)),
            tuple(sorted(v.id for v in planning_vehicles)),
        )
        if signature != self._plan_signature:
            self._vehicle_routes = self._build_global_plan(planning_vehicles, all_pending, snapshot)
            self._plan_signature = signature

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

        # 1) 优先尝试“一体化 VRPTW MIP”。
        route_plan = self._try_vrptw_solver(solver, vehicles, tasks, snapshot)
        if route_plan is not None:
            return route_plan
        if strict:
            msg = self._vrptw_disabled_reason or "VRPTW solver did not return OPTIMAL."
            raise RuntimeError(f"[STRICT_STATIC] global optimum not proven: {msg}")

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
        return route_map

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
        weight = {}
        for n in task_nodes:
            t = task_by_node[n]
            release[n] = max(0.0, float(t.create_time) - float(now_ts))
            deadline[n] = max(0.0, float(t.deadline) - float(now_ts))
            weight[n] = float(t.weight)

        m = gp.Model("neft_static_vrptw")
        m.Params.OutputFlag = 0
        static_cfg = (config.get_optimization_config().get("static") or {})
        strict = bool(static_cfg.get("strict_global_optimum", True))
        m.Params.MIPGap = 0.0 if strict else 0.01
        tl = static_cfg.get("time_limit_s", None)
        if tl is not None:
            m.Params.TimeLimit = float(tl)

        K = [v.id for v in vehicles]
        v_by_id = {v.id: v for v in vehicles}
        max_cap = max(float(v.get_remaining_load()) for v in vehicles) if vehicles else 0.0
        max_route_time = max(36000.0, max(deadline.values()) + 7200.0) if deadline else 36000.0

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
        tvar = {(k, n): m.addVar(lb=0.0, ub=max_route_time, vtype=GRB.CONTINUOUS, name=f"t_{k}_{n}")
                for k in K for n in task_nodes}

        # 每个任务的完成时刻 c[n] 与迟到 tard[n]
        c = {n: m.addVar(lb=0.0, ub=max_route_time, vtype=GRB.CONTINUOUS, name=f"c_{n}") for n in task_nodes}
        tard = {n: m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name=f"tard_{n}") for n in task_nodes}

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

        # 时间窗与弧时序
        M = max_route_time + max(travel.values()) + 1000.0 if travel else max_route_time + 1000.0
        for k in K:
            for n in task_nodes:
                # release
                m.addConstr(tvar[(k, n)] >= release[n] - M * (1 - y[(k, n)]), name=f"rel_{k}_{n}")
                # 关联 c[n]
                m.addConstr(c[n] >= tvar[(k, n)] - M * (1 - y[(k, n)]), name=f"c_lb_{k}_{n}")
                m.addConstr(c[n] <= tvar[(k, n)] + M * (1 - y[(k, n)]), name=f"c_ub_{k}_{n}")

            # start->j
            for j in task_nodes:
                m.addConstr(
                    tvar[(k, j)] >= travel[(start, j)] - M * (1 - x[(k, start, j)]),
                    name=f"time_start_{k}_{j}",
                )
            # i->j
            for i in task_nodes:
                for j in task_nodes:
                    if i == j:
                        continue
                    m.addConstr(
                        tvar[(k, j)] >= tvar[(k, i)] + travel[(i, j)] - M * (1 - x[(k, i, j)]),
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
        total_completion = gp.quicksum(c[n] for n in task_nodes)
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
            - float(EARLY_COMPLETION_REWARD_PER_MIN) / 60.0 * total_completion
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
        if strict:
            if m.status != GRB.OPTIMAL:
                self._vrptw_disabled_reason = f"Gurobi status={int(m.status)} (STRICT requires OPTIMAL)."
                return None
        elif m.status not in (GRB.OPTIMAL, GRB.TIME_LIMIT, GRB.SUBOPTIMAL):
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

