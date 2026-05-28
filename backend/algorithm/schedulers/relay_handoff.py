"""协同接力调度：基于 nearest_task 装批，路网上近距离车辆可协商交换货物。

交换流程：
    1. 两车在仓库外、路网距离 < proximity_threshold_m 时可协商（不限 idle / 行驶中）。
    2. 合并车上任务做 k=2 聚类；max_load 较小的车优先从较轻簇按重量升序装货，
       其余归另一车；若另一车放不下则放弃交换。
    3. 约定 path 中点碰头，先到者等待；同节点后 handoff 转交。
    4. 交换成功后，该**车辆对**须各自回仓一次才能再次交换（与其他车不受限）。
    5. 每辆车须**首次离仓后再回仓一次**，才具备交换资格（避免开局同点触发）。
    6. 交接后若无任务则回仓库。

仓库装批与常规在途送货逻辑与 nearest_task 一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.schedulers.regional_planning import _kmeans_packages
from backend.algorithm.snapshot import Snapshot
from backend.config import config
from backend.data.task import Task
from backend.data.vehicle import Vehicle

_POSITION_EPS = 1e-4


def _proximity_threshold_m() -> float:
    relay = config.get_scheduling_config().get("relay_handoff") or {}
    return float(relay.get("proximity_threshold_m", 5000.0))


def _pair_key(a_id: int, b_id: int) -> Tuple[int, int]:
    return (min(a_id, b_id), max(a_id, b_id))


@dataclass
class _HandoffPlan:
    vehicle_a: int
    vehicle_b: int
    meeting_xy: Tuple[float, float]
    a_to_b: List[int] = field(default_factory=list)
    b_to_a: List[int] = field(default_factory=list)


@dataclass
class _ExchangeProposal:
    a_to_b: List[int]
    b_to_a: List[int]
    meeting_xy: Tuple[float, float]


def _vehicle_by_id(snapshot: Snapshot) -> Dict[int, Vehicle]:
    return {v.id: v for v in snapshot.vehicles}


def _tasks_by_id(snapshot: Snapshot) -> Dict[int, Task]:
    return {t.id: t for t in snapshot.tasks}


def _at_warehouse(v: Vehicle, snapshot: Snapshot) -> bool:
    wh = snapshot.warehouse_xy
    return snapshot._near_point((v.position.x, v.position.y), wh)


def _eligible_vehicles(snapshot: Snapshot) -> List[Vehicle]:
    """仓库外、未抛锚的所有车辆（含行驶中 / 充电等）。"""
    return [
        v
        for v in snapshot.vehicles
        if not v.is_stranded() and not _at_warehouse(v, snapshot)
    ]


def _same_xy(
    a_xy: Tuple[float, float],
    b_xy: Tuple[float, float],
    snapshot: Snapshot,
) -> bool:
    return snapshot._near_point(a_xy, b_xy, eps=_POSITION_EPS)


def _at_meeting(v: Vehicle, meeting_xy: Tuple[float, float], snapshot: Snapshot) -> bool:
    pos = (float(v.position.x), float(v.position.y))
    return _same_xy(pos, meeting_xy, snapshot)


def _vehicles_colocated(va: Vehicle, vb: Vehicle, snapshot: Snapshot) -> bool:
    pos_a = (float(va.position.x), float(va.position.y))
    pos_b = (float(vb.position.x), float(vb.position.y))
    return _same_xy(pos_a, pos_b, snapshot)


def _heading_to_meeting(v: Vehicle, meeting_xy: Tuple[float, float], snapshot: Snapshot) -> bool:
    if v.current_target_xy is None:
        return False
    return _same_xy(v.current_target_xy, meeting_xy, snapshot)


def _binary_split_tasks(
    va: Vehicle,
    vb: Vehicle,
    tasks_a: List[Task],
    tasks_b: List[Task],
    snapshot: Snapshot,
) -> Optional[Tuple[List[int], List[int]]]:
    """按二分聚类 + 小载重车优先取轻簇，返回 (a_to_b, b_to_a) 或 None。"""
    all_tasks = list(tasks_a) + list(tasks_b)
    if not all_tasks:
        return None

    if len(all_tasks) == 1:
        clusters = [all_tasks, []]
    else:
        packages = _kmeans_packages(all_tasks, 2)
        clusters = [p.tasks for p in packages]
        if len(clusters) == 1:
            clusters = [clusters[0], []]

    def cluster_weight(ts: List[Task]) -> float:
        return sum(float(t.weight) for t in ts)

    clusters.sort(key=cluster_weight)
    light_cluster = list(clusters[0])

    small_v, large_v = (va, vb) if va.max_load <= vb.max_load else (vb, va)
    small_is_a = small_v.id == va.id

    light_cluster.sort(key=lambda t: float(t.weight))

    small_keeps: List[Task] = []
    small_w = 0.0
    cap = float(small_v.max_load)
    for t in light_cluster:
        w = float(t.weight)
        if small_w + w <= cap + 1e-9:
            small_keeps.append(t)
            small_w += w

    small_keep_ids = {t.id for t in small_keeps}
    large_keeps = [t for t in all_tasks if t.id not in small_keep_ids]
    large_w = sum(float(t.weight) for t in large_keeps)
    if large_w > float(large_v.max_load) + 1e-9:
        return None

    if small_is_a:
        a_final = {t.id for t in small_keeps}
        b_final = {t.id for t in large_keeps}
    else:
        a_final = {t.id for t in large_keeps}
        b_final = {t.id for t in small_keeps}

    a_orig = {t.id for t in tasks_a}
    b_orig = {t.id for t in tasks_b}
    a_to_b = sorted(a_orig - a_final)
    b_to_a = sorted(b_orig - b_final)

    if not a_to_b and not b_to_a:
        return None
    return a_to_b, b_to_a


def _propose_exchange(
    va: Vehicle,
    vb: Vehicle,
    snapshot: Snapshot,
) -> Optional[_ExchangeProposal]:
    tasks_a = snapshot.vehicle_undelivered_tasks(va)
    tasks_b = snapshot.vehicle_undelivered_tasks(vb)

    if not tasks_a and not tasks_b:
        return None

    split = _binary_split_tasks(va, vb, tasks_a, tasks_b, snapshot)
    if split is None:
        return None
    a_to_b, b_to_a = split

    tasks_by_id = _tasks_by_id(snapshot)

    recv_a = sum(float(tasks_by_id[t].weight) for t in b_to_a if t in tasks_by_id)
    give_a = sum(float(tasks_by_id[t].weight) for t in a_to_b if t in tasks_by_id)
    final_a = float(va.current_load) - give_a + recv_a
    if final_a > float(va.max_load) + 1e-9:
        return None

    recv_b = sum(float(tasks_by_id[t].weight) for t in a_to_b if t in tasks_by_id)
    give_b = sum(float(tasks_by_id[t].weight) for t in b_to_a if t in tasks_by_id)
    final_b = float(vb.current_load) - give_b + recv_b
    if final_b > float(vb.max_load) + 1e-9:
        return None

    pos_a = (float(va.position.x), float(va.position.y))
    pos_b = (float(vb.position.x), float(vb.position.y))
    meeting_xy = utils.path_midpoint(pos_a, pos_b, snapshot)

    if not utils.can_reach_target(va, meeting_xy, snapshot, require_station_buffer=True):
        return None
    if not utils.can_reach_target(vb, meeting_xy, snapshot, require_station_buffer=True):
        return None

    return _ExchangeProposal(a_to_b=a_to_b, b_to_a=b_to_a, meeting_xy=meeting_xy)


class RelayHandoffScheduler(Scheduler):
    name = "relay_handoff"

    def __init__(self) -> None:
        self._handoff_plans: Dict[Tuple[int, int], _HandoffPlan] = {}
        # 按车辆对冷却：仅 (1,2) 交换后须双双回仓；(1,3) 不受影响
        self._pair_warehouse_gate: Dict[Tuple[int, int], Set[int]] = {}
        # 交换完成后待恢复常规调度（送货 / 回仓）
        self._resume_queue: Set[int] = set()
        # 首次回仓门槛：离仓后再回仓一次，才允许参与任何交换
        self._has_departed_warehouse: Set[int] = set()
        self._returned_warehouse_once: Set[int] = set()

    def _abort_handoff_plan(self, pair: Tuple[int, int], reason: str) -> None:
        plan = self._handoff_plans.pop(pair, None)
        if plan is None:
            return
        self._resume_queue.add(plan.vehicle_a)
        self._resume_queue.add(plan.vehicle_b)
        print(
            f"[RelayHandoff] 取消交换 v{pair[0]} <-> v{pair[1]}: {reason}，"
            f"恢复各自任务"
        )

    def drain_resume_commands(self, snapshot: Snapshot) -> List[Command]:
        """交换完成后立即派发下一跳（送货或回仓）。"""
        commands: List[Command] = []
        handoff_busy = self._vehicles_in_active_handoff()
        vehicles = _vehicle_by_id(snapshot)
        for vid in list(self._resume_queue):
            if vid in handoff_busy:
                continue
            v = vehicles.get(vid)
            if v is None or v.is_stranded() or not v.is_idle() or v.has_target():
                self._resume_queue.discard(vid)
                continue
            commands.append(utils.decide_en_route(v, snapshot))
            self._resume_queue.discard(vid)
        return commands

    def on_handoff_executed(
        self,
        src_id: int,
        dst_id: int,
        task_ids: List[int],
        ok: bool,
    ) -> None:
        if not ok:
            pair = _pair_key(src_id, dst_id)
            if pair in self._handoff_plans:
                self._abort_handoff_plan(pair, "转交执行失败")
            return
        pair = _pair_key(src_id, dst_id)
        plan = self._handoff_plans.get(pair)
        if plan is None:
            return
        if src_id == plan.vehicle_a:
            plan.a_to_b = [t for t in plan.a_to_b if t not in task_ids]
        elif src_id == plan.vehicle_b:
            plan.b_to_a = [t for t in plan.b_to_a if t not in task_ids]
        if not plan.a_to_b and not plan.b_to_a:
            del self._handoff_plans[pair]
            self._pair_warehouse_gate[pair] = set()
            self._resume_queue.add(plan.vehicle_a)
            self._resume_queue.add(plan.vehicle_b)
            print(
                f"[RelayHandoff] v{pair[0]} <-> v{pair[1]} 交换完成，"
                f"须各自回仓一次后才能再次互换"
            )

    def _note_warehouse_visits(self, snapshot: Snapshot) -> None:
        for v in snapshot.vehicles:
            vid = v.id
            if _at_warehouse(v, snapshot):
                if vid in self._has_departed_warehouse and vid not in self._returned_warehouse_once:
                    self._returned_warehouse_once.add(vid)
                    print(f"[RelayHandoff] v{vid} 首次回仓，具备交换资格")
                for pair in list(self._pair_warehouse_gate.keys()):
                    if vid not in pair:
                        continue
                    self._pair_warehouse_gate[pair].add(vid)
                    if len(self._pair_warehouse_gate[pair]) >= 2:
                        del self._pair_warehouse_gate[pair]
                        print(
                            f"[RelayHandoff] v{pair[0]} <-> v{pair[1]} "
                            f"均已回仓，可再次协商交换"
                        )
            else:
                self._has_departed_warehouse.add(vid)

    def _vehicle_exchange_eligible(self, vehicle_id: int) -> bool:
        return vehicle_id in self._returned_warehouse_once

    def _pair_exchange_allowed(self, a_id: int, b_id: int) -> bool:
        if not self._vehicle_exchange_eligible(a_id) or not self._vehicle_exchange_eligible(b_id):
            return False
        return _pair_key(a_id, b_id) not in self._pair_warehouse_gate

    def _vehicles_in_active_handoff(self) -> Set[int]:
        busy: Set[int] = set()
        for plan in self._handoff_plans.values():
            busy.add(plan.vehicle_a)
            busy.add(plan.vehicle_b)
        return busy

    def _execute_handoff_at_meeting(
        self,
        plan: _HandoffPlan,
        snapshot: Snapshot,
        vehicles: Dict[int, Vehicle],
        handled: Set[int],
    ) -> List[Command]:
        pair = _pair_key(plan.vehicle_a, plan.vehicle_b)
        va = vehicles.get(plan.vehicle_a)
        vb = vehicles.get(plan.vehicle_b)
        if va is None or vb is None:
            self._handoff_plans.pop(pair, None)
            return []

        if not (_at_meeting(va, plan.meeting_xy, snapshot) and _at_meeting(vb, plan.meeting_xy, snapshot)):
            return []

        if not _vehicles_colocated(va, vb, snapshot):
            return []

        cmds: List[Command] = []
        if plan.a_to_b:
            cmds.append(utils.make_handoff_command(va, vb, plan.a_to_b))
            handled.add(va.id)
        if plan.b_to_a:
            cmds.append(utils.make_handoff_command(vb, va, plan.b_to_a))
            handled.add(vb.id)

        if not cmds:
            self._abort_handoff_plan(pair, "无可转交任务")
        return cmds

    def _command_for_handoff_vehicle(
        self,
        v: Vehicle,
        snapshot: Snapshot,
    ) -> Optional[Command]:
        for plan in self._handoff_plans.values():
            if v.id not in (plan.vehicle_a, plan.vehicle_b):
                continue
            other_id = plan.vehicle_b if v.id == plan.vehicle_a else plan.vehicle_a
            other = _vehicle_by_id(snapshot).get(other_id)
            if other is None:
                continue

            if _at_meeting(v, plan.meeting_xy, snapshot) and _at_meeting(
                other, plan.meeting_xy, snapshot
            ):
                if _vehicles_colocated(v, other, snapshot):
                    return None
                if v.is_idle():
                    return utils.make_idle_command(v)
                return None

            if _at_meeting(v, plan.meeting_xy, snapshot):
                if v.is_idle():
                    return utils.make_idle_command(v)
                return None

            if _heading_to_meeting(v, plan.meeting_xy, snapshot):
                return None

            if utils.can_reach_target(
                v, plan.meeting_xy, snapshot, require_station_buffer=True
            ):
                return utils.make_goto_node_command(v, plan.meeting_xy)
            return None
        return None

    def _try_start_handoff(
        self,
        va: Vehicle,
        vb: Vehicle,
        snapshot: Snapshot,
    ) -> Optional[_HandoffPlan]:
        if va.is_stranded() or vb.is_stranded():
            return None
        if _at_warehouse(va, snapshot) or _at_warehouse(vb, snapshot):
            return None
        if not self._pair_exchange_allowed(va.id, vb.id):
            return None

        dist = snapshot.distance(va.position, vb.position)
        if dist > _proximity_threshold_m():
            return None

        proposal = _propose_exchange(va, vb, snapshot)
        if proposal is None:
            return None

        return _HandoffPlan(
            vehicle_a=va.id,
            vehicle_b=vb.id,
            meeting_xy=proposal.meeting_xy,
            a_to_b=list(proposal.a_to_b),
            b_to_a=list(proposal.b_to_a),
        )

    def _log_handoff_triggered(self, plan: _HandoffPlan, snapshot: Snapshot) -> None:
        mx, my = plan.meeting_xy
        dist = snapshot.distance(
            _vehicle_by_id(snapshot)[plan.vehicle_a].position,
            _vehicle_by_id(snapshot)[plan.vehicle_b].position,
        )
        print(
            f"[RelayHandoff] 触发交换: v{plan.vehicle_a} <-> v{plan.vehicle_b}, "
            f"距离={dist:.0f}m, 碰头点=({mx:.5f},{my:.5f}), "
            f"v{plan.vehicle_a}->v{plan.vehicle_b}={plan.a_to_b}, "
            f"v{plan.vehicle_b}->v{plan.vehicle_a}={plan.b_to_a}"
        )

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        self._note_warehouse_visits(snapshot)

        commands: List[Command] = []
        handled: Set[int] = set()
        vehicles = _vehicle_by_id(snapshot)
        handoff_busy = self._vehicles_in_active_handoff()

        # 优先恢复上一轮交换完成的车辆
        for cmd in self.drain_resume_commands(snapshot):
            commands.append(cmd)
            handled.add(cmd.vehicle_id)

        for _pair, plan in list(self._handoff_plans.items()):
            commands.extend(
                self._execute_handoff_at_meeting(plan, snapshot, vehicles, handled)
            )

        handoff_busy = self._vehicles_in_active_handoff()

        eligible = [
            v for v in _eligible_vehicles(snapshot) if v.id not in handoff_busy
        ]
        eligible.sort(key=lambda v: v.id)
        for i, va in enumerate(eligible):
            if va.id in handoff_busy:
                continue
            for vb in eligible[i + 1 :]:
                if vb.id in handoff_busy:
                    continue
                pair = _pair_key(va.id, vb.id)
                if pair in self._handoff_plans:
                    continue
                plan = self._try_start_handoff(va, vb, snapshot)
                if plan is None:
                    continue
                self._handoff_plans[pair] = plan
                handoff_busy.add(va.id)
                handoff_busy.add(vb.id)
                self._log_handoff_triggered(plan, snapshot)
                commands.extend(
                    self._execute_handoff_at_meeting(plan, snapshot, vehicles, handled)
                )
                break

        for vid in sorted(handoff_busy):
            if vid in handled:
                continue
            veh = vehicles.get(vid)
            if veh is None:
                continue
            cmd = self._command_for_handoff_vehicle(veh, snapshot)
            if cmd is not None:
                commands.append(cmd)
                handled.add(vid)

        for v in snapshot.idle_vehicles_not_at_warehouse():
            if v.id in handled or v.id in handoff_busy:
                continue
            commands.append(utils.decide_en_route(v, snapshot))
            handled.add(v.id)

        claimed: Set[int] = set()

        def pick_batch(vehicle: Vehicle, tasks: List[Task], snap: Snapshot) -> List[Task]:
            unclaimed = [t for t in tasks if t.id not in claimed]
            unclaimed = utils.feasible_tasks_for(vehicle, unclaimed)
            if not unclaimed:
                return []

            start_xy = (vehicle.position.x, vehicle.position.y)
            unclaimed.sort(key=lambda t: snap.distance(vehicle.position, t.position))

            chosen: List[Task] = []
            for t in unclaimed:
                cand = chosen + [t]
                ordered = utils.greedy_chain(
                    start_xy,
                    [(x.position.x, x.position.y) for x in cand],
                    snap,
                )
                if not ordered:
                    break
                dist = utils.estimate_chain_distance_with_recharge(
                    vehicle,
                    ordered,
                    snap,
                    require_final_station_buffer=True,
                )
                if dist == float("inf"):
                    break
                chosen = cand
            return chosen

        handoff_busy = self._vehicles_in_active_handoff()
        for v in snapshot.idle_vehicles_at_warehouse():
            if v.id in handled or v.id in handoff_busy:
                continue
            cmd = utils.decide_at_warehouse(v, snapshot, pick_batch)
            if cmd.assigned_tasks:
                claimed.update(cmd.assigned_tasks)
            commands.append(cmd)
            handled.add(v.id)

        return commands
