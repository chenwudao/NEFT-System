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
from .strategy_selector import StrategySelector
from .plan import Plan

class DecisionManager:
    def __init__(self, data_manager: DataManager, algorithm_manager: AlgorithmManager):
        self.data_manager = data_manager
        self.algorithm_manager = algorithm_manager
        self._static_planning = StaticPlanningModule(data_manager, algorithm_manager)
        self._dynamic_scheduling = DynamicSchedulingModule(data_manager, algorithm_manager)
        self.strategy_selector = StrategySelector()

    def static_planning(self) -> Optional[Plan]:
        return self._static_planning.execute_planning()

    def dynamic_scheduling(self, new_tasks: Optional[List[Task]] = None, 
                          strategy: str = "auto") -> List[Dict]:
        if new_tasks:
            for task in new_tasks:
                self._dynamic_scheduling.receive_new_task(task)

        if strategy == "auto":
            tasks = self.data_manager.get_pending_tasks()
            vehicles = self.data_manager.get_vehicles()
            global_params = {
                "warehouse_pos": self.data_manager.warehouse_position,
                "grid_unit": 1.0,
                "timestamp": int(datetime.now().timestamp())
            }
            strategy = self.strategy_selector.select_strategy(tasks, vehicles, global_params)

        commands = self._dynamic_scheduling.process_pending_tasks(strategy)

        return commands

    def manage_battery(self, vehicle: Vehicle) -> Optional[Dict]:
        if vehicle.battery < vehicle.max_battery * 0.2:
            charging_stations = self.data_manager.get_charging_stations()
            station_id = self.data_manager.path_calculator.find_nearest_charging_station(
                vehicle, charging_stations
            )

            if station_id:
                command = {
                    "vehicle_id": vehicle.id,
                    "action_type": "charge",
                    "assigned_tasks": [],
                    "path": [(vehicle.position.x, vehicle.position.y)],
                    "charging_station_id": station_id,
                    "estimated_time": 0
                }

                station = self.data_manager.get_charging_station(station_id)
                if station:
                    command["path"] = [(vehicle.position.x, vehicle.position.y), 
                                       (station.position.x, station.position.y)]

                return command

        return None

    def coordinate_vehicles(self, task: Task) -> List[Dict]:
        idle_vehicles = self.data_manager.get_idle_vehicles()

        if not idle_vehicles:
            return []

        suitable_vehicles = [
            v for v in idle_vehicles
            if (v.max_load - v.current_load) >= task.weight
        ]

        if not suitable_vehicles:
            return []

        if task.weight > sum(v.max_load - v.current_load for v in suitable_vehicles):
            return []

        commands = []
        remaining_weight = task.weight

        for vehicle in sorted(suitable_vehicles, 
                             key=lambda v: self.data_manager.path_calculator.calculate_distance_from_positions(
                                 [v.position, task.position]
                             )):
            if remaining_weight <= 0:
                break

            available_load = vehicle.max_load - vehicle.current_load
            load_to_assign = min(available_load, remaining_weight)

            if load_to_assign > 0:
                # 完整路径：仓库 -> 任务 -> 仓库
                warehouse_pos = self.data_manager.warehouse_position
                complete_path = [
                    (warehouse_pos.x, warehouse_pos.y),  # 从仓库出发
                    (task.position.x, task.position.y),     # 到达任务点
                    (warehouse_pos.x, warehouse_pos.y)   # 返回仓库
                ]
                
                # 计算预计完成时间（基于车辆速度）
                estimated_time = self.data_manager.path_calculator.calculate_task_completion_time(
                    complete_path, 
                    vehicle_speed=vehicle.speed, 
                    unloading_time=30.0
                )
                
                command = {
                    "vehicle_id": vehicle.id,
                    "action_type": "transport",
                    "assigned_tasks": [task.id],
                    "path": complete_path,
                    "charging_station_id": None,
                    "estimated_time": estimated_time
                }
                commands.append(command)
                remaining_weight -= load_to_assign

        return commands

    def get_system_status(self) -> Dict:
        tasks = self.data_manager.get_tasks()
        vehicles = self.data_manager.get_vehicles()
        charging_stations = self.data_manager.get_charging_stations()

        pending_tasks = [t for t in tasks if t.status == TaskStatus.PENDING]
        idle_vehicles = [v for v in vehicles if v.status == VehicleStatus.IDLE]

        return {
            "timestamp": int(datetime.now().timestamp()),
            "total_tasks": len(tasks),
            "pending_tasks": len(pending_tasks),
            "completed_tasks": len([t for t in tasks if t.status == TaskStatus.COMPLETED]),
            "timeout_tasks": len([t for t in tasks if t.status == TaskStatus.TIMEOUT]),
            "total_vehicles": len(vehicles),
            "idle_vehicles": len(idle_vehicles),
            "transporting_vehicles": len([v for v in vehicles if v.status == VehicleStatus.TRANSPORTING]),
            "charging_vehicles": len([v for v in vehicles if v.status == VehicleStatus.CHARGING]),
            "total_charging_stations": len(charging_stations),
            "active_commands": len(self._dynamic_scheduling.get_active_commands()),
            "current_strategy": self.strategy_selector.get_best_strategy()
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

            vehicle = self.data_manager.get_vehicle(task.assigned_vehicle_id) if task.assigned_vehicle_id else None
            if vehicle:
                distance = self.data_manager.path_calculator.calculate_distance_from_positions(
                    [vehicle.position, task.position]
                )
                total_distance += distance

            if task.complete_time and task.deadline:
                if task.complete_time <= task.deadline:
                    total_score += 100
                else:
                    total_score -= 50

        avg_completion_time = total_completion_time / len(completed_tasks) if completed_tasks else 0.0

        return {
            "completion_rate": completion_rate,
            "avg_completion_time": avg_completion_time,
            "total_distance": total_distance,
            "total_score": total_score
        }
