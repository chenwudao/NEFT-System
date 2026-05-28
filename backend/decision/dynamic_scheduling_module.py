"""动态调度执行器。

只有两个公共方法：
    - run_once(strategy):  拍一张 Snapshot → 让算法出 Command → 落到 DataManager
    - receive_new_task(t): 供 API / 任务生成器在外部注入新任务

算法本身不感知 DataManager，也不直接改状态；所有"状态变动"都在本文件里发生。
"""

from datetime import datetime
from typing import Dict, List, Optional

from backend.algorithm import utils
from backend.algorithm.algorithm_manager import AlgorithmManager
from backend.algorithm.scheduler import (
    ACTION_CHARGE,
    ACTION_DELIVER,
    ACTION_GOTO_NODE,
    ACTION_HANDOFF,
    ACTION_IDLE,
    ACTION_RETURN,
    Command,
)
from backend.algorithm.snapshot import Snapshot
from backend.config import config
from backend.data.data_manager import DataManager
from backend.data.task import Task, TaskStatus
from backend.data.vehicle import VehicleStatus


class DynamicSchedulingModule:
    def __init__(self, data_manager: DataManager, algorithm_manager: AlgorithmManager):
        self.data_manager = data_manager
        self.algorithm_manager = algorithm_manager
        # 最近一次调度生成的 Command 列表（dict 形式），纯做展示用
        self.last_commands: List[Dict] = []
        # 当前轮策略名（用于策略特定兜底）
        self._current_strategy: str = ""

    # ------------------------------------------------------------------
    # 外部入口
    # ------------------------------------------------------------------
    def receive_new_task(self, task: Task) -> None:
        self.data_manager.add_task(task)

    def run_once(self, strategy: str) -> List[Dict]:
        """拍快照 → 跑算法 → 落地命令。返回这一轮产生的命令（dict）。"""
        self._current_strategy = str(strategy or "")

        snapshot = Snapshot.capture(self.data_manager)
        resolved = self.algorithm_manager.resolve_strategy_name(strategy)
        # relay_handoff 需每轮扫描全部车辆对（含行驶中），不能因无 IDLE 车而跳过
        if not snapshot.vehicles_need_decision() and resolved != "relay_handoff":
            self.last_commands = []
            return []

        try:
            commands = self.algorithm_manager.schedule(resolved, snapshot)
        except Exception as e:
            print(f"[ERROR DynamicSchedulingModule] scheduler '{strategy}' raised: {e}")
            import traceback
            traceback.print_exc()
            self.last_commands = []
            return []

        out: List[Dict] = []
        had_handoff = False
        for cmd in commands:
            executed = self._execute(cmd, snapshot)
            out.append(executed.to_dict())
            if executed.action == ACTION_HANDOFF:
                had_handoff = True

        if had_handoff and resolved == "relay_handoff":
            relay = self._relay_scheduler()
            if relay is not None:
                snap2 = Snapshot.capture(self.data_manager)
                for rcmd in relay.drain_resume_commands(snap2):
                    executed = self._execute(rcmd, snap2)
                    out.append(executed.to_dict())

        self.last_commands = out
        return out

    # ------------------------------------------------------------------
    # 落地：把 Command 翻译成 DataManager 上的状态变动
    # ------------------------------------------------------------------
    def _execute(self, cmd: Command, snapshot: Snapshot) -> Command:
        vehicle = self.data_manager.get_vehicle(cmd.vehicle_id)
        if vehicle is None:
            return cmd

        cmd = self._guard_battery_before_motion(vehicle, cmd, snapshot)

        if cmd.action == ACTION_IDLE:
            # 保留在 IDLE；清干净残留目标
            vehicle.clear_route()
            vehicle.update_status(VehicleStatus.IDLE)
            return cmd

        if cmd.action == ACTION_HANDOFF:
            # 原地接力：不需要 target_xy，走专门路径
            self._handle_handoff(vehicle, cmd)
            return cmd

        if cmd.target_xy is None:
            # 仓库只装货：deliver + assigned_tasks + 无 task_id/目标坐标
            if cmd.action == ACTION_DELIVER and cmd.assigned_tasks:
                self._handle_deliver(vehicle, cmd)
                return cmd
            print(f"[WARN] Command {cmd} missing target_xy; ignored.")
            return cmd

        if cmd.action == ACTION_DELIVER:
            self._handle_deliver(vehicle, cmd)
        elif cmd.action == ACTION_GOTO_NODE:
            self.data_manager.start_vehicle_route(
                vehicle.id, cmd.target_xy, VehicleStatus.MOVING_TO_NODE
            )
        elif cmd.action == ACTION_CHARGE:
            self.data_manager.start_vehicle_route(
                vehicle.id, cmd.target_xy, VehicleStatus.MOVING_TO_CHARGE
            )
        elif cmd.action == ACTION_RETURN:
            self.data_manager.start_vehicle_route(
                vehicle.id, cmd.target_xy, VehicleStatus.MOVING_TO_WAREHOUSE
            )
        return cmd

    def _guard_battery_before_motion(
        self, vehicle, cmd: Command, snapshot: Snapshot
    ) -> Command:
        """落地前兜底：目标不可达时，改派到当前电量可达的充电站。

        调度算法通常会在 utils 模板里做电量预判；这里再守一次，防止某个
        自定义算法直接输出不可达的 deliver/return/charge 命令导致车辆抛锚。
        """
        if cmd.action in (ACTION_IDLE, ACTION_HANDOFF) or cmd.target_xy is None:
            return cmd

        single_task_strategies = {
            "nearest_task",
            "priority_task",
            "heaviest_task",
            "deadline_earliest",
            "dfs_score_search",
            "sa_score_search",
            "rl_batch",
        }
        at_warehouse = (
            abs(float(vehicle.position.x) - float(snapshot.warehouse_xy[0])) < 1e-4
            and abs(float(vehicle.position.y) - float(snapshot.warehouse_xy[1])) < 1e-4
        )
        single_task_policy = (
            str(self._current_strategy) in single_task_strategies
            and cmd.action == ACTION_DELIVER
            and at_warehouse
            and len(getattr(cmd, "assigned_tasks", []) or []) <= 1
        )

        if cmd.action == ACTION_CHARGE:
            if utils.can_reach_target(
                vehicle, cmd.target_xy, snapshot, require_station_buffer=False
            ):
                return cmd
            station = utils.best_charging_station(vehicle, snapshot)
            if station is not None:
                return utils.make_charge_command(vehicle, station)
            print(
                f"[WARN] Vehicle {vehicle.id} cannot reach requested charging station "
                "and no reachable station is available; keep idle."
            )
            return utils.make_idle_command(vehicle)

        # 默认安全约束：任何下一目的地都要预留“到最近充电站”的余量。
        require_station_buffer = True
        if utils.can_reach_target(
            vehicle,
            cmd.target_xy,
            snapshot,
            require_station_buffer=require_station_buffer,
        ):
            return cmd

        # 目标不可直达时，检查是否存在“当前可达且充到阈值后可继续送达目标”的中转充电站。
        transit = self._best_transit_station_for_target(vehicle, cmd.target_xy, snapshot)
        if transit is not None:
            return utils.make_charge_command(vehicle, transit)

        # 单任务单车策略 + 仓库派单阶段：
        # 不能安全派单时，保持仓库待命（不把任务改 TIMEOUT）。
        if single_task_policy:
            print(
                f"[Policy] strategy={self._current_strategy} v{vehicle.id}: "
                "task not dispatchable (no direct-safe route / no charge transition). keep idle at warehouse."
            )
            return utils.make_idle_command(vehicle)

        print(
            f"[WARN] Vehicle {vehicle.id} cannot reach target or any charging station; "
            "target will be timed out if it is an active task."
        )
        if cmd.action == ACTION_DELIVER and cmd.task_id is not None:
            self._timeout_unreachable_task(vehicle, cmd.task_id)
        return utils.make_idle_command(vehicle)

    def _best_transit_station_for_target(self, vehicle, target_xy, snapshot: Snapshot):
        """选择中转充电站：车辆先去站补能，再能送达目标。"""
        stations = list(getattr(snapshot, "charging_stations", []) or [])
        if not stations:
            return None
        sched_cfg = config.get_scheduling_config()
        charge_until_pct = float(sched_cfg.get("charge_until_pct", 90.0))
        charge_until_pct = max(1.0, min(100.0, charge_until_pct))
        charge_level = float(vehicle.max_battery) * charge_until_pct / 100.0
        margin = float(sched_cfg.get("battery_safety_margin", 1.15))
        margin = max(1.0, margin)
        load_weight = float(sched_cfg.get("charge_load_weight_m", 8000.0))
        queue_weight = float(sched_cfg.get("charge_queue_weight_m", 2000.0))

        best_station = None
        best_cost = float("inf")
        for st in stations:
            st_xy = (float(st.position.x), float(st.position.y))
            # 先要求“当前可达该站”
            if not utils.can_reach_target(
                vehicle, st_xy, snapshot, require_station_buffer=False
            ):
                continue
            d_st_to_target = snapshot.distance(st_xy, target_xy)
            if d_st_to_target == float("inf"):
                continue
            d_target_to_station = utils.min_distance_to_any_station(
                target_xy, stations, snapshot
            )
            if d_target_to_station == float("inf"):
                continue
            need = (
                utils.energy_required_for_distance(
                    vehicle, float(d_st_to_target) + float(d_target_to_station)
                )
                * margin
            )
            # 从该站充到阈值电量仍不可达目标+缓冲，则该站不可用
            if charge_level + 1e-9 < need:
                continue

            d_to_st = snapshot.distance(vehicle.position, st.position)
            waiting = max(
                0,
                int(getattr(st, "queue_count", 0))
                - int(getattr(st, "capacity", 0)),
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

    def _timeout_unreachable_task(self, vehicle, task_id: int) -> None:
        """对无法在任何中转充电站后送达的任务，直接标记 TIMEOUT。"""
        task = self.data_manager.get_task(task_id)
        if task is None:
            return
        if task.status in (TaskStatus.COMPLETED, TaskStatus.TIMEOUT):
            return

        if task.assigned_vehicle_id == vehicle.id:
            task.assigned_vehicle_id = None
            vehicle.remove_task(task.id)
            vehicle.update_load(max(0.0, vehicle.current_load - float(task.weight)))
            self.data_manager._notify_vehicle_update(vehicle)

        task.score = 0.0
        self.data_manager.update_task_status(task.id, TaskStatus.TIMEOUT)
        print(
            f"[Timeout] Task {task.id} marked TIMEOUT: unreachable even after charging transition."
        )

    def _relay_scheduler(self):
        sch = self.algorithm_manager._registry.get("relay_handoff")
        if sch is not None and sch.name == "relay_handoff":
            return sch
        return None

    def _handle_handoff(self, vehicle, cmd: Command) -> None:
        """把 cmd.vehicle_id 车上的 task_ids_to_transfer 交给 cmd.target_vehicle_id。"""
        if cmd.target_vehicle_id is None or not cmd.task_ids_to_transfer:
            print(f"[WARN] Handoff command missing target / tasks: {cmd}")
            return

        position_eps = 1e-4
        relay = self._relay_scheduler()

        ok = self.data_manager.transfer_cargo(
            cmd.vehicle_id,
            cmd.target_vehicle_id,
            list(cmd.task_ids_to_transfer),
            position_eps=position_eps,
        )
        if relay is not None:
            relay.on_handoff_executed(
                cmd.vehicle_id,
                cmd.target_vehicle_id,
                list(cmd.task_ids_to_transfer),
                ok,
            )
        if not ok:
            print(
                f"[WARN] Handoff rejected: v{cmd.vehicle_id} -> v{cmd.target_vehicle_id}, "
                f"tasks={cmd.task_ids_to_transfer}（位置不合 / 载重不足 / 任务不在此车上）"
            )

    def _load_assigned_tasks_at_warehouse(
        self, vehicle, task_ids: List[int]
    ) -> None:
        """仓库装货：pending → IN_PROGRESS 并挂到车上。"""
        now_ts = self.data_manager.get_sim_time()
        for tid in task_ids:
            task = self.data_manager.get_task(tid)
            if task is None or task.status != TaskStatus.PENDING:
                continue
            if int(getattr(task, "create_time", 0)) > now_ts:
                continue
            self.data_manager.assign_task_to_vehicle(tid, vehicle.id)
            vehicle.update_load(vehicle.current_load + float(task.weight))

    def _handle_deliver(self, vehicle, cmd: Command) -> None:
        """transport 语义：同时支持"在仓库装货"与"半路跳下一站"。"""
        now_ts = self.data_manager.get_sim_time()
        if cmd.assigned_tasks:
            self._load_assigned_tasks_at_warehouse(vehicle, cmd.assigned_tasks)

        # 2) 启动前往"下一个任务点"的路径
        target_task = self.data_manager.get_task(cmd.task_id) if cmd.task_id is not None else None
        if target_task is None:
            # 没有指定具体 task，退化为 idle
            vehicle.update_status(VehicleStatus.IDLE)
            return
        if int(getattr(target_task, "create_time", 0)) > now_ts:
            vehicle.update_status(VehicleStatus.IDLE)
            return
        ok = self.data_manager.start_vehicle_route(
            vehicle.id,
            cmd.target_xy,
            VehicleStatus.MOVING_TO_TASK,
            task_id=target_task.id,
        )
        if not ok:
            # 路径不可达：把这单退回 PENDING 以免死锁
            if target_task.status == TaskStatus.IN_PROGRESS:
                target_task.assigned_vehicle_id = None
                target_task.update_status(TaskStatus.PENDING)
                vehicle.remove_task(target_task.id)
                vehicle.update_load(max(0.0, vehicle.current_load - target_task.weight))
            vehicle.update_status(VehicleStatus.IDLE)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get_last_commands(self) -> List[Dict]:
        return list(self.last_commands)
