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

        print(f"[DEBUG process_pending_tasks] {len(pending_tasks)} pending, {len(idle_vehicles)} idle")
        
        if not pending_tasks or not idle_vehicles:
            print(f"[DEBUG process_pending_tasks] No tasks or vehicles, returning empty")
            return []

        global_params = {
            "warehouse_position": self.data_manager.warehouse_position,
            "grid_unit": 1.0,
            "timestamp": int(datetime.now().timestamp())
        }

        try:
            commands = self.algorithm_manager.schedule_realtime(
                strategy, idle_vehicles, pending_tasks,
                charging_stations, global_params
            )
            print(f"[DEBUG process_pending_tasks] Generated {len(commands)} commands")
        except Exception as e:
            print(f"[ERROR process_pending_tasks] schedule_realtime failed: {e}")
            import traceback
            traceback.print_exc()
            return []

        self.active_commands.extend(commands)

        for command in commands:
            self._execute_command(command)

        return commands

    def run_commands(self, commands: List[Dict]) -> None:
        """Execute scheduling commands without running strategy logic (e.g. static plan)."""
        if not commands:
            return
        self.active_commands.extend(commands)
        for command in commands:
            self._execute_command(command)

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
            "path": self.data_manager.path_calculator.find_shortest_path(
                (vehicle.position.x, vehicle.position.y),
                (task.position.x, task.position.y)
            ) or [(vehicle.position.x, vehicle.position.y), (task.position.x, task.position.y)],
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
                # 进入运输阶段后，任务应明确进入 in_progress 状态。
                task = self.data_manager.get_task(task_id)
                if task:
                    task.update_status(TaskStatus.IN_PROGRESS)

            # 将调度指令路径写入车辆，供按速度推进位置和完成判定使用。
            command_path = command.get("path", [])
            vehicle.complete_path = command_path.copy() if command_path else []
            # 使用 data_manager 的方法更新状态，确保触发 WebSocket 通知
            self.data_manager.update_vehicle_status(vehicle_id, VehicleStatus.TRANSPORTING)

        elif action_type == "charge":
            station_id = command.get("charging_station_id")
            if station_id:
                self.data_manager.add_vehicle_to_charging_station(vehicle_id, station_id)

        elif action_type == "idle":
            self.data_manager.update_vehicle_status(vehicle_id, VehicleStatus.IDLE)

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
