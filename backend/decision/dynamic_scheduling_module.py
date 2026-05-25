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
from backend.data.data_manager import DataManager
from backend.data.task import Task, TaskStatus, apply_deadline_timeouts
from backend.data.vehicle import VehicleStatus


class DynamicSchedulingModule:
    def __init__(self, data_manager: DataManager, algorithm_manager: AlgorithmManager):
        self.data_manager = data_manager
        self.algorithm_manager = algorithm_manager
        # 最近一次调度生成的 Command 列表（dict 形式），纯做展示用
        self.last_commands: List[Dict] = []

    # ------------------------------------------------------------------
    # 外部入口
    # ------------------------------------------------------------------
    def receive_new_task(self, task: Task) -> None:
        self.data_manager.add_task(task)

    def run_once(self, strategy: str) -> List[Dict]:
        """拍快照 → 跑算法 → 落地命令。返回这一轮产生的命令（dict）。"""
        # 先把超时任务统一打 TIMEOUT，避免算法看到它们。
        apply_deadline_timeouts(
            self.data_manager.get_tasks(), int(datetime.now().timestamp())
        )

        snapshot = Snapshot.capture(self.data_manager)
        if not snapshot.vehicles_need_decision():
            self.last_commands = []
            return []

        try:
            commands = self.algorithm_manager.schedule(strategy, snapshot)
        except Exception as e:
            print(f"[ERROR DynamicSchedulingModule] scheduler '{strategy}' raised: {e}")
            import traceback
            traceback.print_exc()
            self.last_commands = []
            return []

        out: List[Dict] = []
        for cmd in commands:
            executed = self._execute(cmd, snapshot)
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
            # 其余 action 必须带 target
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

        # 配送 / 特殊节点要预留“到最近充电站”的余量；回仓库本身可作为安全点。
        require_station_buffer = cmd.action != ACTION_RETURN
        if utils.can_reach_target(
            vehicle,
            cmd.target_xy,
            snapshot,
            require_station_buffer=require_station_buffer,
        ):
            return cmd

        station = utils.best_charging_station(vehicle, snapshot)
        if station is not None:
            return utils.make_charge_command(vehicle, station)

        print(
            f"[WARN] Vehicle {vehicle.id} cannot reach target or any charging station; "
            "keep idle to avoid running out of battery."
        )
        return utils.make_idle_command(vehicle)

    def _handle_handoff(self, vehicle, cmd: Command) -> None:
        """把 cmd.vehicle_id 车上的 task_ids_to_transfer 交给 cmd.target_vehicle_id。"""
        if cmd.target_vehicle_id is None or not cmd.task_ids_to_transfer:
            print(f"[WARN] Handoff command missing target / tasks: {cmd}")
            return
        ok = self.data_manager.transfer_cargo(
            cmd.vehicle_id, cmd.target_vehicle_id, list(cmd.task_ids_to_transfer)
        )
        if not ok:
            print(
                f"[WARN] Handoff rejected: v{cmd.vehicle_id} -> v{cmd.target_vehicle_id}, "
                f"tasks={cmd.task_ids_to_transfer}（位置不合 / 载重不足 / 任务不在此车上）"
            )

    def _handle_deliver(self, vehicle, cmd: Command) -> None:
        """transport 语义：同时支持"在仓库装货"与"半路跳下一站"。"""
        # 1) 如果 cmd.assigned_tasks 非空，说明这一次是在仓库批量接单：
        #    逐一把 task 状态置 ASSIGNED + 加到车上 + 累加载重
        if cmd.assigned_tasks:
            for tid in cmd.assigned_tasks:
                task = self.data_manager.get_task(tid)
                if task is None or task.status != TaskStatus.PENDING:
                    continue
                self.data_manager.assign_task_to_vehicle(tid, vehicle.id)
                vehicle.update_load(vehicle.current_load + task.weight)

        # 2) 启动前往"下一个任务点"的路径
        target_task = self.data_manager.get_task(cmd.task_id) if cmd.task_id is not None else None
        if target_task is None:
            # 没有指定具体 task，退化为 idle
            vehicle.update_status(VehicleStatus.IDLE)
            return
        ok = self.data_manager.start_vehicle_route(
            vehicle.id,
            cmd.target_xy,
            VehicleStatus.MOVING_TO_TASK,
            task_id=target_task.id,
        )
        if not ok:
            # 路径不可达：把 ASSIGNED 的这单退回 PENDING 以免死锁
            if target_task.status == TaskStatus.ASSIGNED:
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
