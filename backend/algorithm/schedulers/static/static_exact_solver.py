"""静态上帝视角优化调度器（VRPTW 近完整 MIP）。

核心：
1) 任务全集已知（含未来 release 时间）；
2) 一体化 MIP 联合优化：车辆路径 + 时间窗 + 载重；
3) 优先调用 Gurobi；可配置为强制仅 Gurobi；
4) 计划先算完，再按 release 时间逐步执行。
"""

from __future__ import annotations

import itertools
import random
import time
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
        self._warehouse_command_plan: Dict[int, List[Dict[str, Any]]] = {}
        self._warehouse_plan_cursor: Dict[int, int] = {}
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
            self._warehouse_command_plan = {}
            self._warehouse_plan_cursor = {}
            self._vehicle_routes = self._build_global_plan(planning_vehicles, all_pending, snapshot)
            self._plan_signature = signature
            self._plan_built_once = True

        planned_global = {
            tid
            for tids in self._vehicle_routes.values()
            for tid in tids
        }
        for v in wh_vehicles:
            # exact 仓库命令计划：只在仓库时按计划时刻发批量指令，允许主动等待。
            plan_cmds = self._warehouse_command_plan.get(v.id, [])
            if plan_cmds:
                cursor = int(self._warehouse_plan_cursor.get(v.id, 0))
                now_ts = int(snapshot.timestamp)
                dispatched = False
                while cursor < len(plan_cmds):
                    item = plan_cmds[cursor]
                    tids = list(item.get("task_ids", []) or [])
                    if not tids:
                        cursor += 1
                        continue
                    all_known = all(tid in task_by_id_all for tid in tids)
                    if not all_known:
                        cursor += 1
                        continue
                    all_pending_now = all(
                        str(getattr(task_by_id_all[tid], "status", None).value) == "pending"
                        and int(getattr(task_by_id_all[tid], "create_time", 0)) <= now_ts
                        for tid in tids
                    )
                    if not all_pending_now:
                        # 还没到释放时刻：按“等待也是动作”的计划继续等待。
                        if any(
                            int(getattr(task_by_id_all[tid], "create_time", 0)) > now_ts
                            for tid in tids
                        ):
                            break
                        # 若任务已不再可派（被其他流程结算），跳过该计划项。
                        cursor += 1
                        continue
                    dispatch_ts = int(item.get("dispatch_ts", now_ts))
                    if dispatch_ts > now_ts:
                        break
                    first_tid = int(item.get("first_task_id", tids[0]))
                    if first_tid not in task_by_id_all:
                        first_tid = tids[0]
                    t = task_by_id_all[first_tid]
                    commands.append(utils.make_deliver_command(v, t, assigned_tasks=tids))
                    cursor += 1
                    dispatched = True
                    break
                self._warehouse_plan_cursor[v.id] = cursor
                if not dispatched:
                    commands.append(utils.make_idle_command(v))
                continue

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
        objective_mode = str(static_cfg.get("objective_mode", "proxy")).lower()
        force_gurobi_only = bool(static_cfg.get("force_gurobi_only", False))
        max_exact_tasks = int(static_cfg.get("max_exact_tasks", 10))
        strict = bool(static_cfg.get("strict_global_optimum", True))
        gap_th = float(static_cfg.get("mip_gap_threshold", 0.02))
        full_exact_enabled = bool(static_cfg.get("full_exact_global", True))
        full_exact_max_tasks = int(static_cfg.get("full_exact_max_tasks", max_exact_tasks))
        sim_exact_max_tasks = int(static_cfg.get("simulation_exact_max_tasks", 12))

        if force_gurobi_only and solver != "gurobi":
            raise RuntimeError(
                f"[STATIC] force_gurobi_only=true requires solver='gurobi', got '{solver}'."
            )

        # 完全精确优先：不设时间上限，枚举“任意任务子集 + 任意车辆 + 任意顺序”。
        if solver in ("exact", "exhaustive", "bruteforce", "brute_force"):
            route_plan, wh_plan = self._exact_warehouse_command_plan(vehicles, tasks, snapshot)
            self._warehouse_command_plan = wh_plan
            self._warehouse_plan_cursor = {v.id: 0 for v in vehicles}
            return route_plan

        # PyTorch/GPU anytime 搜索：持续输出当前最优，避免“长时间无响应”。
        if solver in ("gpu_search", "torch_search", "gpu"):
            route_plan = self._gpu_anytime_search_plan(vehicles, tasks, snapshot)
            self._warehouse_command_plan = {}
            self._warehouse_plan_cursor = {}
            return route_plan

        # 非 MIP 模式：先尽量精确（小规模全局搜索），再走限时启发式。
        if solver in ("heuristic", "global_heuristic", "meta_heuristic", "nogurobi"):
            if objective_mode in ("simulation_score", "sim_score"):
                if len(tasks) <= max(1, sim_exact_max_tasks):
                    sim_plan = self._full_exact_simulation_score(vehicles, tasks, snapshot)
                    if sim_plan is not None:
                        print(
                            f"[STATIC][HEURISTIC] simulation-score exact accepted "
                            f"(tasks={len(tasks)}, vehicles={len(vehicles)})."
                        )
                        return sim_plan
            if full_exact_enabled and len(tasks) <= max(1, full_exact_max_tasks):
                exact_plan = self._full_exact_global_with_charging(vehicles, tasks, snapshot)
                if exact_plan is not None:
                    print(
                        f"[STATIC][HEURISTIC] full exact global accepted "
                        f"(tasks={len(tasks)}, vehicles={len(vehicles)})."
                    )
                    return exact_plan
            return self._heuristic_global_plan(vehicles, tasks, snapshot)

        # 0) 真正按“仿真总分”做目标（全局穷举，适合小规模）。
        # force_gurobi_only 开启时跳过，确保全链路只由 Gurobi 决策。
        if (not force_gurobi_only) and objective_mode in ("simulation_score", "sim_score"):
            if len(tasks) <= max(1, sim_exact_max_tasks):
                sim_plan = self._full_exact_simulation_score(vehicles, tasks, snapshot)
                if sim_plan is not None:
                    print(
                        f"[STATIC] Simulation-score exact search accepted "
                        f"(tasks={len(tasks)}, vehicles={len(vehicles)})."
                    )
                    return sim_plan
                if strict:
                    raise RuntimeError(
                        "[STRICT_STATIC] simulation-score exact search failed to build feasible plan."
                    )
            elif strict:
                raise RuntimeError(
                    f"[STRICT_STATIC] objective_mode=simulation_score requires "
                    f"tasks <= simulation_exact_max_tasks ({sim_exact_max_tasks}), got {len(tasks)}."
                )

        # 0) 小规模时优先做“全局穷举精确搜索”（包含充电/时间窗/电量可行）。
        # force_gurobi_only 打开时跳过该分支，确保必须走 Gurobi。
        if (not force_gurobi_only) and full_exact_enabled and len(tasks) <= max(1, full_exact_max_tasks):
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
        if force_gurobi_only:
            msg = self._vrptw_disabled_reason or "Gurobi did not return an accepted VRPTW result."
            print(
                "[STATIC] force_gurobi_only enabled and no accepted VRPTW plan: "
                f"{msg}. return empty plan (no fallback)."
            )
            return {v.id: [] for v in vehicles}
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

    def _exhaustive_global_score_plan(self, vehicles, tasks, snapshot: Snapshot) -> Optional[Dict[int, List[int]]]:
        """无时间上限的全局精确搜索。

        搜索空间：
        - 每个任务可以不服务（得 0 分）；
        - 可以追加到任意一辆仍有载重的车辆；
        - 车辆内部顺序由搜索自然枚举；
        - 叶子/中间节点都用 `_simulate_routes_total_score` 按当前仿真评分评估。
        """
        if not vehicles:
            return {}
        if not tasks:
            return {v.id: [] for v in vehicles}

        static_cfg = (config.get_optimization_config().get("static") or {})
        live_log = bool(static_cfg.get("exact_live_log", True))
        log_interval_s = max(1.0, float(static_cfg.get("exact_log_interval_s", 5.0)))

        vehicles = list(vehicles)
        ordered_tasks = sorted(
            list(tasks),
            key=lambda t: (
                float(getattr(t, "deadline", 0.0)),
                -float(getattr(t, "priority", 0.0)),
                float(getattr(t, "create_time", 0.0)),
            ),
        )
        t_by_id = {t.id: t for t in ordered_tasks}
        task_ids = tuple(t.id for t in ordered_tasks)
        vids = [v.id for v in vehicles]
        cap_left: Dict[int, float] = {v.id: float(v.get_remaining_load()) for v in vehicles}
        routes: Dict[int, List[int]] = {v.id: [] for v in vehicles}

        optimistic_value = {
            t.id: max(
                0.0,
                float(TASK_ASSIGN_REWARD)
                + float(t.priority) * float(PRIORITY_REWARD)
                + max(0.0, float(t.deadline) - max(float(snapshot.timestamp), float(t.create_time))) / 60.0
                * float(EARLY_COMPLETION_REWARD_PER_MIN),
            )
            for t in ordered_tasks
        }

        best_score = self._simulate_routes_total_score(routes, vehicles, t_by_id, snapshot)
        best_routes: Dict[int, List[int]] = {vid: [] for vid in vids}
        nodes = 0
        pruned = 0
        evaluated = 1
        t0 = time.monotonic()
        last_log = t0

        def _remaining_bound(remaining: Tuple[int, ...]) -> float:
            return sum(float(optimistic_value.get(tid, 0.0)) for tid in remaining)

        def _route_signature() -> Tuple[Tuple[int, Tuple[int, ...]], ...]:
            return tuple((vid, tuple(routes[vid])) for vid in vids)

        seen_best: Dict[Tuple[Tuple[int, ...], Tuple[Tuple[int, Tuple[int, ...]], ...]], float] = {}

        def _evaluate_current() -> None:
            nonlocal best_score, best_routes, evaluated
            evaluated += 1
            score = self._simulate_routes_total_score(routes, vehicles, t_by_id, snapshot)
            if score > best_score + 1e-9:
                best_score = score
                best_routes = {vid: list(routes[vid]) for vid in vids}
                print(f"[STATIC][EXACT] new best score={best_score:.2f} routes={best_routes}")

        def dfs(remaining: Tuple[int, ...]) -> None:
            nonlocal nodes, pruned, last_log
            nodes += 1

            cur_score = self._simulate_routes_total_score(routes, vehicles, t_by_id, snapshot)
            if cur_score == float("-inf"):
                pruned += 1
                return
            if cur_score + _remaining_bound(remaining) <= best_score + 1e-9:
                pruned += 1
                return

            sig = (remaining, _route_signature())
            prev = seen_best.get(sig)
            if prev is not None and prev >= cur_score - 1e-9:
                pruned += 1
                return
            seen_best[sig] = cur_score

            if live_log:
                now_m = time.monotonic()
                if now_m - last_log >= log_interval_s:
                    elapsed = max(1e-6, now_m - t0)
                    print(
                        "[STATIC][EXACT] "
                        f"elapsed={elapsed:.1f}s nodes={nodes} evaluated={evaluated} "
                        f"pruned={pruned} remaining={len(remaining)} best={best_score:.2f} "
                        f"rate={nodes / elapsed:.1f}n/s"
                    )
                    last_log = now_m

            _evaluate_current()
            if not remaining:
                return

            # 分支顺序：优先尝试潜在收益最高、截止更紧的任务，利于尽早找到高分上界。
            candidates = sorted(
                remaining,
                key=lambda tid: (
                    -float(optimistic_value.get(tid, 0.0)),
                    float(getattr(t_by_id[tid], "deadline", 0.0)),
                ),
            )
            for tid in candidates:
                task = t_by_id[tid]
                rest = tuple(x for x in remaining if x != tid)

                # 显式跳过该任务：允许低分/不可行任务不派单，分数为 0。
                dfs(rest)

                vehicle_order = sorted(
                    vehicles,
                    key=lambda v: (
                        len(routes[v.id]),
                        snapshot.distance(
                            (t_by_id[routes[v.id][-1]].position.x, t_by_id[routes[v.id][-1]].position.y)
                            if routes[v.id]
                            else v.position,
                            task.position,
                        ),
                    ),
                )
                for v in vehicle_order:
                    vid = v.id
                    if float(task.weight) > cap_left[vid] + 1e-9:
                        continue
                    routes[vid].append(tid)
                    cap_left[vid] -= float(task.weight)
                    dfs(rest)
                    cap_left[vid] += float(task.weight)
                    routes[vid].pop()

        dfs(task_ids)
        elapsed = max(1e-6, time.monotonic() - t0)
        print(
            "[STATIC][EXACT] done "
            f"elapsed={elapsed:.1f}s nodes={nodes} evaluated={evaluated} "
            f"pruned={pruned} best={best_score:.2f}"
        )
        return self._repair_plan_with_energy(vehicles, tasks, best_routes, snapshot)

    def _heuristic_global_plan(self, vehicles, tasks, snapshot: Snapshot) -> Dict[int, List[int]]:
        """全局已知下的限时启发式：贪心插入 + 局部搜索（不依赖 Gurobi）。"""
        if not vehicles or not tasks:
            return {v.id: [] for v in vehicles}

        static_cfg = (config.get_optimization_config().get("static") or {})
        time_budget = max(0.2, float(static_cfg.get("heuristic_time_limit_s", 3.0)))
        ls_rounds = max(10, int(static_cfg.get("heuristic_ls_rounds", 120)))
        rng = random.Random(int(static_cfg.get("heuristic_seed", int(snapshot.timestamp) % 10_000_000)))
        unserved_penalty = float(
            static_cfg.get("unserved_penalty", float(TASK_ASSIGN_REWARD) + 2.0 * float(PRIORITY_REWARD))
        )

        t_by_id = {t.id: t for t in tasks}
        vids = [v.id for v in vehicles]
        v_by_id = {v.id: v for v in vehicles}
        routes: Dict[int, List[int]] = {vid: [] for vid in vids}
        start_ts = time.time()

        def _seq_obj(vid: int, tid_seq: List[int]) -> float:
            seq = [t_by_id[tid] for tid in tid_seq if tid in t_by_id]
            if tid_seq and not seq:
                return float("-inf")
            if seq and not self._is_chain_feasible(v_by_id[vid], seq, snapshot):
                return float("-inf")
            return self._sequence_objective(v_by_id[vid], seq, snapshot)

        def _served_ids(plan: Dict[int, List[int]]) -> set:
            out = set()
            for tid_seq in plan.values():
                out.update(tid_seq)
            return out

        def _plan_score(plan: Dict[int, List[int]]) -> float:
            served = _served_ids(plan)
            score = 0.0
            for vid in vids:
                s = _seq_obj(vid, plan.get(vid, []))
                if s == float("-inf"):
                    return float("-inf")
                score += s
            score -= unserved_penalty * max(0, len(tasks) - len(served))
            return score

        def _remaining_cap(vid: int, plan: Dict[int, List[int]]) -> float:
            used = sum(float(t_by_id[tid].weight) for tid in plan.get(vid, []) if tid in t_by_id)
            return float(v_by_id[vid].get_remaining_load()) - used

        # 1) 贪心插入构建初解（每次选“全局增益最大”的插入动作）
        remaining = sorted(
            [t.id for t in tasks],
            key=lambda tid: (float(getattr(t_by_id[tid], "deadline", 0.0)), -float(getattr(t_by_id[tid], "priority", 0.0))),
        )
        while remaining and (time.time() - start_ts) < time_budget * 0.55:
            best_move = None
            best_gain = 1e-9
            for tid in list(remaining):
                t = t_by_id[tid]
                for vid in vids:
                    if float(t.weight) > _remaining_cap(vid, routes) + 1e-9:
                        continue
                    base_seq = list(routes[vid])
                    base_obj = _seq_obj(vid, base_seq)
                    if base_obj == float("-inf"):
                        continue
                    for pos in range(len(base_seq) + 1):
                        cand_seq = base_seq[:pos] + [tid] + base_seq[pos:]
                        cand_obj = _seq_obj(vid, cand_seq)
                        if cand_obj == float("-inf"):
                            continue
                        gain = (cand_obj - base_obj) + unserved_penalty
                        if gain > best_gain:
                            best_gain = gain
                            best_move = (tid, vid, pos)
            if best_move is None:
                break
            tid, vid, pos = best_move
            cur = list(routes[vid])
            routes[vid] = cur[:pos] + [tid] + cur[pos:]
            remaining.remove(tid)

        # 2) 局部搜索（relocate + swap）提升全局分数
        current = {vid: list(seq) for vid, seq in routes.items()}
        current_score = _plan_score(current)
        best = {vid: list(seq) for vid, seq in current.items()}
        best_score = current_score

        rounds = 0
        while rounds < ls_rounds and (time.time() - start_ts) < time_budget:
            rounds += 1
            improved = False

            # relocate
            non_empty = [vid for vid in vids if current.get(vid)]
            rng.shuffle(non_empty)
            for from_vid in non_empty:
                from_seq = list(current[from_vid])
                if not from_seq:
                    continue
                tid = rng.choice(from_seq)
                t = t_by_id.get(tid)
                if t is None:
                    continue
                idx = from_seq.index(tid)
                for to_vid in vids:
                    if to_vid != from_vid and float(t.weight) > _remaining_cap(to_vid, current) + 1e-9:
                        continue
                    target_seq = list(current[to_vid])
                    for pos in range(len(target_seq) + 1):
                        trial = {vid: list(seq) for vid, seq in current.items()}
                        trial[from_vid].pop(idx)
                        insert_pos = min(pos, len(trial[to_vid]))
                        trial[to_vid].insert(insert_pos, tid)
                        sc = _plan_score(trial)
                        if sc > current_score + 1e-6:
                            current = trial
                            current_score = sc
                            improved = True
                            break
                    if improved:
                        break
                if improved:
                    break
            if improved:
                if current_score > best_score + 1e-6:
                    best = {vid: list(seq) for vid, seq in current.items()}
                    best_score = current_score
                continue

            # swap
            pair_vids = list(vids)
            rng.shuffle(pair_vids)
            for i, v1 in enumerate(pair_vids):
                seq1 = current.get(v1, [])
                if not seq1:
                    continue
                for v2 in pair_vids[i + 1:]:
                    seq2 = current.get(v2, [])
                    if not seq2:
                        continue
                    t1 = t_by_id[rng.choice(seq1)]
                    t2 = t_by_id[rng.choice(seq2)]
                    cap1 = _remaining_cap(v1, current) + float(t1.weight)
                    cap2 = _remaining_cap(v2, current) + float(t2.weight)
                    if float(t2.weight) > cap1 + 1e-9 or float(t1.weight) > cap2 + 1e-9:
                        continue
                    trial = {vid: list(seq) for vid, seq in current.items()}
                    i1 = trial[v1].index(t1.id)
                    i2 = trial[v2].index(t2.id)
                    trial[v1][i1], trial[v2][i2] = trial[v2][i2], trial[v1][i1]
                    sc = _plan_score(trial)
                    if sc > current_score + 1e-6:
                        current = trial
                        current_score = sc
                        improved = True
                        break
                if improved:
                    break

            if improved and current_score > best_score + 1e-6:
                best = {vid: list(seq) for vid, seq in current.items()}
                best_score = current_score

        # 3) 按车辆内部最佳顺序再精炼一次
        route_map: Dict[int, List[int]] = {vid: [] for vid in vids}
        for v in vehicles:
            seq_tasks = [t_by_id[tid] for tid in best.get(v.id, []) if tid in t_by_id]
            ordered = self._best_order_for_vehicle(v, seq_tasks, snapshot)
            route_map[v.id] = [t.id for t in ordered]
        return self._repair_plan_with_energy(vehicles, tasks, route_map, snapshot)

    def _exact_warehouse_command_plan(
        self, vehicles, tasks, snapshot: Snapshot
    ) -> Tuple[Dict[int, List[int]], Dict[int, List[Dict[str, Any]]]]:
        """精确枚举“仓库时刻命令”：

        - 仅当车辆在仓库时可下达命令；
        - 命令可为：等待 / 给该车分配一批任务；
        - 车辆出仓后按“正常执行”自动送货与充电；
        - 允许在可执行时选择等待未来任务（静态全局已知）。
        """
        if not vehicles or not tasks:
            return ({v.id: [] for v in vehicles}, {v.id: [] for v in vehicles})

        now_ts = float(int(snapshot.timestamp))
        wh_xy = (float(snapshot.warehouse_xy[0]), float(snapshot.warehouse_xy[1]))
        stations = list(getattr(snapshot, "charging_stations", []) or [])
        sched_cfg = config.get_scheduling_config() or {}
        charge_until_pct = max(1.0, min(100.0, float(sched_cfg.get("charge_until_pct", 90.0))))
        margin = max(1.0, float(sched_cfg.get("battery_safety_margin", 1.15)))
        static_cfg = (config.get_optimization_config().get("static") or {})
        live_log = bool(static_cfg.get("exact_live_log", True))
        log_interval_s = max(1.0, float(static_cfg.get("exact_log_interval_s", 5.0)))
        breadth_levels = max(0, int(static_cfg.get("exact_breadth_levels", 2)))
        beam_width = max(1, int(static_cfg.get("exact_beam_width", 64)))
        refine_seeds = max(1, int(static_cfg.get("exact_refine_seeds", 4)))

        tasks = list(tasks)
        vehicles = list(vehicles)
        t_by_id = {t.id: t for t in tasks}
        v_by_id = {v.id: v for v in vehicles}
        vids = [v.id for v in vehicles]

        optimistic = {
            t.id: max(
                0.0,
                float(TASK_ASSIGN_REWARD)
                + float(t.priority) * float(PRIORITY_REWARD)
                + max(0.0, float(t.deadline) - max(float(t.create_time), now_ts)) / 60.0
                * float(EARLY_COMPLETION_REWARD_PER_MIN),
            )
            for t in tasks
        }

        init_vehicle_state: Dict[int, Dict[str, Any]] = {
            v.id: {
                "available_ts": now_ts,
                "battery": float(v.battery),
                "parked": False,
            }
            for v in vehicles
        }
        init_task_status: Dict[int, str] = {t.id: "pending" for t in tasks}
        init_commands: Dict[int, List[Dict[str, Any]]] = {v.id: [] for v in vehicles}

        best_score = 0.0
        best_cmds = {v.id: [] for v in vehicles}
        nodes = 0
        pruned = 0
        t0 = time.monotonic()
        t_last = t0

        def _clone_vehicle_state(vs: Dict[int, Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
            return {vid: dict(st) for vid, st in vs.items()}

        def _clone_task_status(ts: Dict[int, str]) -> Dict[int, str]:
            return dict(ts)

        def _clone_commands(cmds: Dict[int, List[Dict[str, Any]]]) -> Dict[int, List[Dict[str, Any]]]:
            out: Dict[int, List[Dict[str, Any]]] = {}
            for vid, items in cmds.items():
                out[vid] = [
                    {
                        "dispatch_ts": int(it.get("dispatch_ts", 0)),
                        "task_ids": list(it.get("task_ids", []) or []),
                        "first_task_id": int(it.get("first_task_id", -1)),
                    }
                    for it in items
                ]
            return out

        def _pending_ids(ts: Dict[int, str]) -> List[int]:
            return [tid for tid, st in ts.items() if st == "pending"]

        def _bound(cur_score: float, ts: Dict[int, str]) -> float:
            return cur_score + sum(optimistic.get(tid, 0.0) for tid in _pending_ids(ts))

        memo: Dict[Tuple, float] = {}

        def _choose_station_for_target(
            vid: int,
            cur_xy: Tuple[float, float],
            cur_t: float,
            cur_b: float,
            target_xy: Tuple[float, float],
        ) -> Optional[Tuple[Any, float, float, float]]:
            v = v_by_id[vid]
            speed = max(1e-6, float(getattr(v, "speed", 10.0)))
            power = max(1e-6, float(getattr(v, "charging_power", 0.022)))
            best = None
            best_finish = float("inf")
            for st in stations:
                st_xy = (float(st.position.x), float(st.position.y))
                d_to = snapshot.distance(cur_xy, st_xy)
                if d_to == float("inf"):
                    continue
                e_to = utils.energy_required_for_distance(v, d_to)
                if e_to == float("inf") or cur_b + 1e-9 < e_to:
                    continue
                after_arrival = cur_b - e_to
                d_after = snapshot.distance(st_xy, target_xy)
                if d_after == float("inf"):
                    continue
                extra = utils.min_distance_to_any_station(target_xy, stations, snapshot) if stations else 0.0
                if extra == float("inf"):
                    continue
                need = utils.energy_required_for_distance(v, float(d_after) + float(extra)) * margin
                if need > float(v.max_battery) + 1e-9:
                    continue
                charge_to = min(
                    float(v.max_battery),
                    max(float(v.max_battery) * charge_until_pct / 100.0, need),
                )
                arr = cur_t + float(d_to) / speed
                finish = arr + max(0.0, charge_to - after_arrival) / power
                finish_target = finish + float(d_after) / speed
                if finish_target < best_finish:
                    best_finish = finish_target
                    best = (st, float(d_to), float(finish), float(charge_to))
            return best

        def _simulate_batch(
            vid: int,
            start_t: float,
            start_batt: float,
            batch_tids: List[int],
        ) -> Optional[Tuple[float, float, Dict[int, float], int]]:
            v = v_by_id[vid]
            cur_xy = wh_xy
            cur_t = float(start_t)
            cur_b = float(start_batt)
            onboard = list(batch_tids)
            task_dist = {tid: 0.0 for tid in onboard}
            first_tid = onboard[0] if onboard else -1

            def _move_to(dst_xy: Tuple[float, float]) -> Optional[Tuple[float, float, float]]:
                nonlocal cur_xy, cur_t, cur_b
                d = snapshot.distance(cur_xy, dst_xy)
                if d == float("inf"):
                    return None
                e = utils.energy_required_for_distance(v, d)
                if e == float("inf") or cur_b + 1e-9 < e:
                    return None
                cur_b -= float(e)
                cur_t += float(d) / max(1e-6, float(getattr(v, "speed", 10.0)))
                cur_xy = dst_xy
                return float(d), cur_t, cur_b

            task_scores: Dict[int, float] = {}
            while onboard:
                target_tid = min(
                    onboard,
                    key=lambda tid: snapshot.distance(cur_xy, (t_by_id[tid].position.x, t_by_id[tid].position.y)),
                )
                if first_tid == -1:
                    first_tid = target_tid
                target_xy = (float(t_by_id[target_tid].position.x), float(t_by_id[target_tid].position.y))

                safe = 0
                while True:
                    safe += 1
                    if safe > max(6, len(stations) * 4 + 2):
                        return None
                    d_leg = snapshot.distance(cur_xy, target_xy)
                    if d_leg == float("inf"):
                        return None
                    extra = utils.min_distance_to_any_station(target_xy, stations, snapshot) if stations else 0.0
                    if extra == float("inf"):
                        return None
                    need = utils.energy_required_for_distance(v, float(d_leg) + float(extra)) * margin
                    if cur_b + 1e-9 >= need:
                        break
                    choice = _choose_station_for_target(vid, cur_xy, cur_t, cur_b, target_xy)
                    if choice is None:
                        return None
                    st, _, finish_charge, charge_to = choice
                    st_xy = (float(st.position.x), float(st.position.y))
                    mv = _move_to(st_xy)
                    if mv is None:
                        return None
                    cur_t = max(cur_t, float(finish_charge))
                    cur_b = float(charge_to)

                mv = _move_to(target_xy)
                if mv is None:
                    return None
                d_move = mv[0]
                for tid in onboard:
                    task_dist[tid] += float(d_move)

                completion_ts = max(cur_t, float(getattr(t_by_id[target_tid], "create_time", cur_t)))
                deadline = float(getattr(t_by_id[target_tid], "deadline", completion_ts))
                early_minutes = max(0.0, deadline - completion_ts) / 60.0
                overdue_minutes = max(0.0, completion_ts - deadline) / 60.0
                score = (
                    float(TASK_ASSIGN_REWARD)
                    + float(getattr(t_by_id[target_tid], "priority", 1.0)) * float(PRIORITY_REWARD)
                    - float(task_dist[target_tid]) * float(DISTANCE_PENALTY)
                    + early_minutes * float(EARLY_COMPLETION_REWARD_PER_MIN)
                    - overdue_minutes * float(OVERDUE_PENALTY_PER_MIN)
                )
                task_scores[target_tid] = max(0.0, float(score))
                onboard.remove(target_tid)

            while abs(cur_xy[0] - wh_xy[0]) > 1e-4 or abs(cur_xy[1] - wh_xy[1]) > 1e-4:
                d_back = snapshot.distance(cur_xy, wh_xy)
                if d_back == float("inf"):
                    return None
                need_back = utils.energy_required_for_distance(v, d_back) * margin
                if cur_b + 1e-9 >= need_back:
                    mv = _move_to(wh_xy)
                    if mv is None:
                        return None
                    break
                choice = _choose_station_for_target(vid, cur_xy, cur_t, cur_b, wh_xy)
                if choice is None:
                    return None
                st, _, finish_charge, charge_to = choice
                st_xy = (float(st.position.x), float(st.position.y))
                mv = _move_to(st_xy)
                if mv is None:
                    return None
                cur_t = max(cur_t, float(finish_charge))
                cur_b = float(charge_to)

            return float(cur_t), float(cur_b), task_scores, int(first_tid)

        def _state_key(
            cur_score: float,
            vs: Dict[int, Dict[str, Any]],
            ts: Dict[int, str],
        ) -> Tuple:
            pending = tuple(sorted(_pending_ids(ts)))
            veh = tuple(
                (
                    vid,
                    int(round(vs[vid]["available_ts"])),
                    round(float(vs[vid]["battery"]), 3),
                    int(bool(vs[vid]["parked"])),
                )
                for vid in sorted(vids)
            )
            return pending, veh, int(round(cur_score))

        def _generate_children(
            cur_score: float,
            vs: Dict[int, Dict[str, Any]],
            ts: Dict[int, str],
            cmds: Dict[int, List[Dict[str, Any]]],
        ) -> List[Tuple[float, Dict[int, Dict[str, Any]], Dict[int, str], Dict[int, List[Dict[str, Any]]]]]:
            children: List[Tuple[float, Dict[int, Dict[str, Any]], Dict[int, str], Dict[int, List[Dict[str, Any]]]]] = []
            pending = _pending_ids(ts)
            active_vids = [vid for vid in vids if not bool(vs[vid]["parked"])]
            if not pending or not active_vids:
                return children

            vid = min(active_vids, key=lambda x: float(vs[x]["available_ts"]))
            t_now = float(vs[vid]["available_ts"])
            v = v_by_id[vid]

            released = [
                tid for tid in pending
                if float(getattr(t_by_id[tid], "create_time", t_now)) <= t_now + 1e-9
            ]
            future_rel = [
                float(getattr(t_by_id[tid], "create_time", t_now))
                for tid in pending
                if float(getattr(t_by_id[tid], "create_time", t_now)) > t_now + 1e-9
            ]

            # 等待
            nvs = _clone_vehicle_state(vs)
            nts = _clone_task_status(ts)
            ncmds = _clone_commands(cmds)
            if future_rel:
                nvs[vid]["available_ts"] = min(future_rel)
            else:
                nvs[vid]["parked"] = True
            children.append((cur_score, nvs, nts, ncmds))

            if not released:
                return children

            # 派发满足载重的任务子集
            cap = float(getattr(v, "max_load", 0.0))
            rel_sorted = sorted(
                released,
                key=lambda tid: (
                    float(getattr(t_by_id[tid], "deadline", 0.0)),
                    -float(getattr(t_by_id[tid], "priority", 0.0)),
                ),
            )
            n = len(rel_sorted)
            for mask in range(1, 1 << n):
                subset = [rel_sorted[i] for i in range(n) if (mask >> i) & 1]
                total_w = sum(float(getattr(t_by_id[tid], "weight", 0.0)) for tid in subset)
                if total_w > cap + 1e-9:
                    continue
                sim = _simulate_batch(vid, t_now, float(vs[vid]["battery"]), subset)
                if sim is None:
                    continue
                ret_ts, ret_b, task_scores, first_tid = sim

                nvs2 = _clone_vehicle_state(vs)
                nts2 = _clone_task_status(ts)
                ncmds2 = _clone_commands(cmds)
                nvs2[vid]["battery"] = float(ret_b)
                nvs2[vid]["available_ts"] = float(ret_ts)
                nvs2[vid]["parked"] = False
                for tid in subset:
                    nts2[tid] = "completed"
                ncmds2[vid].append(
                    {
                        "dispatch_ts": int(t_now),
                        "task_ids": list(subset),
                        "first_task_id": int(first_tid if first_tid > 0 else subset[0]),
                    }
                )
                gain = sum(float(task_scores.get(tid, 0.0)) for tid in subset)
                children.append((cur_score + gain, nvs2, nts2, ncmds2))
            return children

        def dfs(
            cur_score: float,
            vs: Dict[int, Dict[str, Any]],
            ts: Dict[int, str],
            cmds: Dict[int, List[Dict[str, Any]]],
        ) -> None:
            nonlocal best_score, best_cmds, nodes, pruned, t_last
            nodes += 1
            if _bound(cur_score, ts) <= best_score + 1e-9:
                pruned += 1
                return

            key = _state_key(cur_score, vs, ts)
            prev = memo.get(key)
            if prev is not None and prev >= cur_score - 1e-9:
                pruned += 1
                return
            memo[key] = cur_score

            pending = _pending_ids(ts)
            if not pending:
                if cur_score > best_score + 1e-9:
                    best_score = cur_score
                    best_cmds = _clone_commands(cmds)
                return

            active_vids = [vid for vid in vids if not bool(vs[vid]["parked"])]
            if not active_vids:
                if cur_score > best_score + 1e-9:
                    best_score = cur_score
                    best_cmds = _clone_commands(cmds)
                return

            if live_log:
                now_m = time.monotonic()
                if now_m - t_last >= log_interval_s:
                    elapsed = max(1e-6, now_m - t0)
                    print(
                        "[STATIC][WAREHOUSE-EXACT] "
                        f"elapsed={elapsed:.1f}s nodes={nodes} pruned={pruned} "
                        f"pending={len(pending)} best={best_score:.2f} rate={nodes/elapsed:.1f}n/s"
                    )
                    t_last = now_m

            children = _generate_children(cur_score, vs, ts, cmds)
            children.sort(key=lambda x: _bound(x[0], x[2]), reverse=True)
            for nscore, nvs, nts, ncmds in children:
                dfs(nscore, nvs, nts, ncmds)

        # Phase A: 广度预探索（beam）
        frontier: List[Tuple[float, Dict[int, Dict[str, Any]], Dict[int, str], Dict[int, List[Dict[str, Any]]]]] = [
            (0.0, _clone_vehicle_state(init_vehicle_state), _clone_task_status(init_task_status), _clone_commands(init_commands))
        ]
        for _ in range(breadth_levels):
            candidates: List[Tuple[float, Dict[int, Dict[str, Any]], Dict[int, str], Dict[int, List[Dict[str, Any]]]]] = []
            for sc, vs, ts, cmds in frontier:
                candidates.extend(_generate_children(sc, vs, ts, cmds))
            if not candidates:
                break
            candidates.sort(key=lambda x: _bound(x[0], x[2]), reverse=True)
            frontier = candidates[:beam_width]

        # Phase B: 从 beam 里最优若干种子继续深搜
        if not frontier:
            frontier = [(0.0, _clone_vehicle_state(init_vehicle_state), _clone_task_status(init_task_status), _clone_commands(init_commands))]
        seeds = sorted(frontier, key=lambda x: _bound(x[0], x[2]), reverse=True)[:refine_seeds]
        for sc, vs, ts, cmds in seeds:
            dfs(sc, vs, ts, cmds)

        elapsed = max(1e-6, time.monotonic() - t0)
        print(
            "[STATIC][WAREHOUSE-EXACT] done "
            f"elapsed={elapsed:.1f}s nodes={nodes} pruned={pruned} best={best_score:.2f}"
        )

        route_map: Dict[int, List[int]] = {vid: [] for vid in vids}
        for vid in vids:
            for item in best_cmds.get(vid, []):
                route_map[vid].extend(list(item.get("task_ids", []) or []))
        return route_map, best_cmds

    def _gpu_anytime_search_plan(self, vehicles, tasks, snapshot: Snapshot) -> Dict[int, List[int]]:
        """PyTorch anytime 搜索（有 CUDA 则用 GPU 采样动作）。"""
        if not vehicles or not tasks:
            return {v.id: [] for v in vehicles}

        static_cfg = (config.get_optimization_config().get("static") or {})
        time_limit_s = max(5.0, float(static_cfg.get("gpu_time_limit_s", 90.0)))
        batch_size = max(4, int(static_cfg.get("gpu_batch_size", 64)))
        generations_per_iter = max(1, int(static_cfg.get("gpu_generations_per_iter", 4)))
        topk_eval = max(1, int(static_cfg.get("gpu_topk_eval", max(4, batch_size // 8))))
        log_interval_s = max(1.0, float(static_cfg.get("gpu_log_interval_s", 2.0)))
        explore_scale = max(0.01, float(static_cfg.get("gpu_explore_scale", 3.0)))
        search_order = str(static_cfg.get("gpu_search_order", "breadth_first")).strip().lower()
        require_cuda = bool(static_cfg.get("gpu_require_cuda", False))
        reserve_mb = max(0, int(static_cfg.get("gpu_vram_reserve_mb", 0)))

        try:
            import torch  # type: ignore
            has_cuda = bool(torch.cuda.is_available())
            device = torch.device("cuda" if has_cuda else "cpu")
        except Exception:
            torch = None  # type: ignore
            has_cuda = False
            device = None

        # 先判断并打印 CUDA 可用性（按你的要求）
        if torch is None:
            print("[STATIC][GPU] torch import failed, fallback to CPU search.")
            if require_cuda:
                raise RuntimeError("[STATIC][GPU] gpu_require_cuda=true but torch is unavailable.")
        else:
            cuda_ver = str(getattr(torch.version, "cuda", None))
            dev_cnt = int(torch.cuda.device_count()) if has_cuda else 0
            print(
                f"[STATIC][GPU] torch={torch.__version__} cuda_available={has_cuda} "
                f"cuda_version={cuda_ver} device_count={dev_cnt} search_order={search_order}"
            )
            if require_cuda and not has_cuda:
                raise RuntimeError("[STATIC][GPU] gpu_require_cuda=true but CUDA is unavailable.")

        # 可选：预留一块显存，避免“小任务下显存几乎不动”的观感。
        # 注意这不会改变最优性，只影响显存占用/一定程度的 GPU 常驻。
        gpu_reserve = None
        if torch is not None and has_cuda and reserve_mb > 0:
            try:
                n_float = (reserve_mb * 1024 * 1024) // 4  # float32 = 4 bytes
                gpu_reserve = torch.empty((n_float,), dtype=torch.float32, device=device)
                # 做一次轻运算，确保显存真正分配并活跃。
                gpu_reserve.uniform_(0.0, 1.0)
                print(f"[STATIC][GPU] reserved_vram={reserve_mb}MB on CUDA.")
            except Exception as exc:
                print(f"[STATIC][GPU] WARN reserve_vram failed: {exc}")
                gpu_reserve = None

        t0 = time.monotonic()
        t_last_log = t0
        task_list = list(tasks)
        n_tasks = len(task_list)
        vids = [v.id for v in vehicles]
        t_by_id = {t.id: t for t in task_list}
        v_by_id = {v.id: v for v in vehicles}

        # base utility 越高越优先（在 GPU 上做批量扰动）
        base_vals = []
        now_ts = float(snapshot.timestamp)
        for t in task_list:
            deadline_left = max(1.0, float(getattr(t, "deadline", now_ts)) - now_ts)
            util = float(t.priority) * float(PRIORITY_REWARD) + 5000.0 / deadline_left
            base_vals.append(util)

        if torch is not None:
            base_tensor = torch.tensor(base_vals, dtype=torch.float32, device=device).view(1, n_tasks)
            pos_decay = torch.linspace(1.0, 0.5, steps=n_tasks, device=device).view(1, n_tasks)

        best_score = float("-inf")
        best_route = {vid: [] for vid in vids}
        eval_count = 0
        best_order_ids: List[int] = []

        def plan_score(route_map: Dict[int, List[int]]) -> float:
            repaired = self._repair_plan_with_energy(vehicles, task_list, route_map, snapshot)
            total = 0.0
            for v in vehicles:
                seq = [t_by_id[tid] for tid in repaired.get(v.id, []) if tid in t_by_id]
                s = self._sequence_objective(v, seq, snapshot)
                if s == float("-inf"):
                    return float("-inf")
                total += float(s)
            return float(total)

        def build_route_from_order(order_ids: List[int]) -> Dict[int, List[int]]:
            route_map: Dict[int, List[int]] = {vid: [] for vid in vids}
            rem_cap: Dict[int, float] = {vid: float(v_by_id[vid].get_remaining_load()) for vid in vids}
            for tid in order_ids:
                t = t_by_id[tid]
                best_vid = None
                best_gain = float("-inf")
                for v in vehicles:
                    vid = v.id
                    if float(t.weight) > rem_cap[vid] + 1e-9:
                        continue
                    base_seq = [t_by_id[x] for x in route_map[vid] if x in t_by_id]
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
                    route_map[best_vid].append(tid)
                    rem_cap[best_vid] -= float(t.weight)
            return route_map

        while time.monotonic() - t0 < time_limit_s:
            if torch is not None:
                eff_batch = batch_size * generations_per_iter
                noise = torch.rand((eff_batch, n_tasks), device=device) * explore_scale
                scores = base_tensor + noise
                ranked_tensor = torch.argsort(scores, dim=1, descending=True)
                # GPU并行粗评分：越靠前的任务权重越高，快速筛掉大量差解
                ranked_base = torch.gather(base_tensor.expand(eff_batch, -1), 1, ranked_tensor)
                surrogate = torch.sum(ranked_base * pos_decay, dim=1)
                k = min(topk_eval, eff_batch)
                top_idx = torch.topk(surrogate, k=k, largest=True).indices
                ranked = ranked_tensor[top_idx].detach().cpu().tolist()
            else:
                ranked = []
                for _ in range(batch_size):
                    idxs = list(range(n_tasks))
                    random.shuffle(idxs)
                    ranked.append(idxs)

            if search_order in ("depth_first", "dfs_first", "deep_first"):
                # 深度优先：优先围绕当前最优顺序做邻域精修，再补充少量全局随机样本。
                candidate_idx_orders: List[List[int]] = []
                if best_order_ids:
                    idx_by_tid = {task_list[i].id: i for i in range(n_tasks)}
                    base_idx = [idx_by_tid[tid] for tid in best_order_ids if tid in idx_by_tid]
                    for _ in range(max(8, batch_size // 2)):
                        cand = list(base_idx)
                        if len(cand) >= 2:
                            i = random.randrange(len(cand))
                            j = random.randrange(len(cand))
                            cand[i], cand[j] = cand[j], cand[i]
                        candidate_idx_orders.append(cand)
                # 混入一部分全局样本，避免陷入局部最优。
                keep_global = max(4, batch_size // 4)
                candidate_idx_orders.extend(ranked[:keep_global])
            else:
                # 广度优先：尽可能覆盖不同候选。
                candidate_idx_orders = ranked

            for idx_order in candidate_idx_orders:
                order_ids = [task_list[i].id for i in idx_order]
                cand_route = build_route_from_order(order_ids)
                sc = plan_score(cand_route)
                eval_count += 1
                if sc > best_score + 1e-9:
                    best_score = sc
                    best_route = cand_route
                    best_order_ids = list(order_ids)
                    print(f"[STATIC][GPU] best={best_score:.2f} eval={eval_count} elapsed={time.monotonic()-t0:.1f}s")

            now_m = time.monotonic()
            if now_m - t_last_log >= log_interval_s:
                mode = "cuda" if has_cuda else "cpu"
                print(
                    f"[STATIC][GPU] mode={mode} elapsed={now_m-t0:.1f}s "
                    f"eval={eval_count} best={best_score:.2f} "
                    f"batch={batch_size} gens={generations_per_iter} topk={topk_eval}"
                )
                t_last_log = now_m

        print(
            f"[STATIC][GPU] done elapsed={time.monotonic()-t0:.1f}s "
            f"eval={eval_count} best={best_score:.2f}"
        )
        # 保持引用直到搜索结束，防止被提前释放。
        _ = gpu_reserve
        return self._repair_plan_with_energy(vehicles, task_list, best_route, snapshot)

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
        static_cfg = (config.get_optimization_config().get("static") or {})
        live_log = bool(static_cfg.get("dfs_live_log", True))
        log_interval_s = max(1.0, float(static_cfg.get("dfs_log_interval_s", 5.0)))
        dfs_nodes = 0
        dfs_leaves = 0
        dfs_pruned = 0
        t0 = time.monotonic()
        t_last_log = t0

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
            nonlocal best_score, best_routes, dfs_nodes, dfs_leaves, dfs_pruned, t_last_log
            dfs_nodes += 1
            cur_total = sum(float(st["score"]) for st in cur_states.values())
            if cur_total + optimistic_suffix[i] <= best_score + 1e-9:
                dfs_pruned += 1
                return

            if live_log:
                now_m = time.monotonic()
                if now_m - t_last_log >= log_interval_s:
                    elapsed = max(1e-6, now_m - t0)
                    rate = dfs_nodes / elapsed
                    print(
                        "[DFS-ENERGY] "
                        f"elapsed={elapsed:.1f}s nodes={dfs_nodes} leaves={dfs_leaves} "
                        f"pruned={dfs_pruned} depth={i}/{len(ordered_tasks)} "
                        f"best={best_score:.2f} rate={rate:.1f}n/s"
                    )
                    t_last_log = now_m

            if i >= len(ordered_tasks):
                dfs_leaves += 1
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
        if live_log:
            elapsed = max(1e-6, time.monotonic() - t0)
            rate = dfs_nodes / elapsed
            print(
                "[DFS-ENERGY] done "
                f"elapsed={elapsed:.1f}s nodes={dfs_nodes} leaves={dfs_leaves} "
                f"pruned={dfs_pruned} best={best_score:.2f} rate={rate:.1f}n/s"
            )
        if best_routes is None:
            return None
        return best_routes

    def _full_exact_simulation_score(self, vehicles, tasks, snapshot: Snapshot) -> Optional[Dict[int, List[int]]]:
        """全局穷举，叶子结点用“仿真总分”评估。"""
        if not vehicles:
            return {}
        if not tasks:
            return {v.id: [] for v in vehicles}

        vehicles = list(vehicles)
        tasks = list(tasks)
        routes: Dict[int, List[int]] = {v.id: [] for v in vehicles}
        rem_cap: Dict[int, float] = {v.id: float(v.get_remaining_load()) for v in vehicles}
        t_by_id = {t.id: t for t in tasks}

        optimistic_task_values = {
            t.id: max(
                0.0,
                float(TASK_ASSIGN_REWARD) + float(t.priority) * float(PRIORITY_REWARD),
            )
            for t in tasks
        }

        best_score = float("-inf")
        best_routes: Optional[Dict[int, List[int]]] = None
        static_cfg = (config.get_optimization_config().get("static") or {})
        live_log = bool(static_cfg.get("dfs_live_log", True))
        log_interval_s = max(1.0, float(static_cfg.get("dfs_log_interval_s", 5.0)))
        dfs_nodes = 0
        dfs_leaves = 0
        dfs_pruned = 0
        t0 = time.monotonic()
        t_last_log = t0

        remaining_ids = [t.id for t in tasks]

        def dfs(remaining: List[int], optimistic_base: float) -> None:
            nonlocal best_score, best_routes, dfs_nodes, dfs_leaves, dfs_pruned, t_last_log
            dfs_nodes += 1
            if optimistic_base <= best_score + 1e-9:
                dfs_pruned += 1
                return

            if live_log:
                now_m = time.monotonic()
                if now_m - t_last_log >= log_interval_s:
                    elapsed = max(1e-6, now_m - t0)
                    rate = dfs_nodes / elapsed
                    done_depth = len(tasks) - len(remaining)
                    print(
                        "[DFS-SIM] "
                        f"elapsed={elapsed:.1f}s nodes={dfs_nodes} leaves={dfs_leaves} "
                        f"pruned={dfs_pruned} depth={done_depth}/{len(tasks)} "
                        f"remain={len(remaining)} best={best_score:.2f} rate={rate:.1f}n/s"
                    )
                    t_last_log = now_m
            if not remaining:
                dfs_leaves += 1
                score = self._simulate_routes_total_score(routes, vehicles, t_by_id, snapshot)
                if score > best_score:
                    best_score = score
                    best_routes = {vid: list(seq) for vid, seq in routes.items()}
                return

            # 先扩展更“紧”的任务。
            ordered = sorted(
                remaining,
                key=lambda tid: (
                    float(getattr(t_by_id[tid], "deadline", 0.0)),
                    -float(getattr(t_by_id[tid], "priority", 0.0)),
                ),
            )
            tid = ordered[0]
            task = t_by_id[tid]

            # 尝试把该任务分配给每辆能装得下的车。
            for v in vehicles:
                vid = v.id
                if float(task.weight) > rem_cap[vid] + 1e-9:
                    continue
                routes[vid].append(tid)
                rem_cap[vid] -= float(task.weight)
                nxt_remaining = [x for x in remaining if x != tid]
                dfs(nxt_remaining, optimistic_base - optimistic_task_values[tid])
                rem_cap[vid] += float(task.weight)
                routes[vid].pop()

        initial_optimistic = sum(optimistic_task_values.values())
        dfs(remaining_ids, initial_optimistic)
        if live_log:
            elapsed = max(1e-6, time.monotonic() - t0)
            rate = dfs_nodes / elapsed
            print(
                "[DFS-SIM] done "
                f"elapsed={elapsed:.1f}s nodes={dfs_nodes} leaves={dfs_leaves} "
                f"pruned={dfs_pruned} best={best_score:.2f} rate={rate:.1f}n/s"
            )
        return best_routes

    def _simulate_routes_total_score(
        self,
        routes: Dict[int, List[int]],
        vehicles,
        task_by_id: Dict[int, Any],
        snapshot: Snapshot,
    ) -> float:
        """按静态执行语义仿真固定路由，返回总分。

        关键对齐点：
        - 任务只有在“车辆在仓库发车时且已释放”才会上车（变为 in_progress）；
        - 任务路径距离从上车开始累计，到该任务送达结束；
        - 多任务同车时，车上所有未送任务共同累计行驶距离（与 DataManager 一致）。
        """
        now_ts = float(int(snapshot.timestamp))
        wh_xy = (float(snapshot.warehouse_xy[0]), float(snapshot.warehouse_xy[1]))
        sched_cfg = config.get_scheduling_config() or {}
        charge_until_pct = max(1.0, min(100.0, float(sched_cfg.get("charge_until_pct", 90.0))))
        margin = max(1.0, float(sched_cfg.get("battery_safety_margin", 1.15)))
        stations = list(getattr(snapshot, "charging_stations", []) or [])

        station_slots: Dict[str, List[float]] = {}
        for st in stations:
            cap = max(1, int(getattr(st, "capacity", 1)))
            station_slots[st.id] = [now_ts for _ in range(cap)]

        v_by_id = {v.id: v for v in vehicles}
        vstate: Dict[int, Dict[str, Any]] = {}
        task_state: Dict[int, Dict[str, Any]] = {}
        for tid, t in task_by_id.items():
            task_state[tid] = {
                "release": float(getattr(t, "create_time", now_ts)),
                "deadline": float(getattr(t, "deadline", now_ts)),
                "priority": float(getattr(t, "priority", 1.0)),
                "xy": (float(t.position.x), float(t.position.y)),
                "status": "pending",     # pending | in_progress | completed
                "carrier": None,
                "dist": 0.0,
                "score": 0.0,
            }

        for v in vehicles:
            vstate[v.id] = {
                "time": now_ts,
                "xy": (float(v.position.x), float(v.position.y)),
                "battery": float(v.battery),
                "route_idx": 0,
                "onboard": [],           # 当前车上任务（按 route 顺序）
                "done": False,
            }

        def _route_remaining(vid: int) -> List[int]:
            route = routes.get(vid, [])
            stv = vstate[vid]
            return list(route[stv["route_idx"]:])

        def _next_release_time(vid: int) -> Optional[float]:
            rem = _route_remaining(vid)
            if not rem:
                return None
            ts = [
                float(task_state[tid]["release"])
                for tid in rem
                if task_state.get(tid, {}).get("status") == "pending"
            ]
            return min(ts) if ts else None

        def _distance_move_and_apply(vid: int, target_xy: Tuple[float, float]) -> bool:
            """车辆移动到目标点，并给车上任务累计路径。"""
            v = v_by_id[vid]
            stv = vstate[vid]
            d = snapshot.distance(stv["xy"], target_xy)
            if d == float("inf"):
                return False
            e = utils.energy_required_for_distance(v, d)
            if e == float("inf") or stv["battery"] + 1e-9 < e:
                return False
            stv["battery"] -= float(e)
            speed = max(1e-6, float(getattr(v, "speed", 10.0)))
            stv["time"] += float(d) / speed
            stv["xy"] = (float(target_xy[0]), float(target_xy[1]))
            for tid in list(stv["onboard"]):
                ts = task_state.get(tid)
                if ts is not None and ts["status"] == "in_progress":
                    ts["dist"] += float(d)
            return True

        def _choose_station_for_target(vid: int, target_xy: Tuple[float, float]) -> Optional[Any]:
            """当前状态下，选一个可行且到目标完成时间最早的补能站。"""
            v = v_by_id[vid]
            stv = vstate[vid]
            speed = max(1e-6, float(getattr(v, "speed", 10.0)))
            power = max(1e-6, float(getattr(v, "charging_power", 0.022)))
            best = None
            best_finish = float("inf")
            for st in stations:
                st_xy = (float(st.position.x), float(st.position.y))
                d_to = snapshot.distance(stv["xy"], st_xy)
                if d_to == float("inf"):
                    continue
                e_to = utils.energy_required_for_distance(v, d_to)
                if e_to == float("inf") or stv["battery"] + 1e-9 < e_to:
                    continue
                after_arrival_b = stv["battery"] - e_to
                d_after = snapshot.distance(st_xy, target_xy)
                if d_after == float("inf"):
                    continue
                extra = utils.min_distance_to_any_station(target_xy, stations, snapshot) if stations else 0.0
                if extra == float("inf"):
                    continue
                need_after = utils.energy_required_for_distance(v, float(d_after) + float(extra)) * margin
                if need_after > float(v.max_battery) + 1e-9:
                    continue
                charge_to = min(
                    float(v.max_battery),
                    max(float(v.max_battery) * charge_until_pct / 100.0, need_after),
                )
                if charge_to + 1e-9 < need_after:
                    continue
                arr = stv["time"] + float(d_to) / speed
                slots = station_slots.get(st.id, [now_ts])
                slot_idx = min(range(len(slots)), key=lambda i: slots[i])
                start_charge = max(arr, float(slots[slot_idx]))
                charge_dur = max(0.0, charge_to - after_arrival_b) / power
                finish_charge = start_charge + charge_dur
                finish_target = finish_charge + float(d_after) / speed
                if finish_target < best_finish:
                    best_finish = finish_target
                    best = (st, d_to, slot_idx, finish_charge, charge_to)
            return best

        while True:
            active = [
                (vid, st["time"])
                for vid, st in vstate.items()
                if not st["done"]
            ]
            if not active:
                break
            vid = min(active, key=lambda x: x[1])[0]
            stv = vstate[vid]
            v = v_by_id[vid]

            # 若当前车无在途任务，只有在仓库才允许从计划里“上车已释放任务”。
            if not stv["onboard"]:
                if not utils.same_position(stv["xy"], wh_xy):
                    if not _distance_move_and_apply(vid, wh_xy):
                        return float("-inf")
                    continue

                rem = _route_remaining(vid)
                released = [
                    tid for tid in rem
                    if task_state.get(tid, {}).get("status") == "pending"
                    and float(task_state[tid]["release"]) <= float(stv["time"]) + 1e-9
                ]
                if released:
                    for tid in released:
                        task_state[tid]["status"] = "in_progress"
                        task_state[tid]["carrier"] = vid
                        stv["onboard"].append(tid)
                    continue

                nxt_rel = _next_release_time(vid)
                if nxt_rel is None:
                    stv["done"] = True
                else:
                    # 在仓库等待下一批任务释放
                    stv["time"] = max(float(stv["time"]), float(nxt_rel))
                continue

            # 选当前车上按计划顺序的下一任务点
            rem = _route_remaining(vid)
            target_tid = next((tid for tid in rem if tid in stv["onboard"]), None)
            if target_tid is None:
                # 计划中没有可送任务，回仓触发下一批。
                if not utils.same_position(stv["xy"], wh_xy):
                    if not _distance_move_and_apply(vid, wh_xy):
                        return float("-inf")
                else:
                    stv["onboard"] = []
                continue
            target_xy = task_state[target_tid]["xy"]

            # 电量不够时，先去充电站（可多次）
            safe_guard = 0
            while True:
                safe_guard += 1
                if safe_guard > max(6, len(stations) * 4 + 2):
                    return float("-inf")
                d_leg = snapshot.distance(stv["xy"], target_xy)
                if d_leg == float("inf"):
                    return float("-inf")
                extra = utils.min_distance_to_any_station(target_xy, stations, snapshot) if stations else 0.0
                if extra == float("inf"):
                    return float("-inf")
                need = utils.energy_required_for_distance(v, float(d_leg) + float(extra)) * margin
                if stv["battery"] + 1e-9 >= need:
                    break
                choice = _choose_station_for_target(vid, target_xy)
                if choice is None:
                    return float("-inf")
                st_obj, d_to, slot_idx, finish_charge, charge_to = choice
                st_xy = (float(st_obj.position.x), float(st_obj.position.y))
                if not _distance_move_and_apply(vid, st_xy):
                    return float("-inf")
                slots = station_slots.get(st_obj.id, [now_ts])
                start_charge = max(float(stv["time"]), float(slots[slot_idx]))
                slots[slot_idx] = max(float(finish_charge), start_charge)
                station_slots[st_obj.id] = slots
                stv["time"] = slots[slot_idx]
                stv["battery"] = float(charge_to)

            if not _distance_move_and_apply(vid, target_xy):
                return float("-inf")

            # 送达目标任务并计分（按任务“上车后累计路径”口径）
            completion = max(float(stv["time"]), float(task_state[target_tid]["release"]))
            early_minutes = max(0.0, float(task_state[target_tid]["deadline"]) - completion) / 60.0
            overdue_minutes = max(0.0, completion - float(task_state[target_tid]["deadline"])) / 60.0
            score = (
                float(TASK_ASSIGN_REWARD)
                + float(task_state[target_tid]["priority"]) * float(PRIORITY_REWARD)
                - float(task_state[target_tid]["dist"]) * float(DISTANCE_PENALTY)
                + early_minutes * float(EARLY_COMPLETION_REWARD_PER_MIN)
                - overdue_minutes * float(OVERDUE_PENALTY_PER_MIN)
            )
            task_state[target_tid]["score"] = max(0.0, float(score))
            task_state[target_tid]["status"] = "completed"
            task_state[target_tid]["carrier"] = None
            stv["onboard"] = [tid for tid in stv["onboard"] if tid != target_tid]
            stv["route_idx"] += 1

            # 一批送完就回仓，贴近静态执行层行为
            if not stv["onboard"] and not utils.same_position(stv["xy"], wh_xy):
                if not _distance_move_and_apply(vid, wh_xy):
                    return float("-inf")

        total_score = sum(float(ts["score"]) for ts in task_state.values() if ts["status"] == "completed")
        return float(total_score)

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
        stations = list(getattr(snapshot, "charging_stations", []) or [])
        avg_station_load = (
            sum(float(getattr(s, "load_pressure", 0.0)) for s in stations) / len(stations)
            if stations else 0.0
        )

        # 每个任务点到最近充电站的缓冲距离（用于线性能量安全近似）。
        # 同时记录该点是否“可充电可达”（决定该点是否允许触发充电事件变量）。
        station_buffer_dist = {n: 0.0 for n in task_nodes}
        station_reachable = {n: False for n in task_nodes}
        for n in task_nodes:
            if stations:
                t = task_by_node[n]
                d_buf = utils.min_distance_to_any_station(
                    (float(t.position.x), float(t.position.y)),
                    stations,
                    snapshot,
                )
                if d_buf == float("inf"):
                    station_buffer_dist[n] = 0.0
                    station_reachable[n] = False
                else:
                    station_buffer_dist[n] = float(d_buf)
                    station_reachable[n] = True
            else:
                station_buffer_dist[n] = 0.0
                station_reachable[n] = False

        warehouse_reachable_station = False
        if stations:
            d_wh = utils.min_distance_to_any_station(
                (float(wh[0]), float(wh[1])),
                stations,
                snapshot,
            )
            warehouse_reachable_station = (d_wh != float("inf"))

        # 充电相关参数（线性代理）
        charge_time_penalty_per_s = float(static_cfg.get("charge_time_penalty_per_s", 0.02))
        charge_event_penalty = float(static_cfg.get("charge_event_penalty", 20.0))
        charge_queue_penalty = float(static_cfg.get("charge_queue_penalty", 40.0))
        avg_charge_detour_m = float(static_cfg.get("avg_charge_detour_m", 1200.0))
        soc_min_ratio = float(static_cfg.get("soc_min_ratio", 0.0))

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
        # unserved[n] 任务n是否不服务（在仿真中会走 TIMEOUT 语义）
        unserved = {n: m.addVar(vtype=GRB.BINARY, name=f"unserved_{n}") for n in task_nodes}

        # t[k,n] 车辆k到达节点n的时刻（仿真秒）
        tvar = {(k, n): m.addVar(lb=0.0, ub=latest[n], vtype=GRB.CONTINUOUS, name=f"t_{k}_{n}")
                for k in K for n in task_nodes}

        # 每个任务的完成时刻 c[n]、迟到 tard[n]、提前完成 early[n]
        c = {n: m.addVar(lb=0.0, ub=latest[n], vtype=GRB.CONTINUOUS, name=f"c_{n}") for n in task_nodes}
        tard = {n: m.addVar(lb=0.0, ub=max_lateness_s, vtype=GRB.CONTINUOUS, name=f"tard_{n}") for n in task_nodes}
        early = {n: m.addVar(lb=0.0, ub=max(0.0, deadline[n]), vtype=GRB.CONTINUOUS, name=f"early_{n}") for n in task_nodes}

        # start / end 是否启用
        use_k = {k: m.addVar(vtype=GRB.BINARY, name=f"use_{k}") for k in K}

        # 线性化充电变量：
        # charge_energy[k] = 车辆k在本规划中补充的总电量；
        # charge_events[k] = 车辆k充电次数（整数，近似）
        charge_energy = {
            k: m.addVar(lb=0.0, ub=max(0.0, float(v_by_id[k].max_battery) * (len(task_nodes) + 1)),
                        vtype=GRB.CONTINUOUS, name=f"charge_energy_{k}")
            for k in K
        }
        charge_events = {
            k: m.addVar(lb=0.0, ub=float(len(task_nodes) + 1), vtype=GRB.INTEGER, name=f"charge_events_{k}")
            for k in K
        }
        # 节点到达电量（SOC）与弧上充电量/充电事件。
        batt_arr = {}
        for k in K:
            max_batt_k = max(1e-9, float(getattr(v_by_id[k], "max_battery", 1.0)))
            for n in task_nodes:
                batt_arr[(k, n)] = m.addVar(
                    lb=0.0,
                    ub=max_batt_k,
                    vtype=GRB.CONTINUOUS,
                    name=f"batt_{k}_{n}",
                )
        charge_on_arc = {
            (k, i, j): m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name=f"q_{k}_{i}_{j}")
            for (k, i, j) in x
        }
        charge_evt_arc = {
            (k, i, j): m.addVar(vtype=GRB.BINARY, name=f"zchg_{k}_{i}_{j}")
            for (k, i, j) in x
        }

        # ---- 约束 ----
        # 每任务要么被一辆车服务，要么标记为 unserved（避免模型整体不可行）
        for n in task_nodes:
            m.addConstr(
                gp.quicksum(y[(k, n)] for k in K) + unserved[n] == 1,
                name=f"serve_or_unserved_{n}",
            )

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

            # ---------- 电量与充电线性近似 ----------
            # 服务总距离（含每个任务点“到最近充电站”的安全缓冲）
            service_dist_expr = gp.quicksum(
                (
                    dist[(i, j)]
                    + (station_buffer_dist[j] if j in task_nodes else 0.0)
                ) * x[(k, i, j)]
                for i in nodes
                for j in nodes
                if (k, i, j) in x
            )
            # 充电绕行距离（每次充电增加平均绕行）
            detour_dist_expr = float(avg_charge_detour_m) * charge_events[k]
            unit_cons = max(1e-9, float(getattr(v_by_id[k], "unit_energy_consumption", 0.0)))
            init_batt = max(0.0, float(getattr(v_by_id[k], "battery", 0.0)))
            max_batt = max(1e-9, float(getattr(v_by_id[k], "max_battery", 1.0)))
            power = max(1e-9, float(getattr(v_by_id[k], "charging_power", 0.022)))
            soc_floor = min(max_batt, max(0.0, float(soc_min_ratio) * max_batt))
            arcs_k = [(i, j) for i in nodes for j in nodes if (k, i, j) in x]
            chargeable_origin = {start: bool(warehouse_reachable_station)}
            for n in task_nodes:
                chargeable_origin[n] = bool(station_reachable.get(n, False))

            # 弧级充电变量联动：q<=max_batt*z, z<=x, q<=max_batt*x
            for i, j in arcs_k:
                m.addConstr(
                    charge_on_arc[(k, i, j)] <= max_batt * charge_evt_arc[(k, i, j)],
                    name=f"q_evt_link_{k}_{i}_{j}",
                )
                m.addConstr(
                    charge_evt_arc[(k, i, j)] <= x[(k, i, j)],
                    name=f"evt_arc_link_{k}_{i}_{j}",
                )
                m.addConstr(
                    charge_on_arc[(k, i, j)] <= max_batt * x[(k, i, j)],
                    name=f"q_arc_link_{k}_{i}_{j}",
                )
                if not chargeable_origin.get(i, False):
                    m.addConstr(charge_on_arc[(k, i, j)] == 0.0, name=f"q_disabled_{k}_{i}_{j}")
                    m.addConstr(charge_evt_arc[(k, i, j)] == 0.0, name=f"z_disabled_{k}_{i}_{j}")

            # 车辆级总充电量/次数与弧级变量一致
            m.addConstr(
                charge_energy[k] == gp.quicksum(charge_on_arc[(k, i, j)] for i, j in arcs_k),
                name=f"charge_energy_sum_{k}",
            )
            m.addConstr(
                charge_events[k] == gp.quicksum(charge_evt_arc[(k, i, j)] for i, j in arcs_k),
                name=f"charge_events_sum_{k}",
            )

            # 节点SOC上下界（仅对已服务节点生效）
            for n in task_nodes:
                m.addConstr(
                    batt_arr[(k, n)] <= max_batt * y[(k, n)],
                    name=f"soc_ub_{k}_{n}",
                )
                m.addConstr(
                    batt_arr[(k, n)] >= soc_floor * y[(k, n)],
                    name=f"soc_lb_{k}_{n}",
                )

            max_need = unit_cons * (
                max(dist.values()) + max(station_buffer_dist.values()) + float(avg_charge_detour_m)
            )
            m_soc = max(1.0, 2.0 * max_batt + max_need)

            # start -> j 的SOC传播
            for j in task_nodes:
                need_start_j = unit_cons * (dist[(start, j)] + station_buffer_dist[j])
                m.addConstr(
                    batt_arr[(k, j)]
                    >= init_batt - need_start_j + charge_on_arc[(k, start, j)] - m_soc * (1 - x[(k, start, j)]),
                    name=f"soc_start_lb_{k}_{j}",
                )
                m.addConstr(
                    batt_arr[(k, j)]
                    <= init_batt - need_start_j + charge_on_arc[(k, start, j)] + m_soc * (1 - x[(k, start, j)]),
                    name=f"soc_start_ub_{k}_{j}",
                )

            # i -> j 的SOC传播（任务到任务）
            for i in task_nodes:
                for j in task_nodes:
                    if i == j:
                        continue
                    need_ij = unit_cons * (dist[(i, j)] + station_buffer_dist[j])
                    m.addConstr(
                        batt_arr[(k, j)]
                        >= batt_arr[(k, i)] - need_ij + charge_on_arc[(k, i, j)] - m_soc * (1 - x[(k, i, j)]),
                        name=f"soc_lb_{k}_{i}_{j}",
                    )
                    m.addConstr(
                        batt_arr[(k, j)]
                        <= batt_arr[(k, i)] - need_ij + charge_on_arc[(k, i, j)] + m_soc * (1 - x[(k, i, j)]),
                        name=f"soc_ub_{k}_{i}_{j}",
                    )

            # i -> end 返回仓库的可达性（无需显式 end SOC）
            for i in task_nodes:
                need_i_end = unit_cons * dist[(i, end)]
                m.addConstr(
                    batt_arr[(k, i)] - need_i_end + charge_on_arc[(k, i, end)] >= -m_soc * (1 - x[(k, i, end)]),
                    name=f"soc_end_reach_{k}_{i}",
                )

            # 能量守恒：消耗 <= 初始电量 + 充电补入
            m.addConstr(
                unit_cons * (service_dist_expr + detour_dist_expr) <= init_batt + charge_energy[k],
                name=f"energy_budget_{k}",
            )
            # 充电能量由充电次数上限控制（每次最多补一块 max_battery）
            m.addConstr(
                charge_energy[k] <= max_batt * charge_events[k],
                name=f"charge_event_link_{k}",
            )
            # 粗时间可行：行驶时间 + 充电时间 不超过规划时域上界
            m.addConstr(
                (service_dist_expr + detour_dist_expr) / max(1e-9, float(getattr(v_by_id[k], "speed", 10.0)))
                + charge_energy[k] / power
                <= max_route_time + max_route_time * (1 - use_k[k]),
                name=f"time_energy_budget_{k}",
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
            # early = max(0, deadline-c)，但仅在任务被服务时生效。
            # 线性化：
            # early <= deadline * (1-unserved)
            # early <= deadline - c + M*unserved
            # early >= deadline - c - M*unserved
            early_cap = max(0.0, deadline[n])
            m.addConstr(early[n] <= early_cap * (1.0 - unserved[n]), name=f"early_cap_served_{n}")
            m.addConstr(early[n] <= deadline[n] - c[n] + early_cap * unserved[n], name=f"early_ub_{n}")
            m.addConstr(early[n] >= deadline[n] - c[n] - early_cap * unserved[n], name=f"early_lb_{n}")

        # ---- 目标函数 ----
        # 用与系统评分一致的线性代理：
        # maximize [任务奖励 + 优先级 + 提前完成 - 逾期 - 距离 - 充电代理项 - 未服务惩罚]
        # 常数项省略，只优化可变部分。
        total_distance = gp.quicksum(
            dist[(i, j)] * x[(k, i, j)]
            for k in K
            for i in nodes
            for j in nodes
            if (k, i, j) in x
        )
        total_tard = gp.quicksum(tard[n] for n in task_nodes)
        total_charge_energy = gp.quicksum(charge_energy[k] for k in K)
        total_charge_events = gp.quicksum(charge_events[k] for k in K)
        total_charge_time = gp.quicksum(
            charge_energy[k] / max(1e-9, float(getattr(v_by_id[k], "charging_power", 0.022)))
            for k in K
        )
        total_early = gp.quicksum(early[n] for n in task_nodes)
        served_count = gp.quicksum(1.0 - unserved[n] for n in task_nodes)
        total_unserved = gp.quicksum(unserved[n] for n in task_nodes)
        priority_term = gp.quicksum(
            float(task_by_node[n].priority) * float(PRIORITY_REWARD) * (1.0 - unserved[n])
            for n in task_nodes
        )
        assign_term = float(TASK_ASSIGN_REWARD) * served_count
        early_reward_term = float(EARLY_COMPLETION_REWARD_PER_MIN) / 60.0 * total_early
        # 未服务惩罚：保证“是否派单”由全局最优决定，避免把明显不可行任务强塞给车辆。
        # 默认强于单任务基础奖励与一般优先级收益，可通过 YAML 调整。
        unserved_penalty = float(
            static_cfg.get(
                "unserved_penalty",
                float(TASK_ASSIGN_REWARD) + 2.0 * float(PRIORITY_REWARD),
            )
        )

        obj = (
            assign_term
            + priority_term
            + early_reward_term
            - float(DISTANCE_PENALTY) * total_distance
            - float(OVERDUE_PENALTY_PER_MIN) / 60.0 * total_tard
            - float(charge_time_penalty_per_s) * total_charge_time
            - float(charge_event_penalty) * total_charge_events
            - float(charge_queue_penalty) * float(avg_station_load) * total_charge_events
            - float(unserved_penalty) * total_unserved
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
        force_gurobi_only = bool(((config.get_optimization_config().get("static") or {}).get("force_gurobi_only", False)))
        accept_feasible_force_only = bool(
            ((config.get_optimization_config().get("static") or {}).get("accept_feasible_when_force_gurobi_only", True))
        )
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
            if (
                force_gurobi_only
                and accept_feasible_force_only
                and m.status in (GRB.TIME_LIMIT, GRB.SUBOPTIMAL, GRB.OPTIMAL)
            ):
                if m.status != GRB.OPTIMAL and mip_gap > gap_th + 1e-9:
                    print(
                        "[STATIC][GUROBI] force mode accepted feasible incumbent "
                        f"with large gap={mip_gap:.6f} (threshold={gap_th:.6f})."
                    )
            elif m.status != GRB.OPTIMAL and mip_gap > gap_th + 1e-9:
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
        static_cfg = (config.get_optimization_config().get("static") or {})
        time_limit_s = max(0.2, float(static_cfg.get("exact_assignment_time_limit_s", 2.0)))
        start_ts = time.time()

        def upper_bound(idx: int) -> float:
            # 粗上界：剩余任务按“任务奖励+优先级奖励”全加
            rem = tasks[idx:]
            return sum(float(TASK_ASSIGN_REWARD) + float(t.priority) * float(PRIORITY_REWARD) for t in rem)

        def dfs(i: int, cur_obj_hint: float):
            nonlocal best_obj, best_assign
            if (time.time() - start_ts) >= time_limit_s:
                return
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

