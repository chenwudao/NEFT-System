from typing import List, Dict, Optional
from datetime import datetime
from backend.data.data_manager import DataManager
from backend.data.task import Task, TaskStatus
from backend.data.vehicle import Vehicle, VehicleStatus
from backend.data.charging_station import ChargingStation
from backend.data.position import Position
from backend.algorithm.algorithm_manager import AlgorithmManager

class DynamicSchedulingModule:
    def __init__(self, data_manager: DataManager, algorithm_manager: AlgorithmManager):
        self.data_manager = data_manager
        self.algorithm_manager = algorithm_manager
        self.pending_tasks: List[Task] = []
        self.active_commands: List[Dict] = []

    def receive_new_task(self, task: Task):
        self.pending_tasks.append(task)
        self.data_manager.add_task(task)

    def process_pending_tasks(self, strategy: str = "auto") -> List[Dict]:
        idle_vehicles = self.data_manager.get_idle_vehicles()
        charging_stations = self.data_manager.get_charging_stations()
        
        # 从data_manager获取待处理任务
        pending_tasks = [task for task in self.data_manager.get_tasks() if task.status == TaskStatus.PENDING]

        if not pending_tasks or not idle_vehicles:
            return []

        global_params = {
            "warehouse_pos": self.data_manager.warehouse_position,
            "grid_unit": 1.0,
            "timestamp": int(datetime.now().timestamp())
        }

        commands = self.algorithm_manager.schedule_realtime(
            strategy, idle_vehicles, pending_tasks,
            charging_stations, global_params
        )

        self.active_commands.extend(commands)

        for command in commands:
            self._execute_command(command)

        return commands

    def handle_urgent_task(self, task: Task) -> Optional[Dict]:
        idle_vehicles = self.data_manager.get_idle_vehicles()

        if not idle_vehicles:
            return None

        suitable_vehicles = [
            v for v in idle_vehicles
            if (v.max_load - v.current_load) >= task.weight
        ]

        if not suitable_vehicles:
            return None

        suitable_vehicles.sort(
            key=lambda v: self.data_manager.path_calculator.calculate_distance_from_positions(
                [v.position, task.position]
            )
        )

        vehicle = suitable_vehicles[0]

        command = {
            "vehicle_id": vehicle.id,
            "action_type": "transport",
            "assigned_tasks": [task.id],
            "path": [(vehicle.position.x, vehicle.position.y), (task.position.x, task.position.y)],
            "charging_station_id": None,
            "estimated_time": 0
        }

        self.active_commands.append(command)
        self._execute_command(command)

        return command

    def adjust_scheduling(self) -> List[Dict]:
        adjusted_commands = []

        for command in self.active_commands[:]:
            if command["action_type"] == "transport":
                vehicle = self.data_manager.get_vehicle(command["vehicle_id"])
                if vehicle and vehicle.status != VehicleStatus.TRANSPORTING:
                    self.active_commands.remove(command)

        return adjusted_commands

    def _execute_command(self, command: Dict):
        vehicle_id = command["vehicle_id"]
        action_type = command["action_type"]

        vehicle = self.data_manager.get_vehicle(vehicle_id)
        if not vehicle:
            return

        if action_type == "transport":
            task_ids = command.get("assigned_tasks", [])
            for task_id in task_ids:
                self.data_manager.assign_task_to_vehicle(task_id, vehicle_id)
            vehicle.update_status(VehicleStatus.TRANSPORTING)

        elif action_type == "charge":
            station_id = command.get("charging_station_id")
            if station_id:
                self.data_manager.add_vehicle_to_charging_station(vehicle_id, station_id)

        elif action_type == "idle":
            vehicle.update_status(VehicleStatus.IDLE)

    def get_active_commands(self) -> List[Dict]:
        return self.active_commands.copy()

    def clear_completed_commands(self):
        self.active_commands = [
            cmd for cmd in self.active_commands
            if self._is_command_active(cmd)
        ]

    def _is_command_active(self, command: Dict) -> bool:
        vehicle = self.data_manager.get_vehicle(command["vehicle_id"])
        if not vehicle:
            return False

        if command["action_type"] == "transport":
            return vehicle.status == VehicleStatus.TRANSPORTING
        elif command["action_type"] == "charge":
            return vehicle.status == VehicleStatus.CHARGING
        else:
            return False
