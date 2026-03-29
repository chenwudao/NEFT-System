from typing import List, Dict, Optional
from datetime import datetime
from backend.data.data_manager import DataManager
from backend.data.task import Task, TaskStatus
from backend.data.vehicle import Vehicle, VehicleStatus
from backend.data.charging_station import ChargingStation
from backend.data.position import Position
from backend.algorithm.algorithm_manager import AlgorithmManager
from .static_planning_module import StaticPlanningModule
from .dynamic_scheduling_module import DynamicSchedulingModule
from .plan import Plan

class DecisionManager:
    def __init__(self, data_manager: DataManager, algorithm_manager: AlgorithmManager):
        self.data_manager = data_manager
        self.algorithm_manager = algorithm_manager
        self._static_planning = StaticPlanningModule(data_manager, algorithm_manager)
        self._dynamic_scheduling = DynamicSchedulingModule(data_manager, algorithm_manager)
        self.last_strategy_scores: Dict[str, Dict] = {}
        self.last_selected_strategy: str = "shortest_task_first"
        self.last_strategy_reason: str = "init"

    def static_planning(self) -> Optional[Plan]:
        return self._static_planning.execute_planning()

    def apply_static_plan(self, plan: Optional[Plan]) -> List[Dict]:
        """Turn a global Plan into transport commands and execute them (idle vehicles only)."""
        if not plan or not plan.vehicle_routes:
            return []

        pc = self.data_manager.path_calculator
        wh = self.data_manager.warehouse_position
        wh_xy = (wh.x, wh.y)
        commands: List[Dict] = []

        for vehicle_id, task_ids in plan.vehicle_routes.items():
            vehicle = self.data_manager.get_vehicle(vehicle_id)
            if not vehicle or vehicle.status != VehicleStatus.IDLE:
                continue

            tasks_ord = []
            for tid in task_ids:
                t = self.data_manager.get_task(tid)
                if t and t.status == TaskStatus.PENDING:
                    tasks_ord.append(t)
            if not tasks_ord:
                continue

            total_w = sum(t.weight for t in tasks_ord)
            if total_w > vehicle.max_load - vehicle.current_load:
                continue

            waypoints = [(vehicle.position.x, vehicle.position.y)]
            waypoints.extend((t.position.x, t.position.y) for t in tasks_ord)
            waypoints.append(wh_xy)
            full_path = pc.build_stitched_path(waypoints)
            if len(full_path) < 2:
                continue

            try:
                energy = pc.calculate_energy_consumption(vehicle, full_path)
                if vehicle.battery < energy:
                    continue
            except Exception:
                continue

            dist = pc.calculate_distance(full_path)
            spd = vehicle.speed if vehicle.speed and vehicle.speed > 0 else 0.1
            estimated_time = int(dist / spd)

            commands.append({
                "vehicle_id": vehicle.id,
                "action_type": "transport",
                "assigned_tasks": [t.id for t in tasks_ord],
                "path": full_path,
                "charging_station_id": None,
                "estimated_time": estimated_time,
            })

        self._dynamic_scheduling.run_commands(commands)
        return commands

    def _select_strategy_by_rules(self, tasks: List[Task], current_time: int) -> str:
        """基于启发式规则快速选择策略
        
        规则：
        1. 紧急任务（30分钟内截止）比例 > 30% → shortest_task_first
        2. 高优先级任务（priority >= 4）比例 > 30% → priority_based
        3. 其他情况 → composite_score
        """
        if not tasks:
            return "shortest_task_first"
        
        total = len(tasks)
        urgent_count = sum(1 for t in tasks if t.deadline - current_time < 1800)
        high_priority_count = sum(1 for t in tasks if t.priority >= 4)
        
        urgent_ratio = urgent_count / total
        high_priority_ratio = high_priority_count / total
        
        if urgent_ratio > 0.3:
            self.last_strategy_reason = "urgent_tasks_dominant"
            return "shortest_task_first"
        elif high_priority_ratio > 0.3:
            self.last_strategy_reason = "high_priority_dominant"
            return "priority_based"
        else:
            self.last_strategy_reason = "balanced_scenario"
            return "composite_score"

    def dynamic_scheduling(self, new_tasks: Optional[List[Task]] = None, 
                          strategy: str = "auto") -> List[Dict]:
        if new_tasks:
            for task in new_tasks:
                self._dynamic_scheduling.receive_new_task(task)

        if strategy == "auto":
            tasks = self.data_manager.get_pending_tasks()
            vehicles = self.data_manager.get_idle_vehicles()
            
            if tasks and vehicles:
                current_time = int(datetime.now().timestamp())
                strategy = self._select_strategy_by_rules(tasks, current_time)
                self.last_selected_strategy = strategy
                # 清空策略分数（不再使用详细评分）
                self.last_strategy_scores = {}
            else:
                strategy = "shortest_task_first"  # 默认回退策略
                self.last_selected_strategy = strategy
                self.last_strategy_reason = "no_tasks_or_vehicles"
                self.last_strategy_scores = {}
        else:
            self.last_selected_strategy = strategy
            self.last_strategy_reason = "manual_strategy"
            self.last_strategy_scores = {}

        commands = self._dynamic_scheduling.process_pending_tasks(strategy)

        return commands

    def manage_battery(self, vehicle: Vehicle) -> Optional[Dict]:
        """
        主动充电管理：电量低于阈值时，找最优充电站发起充电指令。
        修复 B3：原方法未被主循环调用，现在主循环每轮对 IDLE 车辆调用。
        增加 WAITING_CHARGE 状态处理：排队中的车辆不重复发充电指令。
        """
        # WAITING_CHARGE 状态：已在充电站排队，不需要再次处理
        if vehicle.status == VehicleStatus.WAITING_CHARGE:
            return None
        # CHARGING 状态：由主循环处理充电，不重复分配
        if vehicle.status == VehicleStatus.CHARGING:
            return None

        low_battery_threshold = 20.0  # 默认低电量阈值
        try:
            from backend.config import config
            low_battery_threshold = config.get_charging_thresholds()["low_battery_threshold"]
        except Exception:
            pass

        if vehicle.battery < vehicle.max_battery * (low_battery_threshold / 100.0):
            charging_stations = self.data_manager.get_charging_stations()
            station_id = self.data_manager.path_calculator.find_nearest_charging_station(
                vehicle, charging_stations
            )
            if station_id:
                station = self.data_manager.get_charging_station(station_id)
                pc = self.data_manager.path_calculator
                try:
                    path = pc.find_shortest_path(
                        (vehicle.position.x, vehicle.position.y),
                        (station.position.x, station.position.y),
                    )
                except Exception:
                    path = [
                        (vehicle.position.x, vehicle.position.y),
                        (station.position.x, station.position.y),
                    ]
                return {
                    "vehicle_id": vehicle.id,
                    "action_type": "charge",
                    "assigned_tasks": [],
                    "path": path,
                    "charging_station_id": station_id,
                    "estimated_time": 0,
                }
        return None

    def evaluate_charge_release_threshold(self, vehicle: Vehicle) -> float:
        """
        情境感知充电离站策略（Q4）。
        根据当前车队加任务情况，动态返回革站电量阈值（%）。

        返回值含义：
          100.0 — 车辆充裕，充满再离
           80.0 — 正常调度，充到80%离站
           60.0 — 任务紧急，充到60%即离
            0.0 — 高优打断，立即离开
        """
        try:
            from backend.config import config
            thresholds = config.get_charging_thresholds()
        except Exception:
            return 80.0  # 默认充到80%

        current_ts = int(__import__('datetime').datetime.now().timestamp())
        pending_tasks = self.data_manager.get_pending_tasks()
        idle_vehicles = self.data_manager.get_idle_vehicles()

        # 判断高优打断：正在充电，priority≥4任务且没有空闲车
        if vehicle.status == VehicleStatus.CHARGING and not idle_vehicles:
            urgent_high_prio = [
                t for t in pending_tasks
                if t.priority >= thresholds["interrupt_priority"]
                and (t.deadline - current_ts) < thresholds["urgent_deadline_window"]
            ]
            if urgent_high_prio:
                return 0.0  # 打断充电

        # 判断任务紧急：有deadline小于30min的任务
        urgent_deadline_window = thresholds["urgent_deadline_window"]
        has_urgent = any(
            (t.deadline - current_ts) < urgent_deadline_window
            for t in pending_tasks
        )
        if has_urgent:
            return thresholds["urgent_release"]  # 60.0

        # 判断车辆充裕：空闲车 ≥ 待处理任务 × 1.5
        n_pending = len(pending_tasks)
        n_idle = len(idle_vehicles)
        if n_pending > 0 and n_idle >= n_pending * thresholds["idle_ratio_for_full"]:
            return thresholds["full_release"]  # 100.0

        # 正常调度
        return thresholds["normal_release"]  # 80.0


    def coordinate_vehicles(self, task: Task) -> List[Dict]:
        """
        超载任务完成调度（修复 B7）。

        原问题：多车被分配同一 task_id 导致状态冲突。
        修复方式：将超重任务按车辆可载重拆分为多个子任务，每个子任务独立分配一辆车。
        若任务重量在单车等级内，则直接分配最近空闲车。
        """
        idle_vehicles = self.data_manager.get_idle_vehicles()
        if not idle_vehicles:
            return []

        # 载重足够的车辆（可单辆完成）
        capable = [v for v in idle_vehicles if v.get_remaining_load() >= task.weight]
        if capable:
            # 单车可完成：选最近的
            best = min(capable, key=lambda v:
                self.data_manager.path_calculator.calculate_distance_from_positions(
                    [v.position, task.position]
                )
            )
            return self._build_single_vehicle_transport(best, task)

        # 超载场景：拆分任务为子任务
        total_available = sum(v.get_remaining_load() for v in idle_vehicles)
        if total_available < task.weight:
            return []  # 所有车辆合并也装不下

        commands = []
        remaining_weight = task.weight
        sorted_vehicles = sorted(
            idle_vehicles,
            key=lambda v: self.data_manager.path_calculator.calculate_distance_from_positions(
                [v.position, task.position]
            )
        )
        sub_task_id_base = task.id * 1000  # 子任务 ID 基底

        for i, vehicle in enumerate(sorted_vehicles):
            if remaining_weight <= 0:
                break
            load_for_this = min(vehicle.get_remaining_load(), remaining_weight)
            if load_for_this <= 0:
                continue

            # 创建子任务（共享任务位置，但重量垆分）
            from backend.data.task import Task as TaskCls
            sub_task = TaskCls(
                id=sub_task_id_base + i,
                position=task.position,
                weight=load_for_this,
                create_time=task.create_time,
                deadline=task.deadline,
                priority=task.priority,
            )
            self.data_manager.add_task(sub_task)
            commands.extend(self._build_single_vehicle_transport(vehicle, sub_task))
            remaining_weight -= load_for_this

        return commands

    def _build_single_vehicle_transport(self, vehicle: Vehicle, task: Task) -> List[Dict]:
        """为单辆车生成运输指令"""
        warehouse_pos = self.data_manager.warehouse_position
        pc = self.data_manager.path_calculator
        complete_path = pc.build_stitched_path([
            (vehicle.position.x, vehicle.position.y),
            (task.position.x, task.position.y),
            (warehouse_pos.x, warehouse_pos.y),
        ])
        speed = vehicle.speed if vehicle.speed > 0 else 10.0
        dist = pc.calculate_distance(complete_path)
        estimated_time = int(dist / speed)
        return [{
            "vehicle_id": vehicle.id,
            "action_type": "transport",
            "assigned_tasks": [task.id],
            "path": complete_path,
            "charging_station_id": None,
            "estimated_time": estimated_time,
        }]


    def get_system_status(self) -> Dict:
        tasks = self.data_manager.get_tasks()
        vehicles = self.data_manager.get_vehicles()
        charging_stations = self.data_manager.get_charging_stations()

        pending_tasks = [t for t in tasks if t.status == TaskStatus.PENDING]
        completed_tasks = [t for t in tasks if t.status == TaskStatus.COMPLETED]
        idle_vehicles = [v for v in vehicles if v.status == VehicleStatus.IDLE]
        completion_rate = len(completed_tasks) / len(tasks) if tasks else 0.0
        vehicle_utilization = (len(vehicles) - len(idle_vehicles)) / len(vehicles) if vehicles else 0.0

        return {
            "timestamp": int(datetime.now().timestamp()),
            "total_tasks": len(tasks),
            "pending_tasks": len(pending_tasks),
            "completed_tasks": len(completed_tasks),
            "timeout_tasks": len([t for t in tasks if t.status == TaskStatus.TIMEOUT]),
            "total_vehicles": len(vehicles),
            "idle_vehicles": len(idle_vehicles),
            "transporting_vehicles": len([v for v in vehicles if v.status == VehicleStatus.TRANSPORTING]),
            "charging_vehicles": len([v for v in vehicles if v.status == VehicleStatus.CHARGING]),
            "waiting_charge_vehicles": len([v for v in vehicles if v.status == VehicleStatus.WAITING_CHARGE]),
            "total_charging_stations": len(charging_stations),
            "active_commands": len(self._dynamic_scheduling.get_active_commands()),
            "current_strategy": self.last_selected_strategy,
            "current_strategy_reason": self.last_strategy_reason,
            "completion_rate": completion_rate,
            "vehicle_utilization": vehicle_utilization,
            "strategy_scores": self.last_strategy_scores
        }

    def evaluate_system_performance(self) -> Dict:
        tasks = self.data_manager.get_tasks()
        completed_tasks = [t for t in tasks if t.status == TaskStatus.COMPLETED]

        if not completed_tasks:
            return {
                "completion_rate": 0.0,
                "avg_completion_time": 0.0,
                "total_distance": 0.0,
                "total_score": 0.0
            }

        completion_rate = len(completed_tasks) / len(tasks) if tasks else 0.0

        total_completion_time = 0
        total_distance = 0
        total_score = 0

        for task in completed_tasks:
            if task.complete_time and task.start_time:
                total_completion_time += (task.complete_time - task.start_time)

            total_distance += task.complete_path_distance

            # 与任务闭环评分口径一致，优先使用任务最终得分。
            if task.score != 0:
                total_score += task.score
            elif task.complete_time and task.deadline:
                total_score += self.data_manager.path_calculator.calculate_task_score(
                    task,
                    task.complete_time,
                    task.complete_path_distance
                )

        avg_completion_time = total_completion_time / len(completed_tasks) if completed_tasks else 0.0

        return {
            "completion_rate": completion_rate,
            "avg_completion_time": avg_completion_time,
            "total_distance": total_distance,
            "total_score": total_score
        }

    def get_last_strategy_evaluation(self) -> Dict:
        return {
            "selected_strategy": self.last_selected_strategy,
            "selection_reason": self.last_strategy_reason,
            "strategy_scores": self.last_strategy_scores
        }
