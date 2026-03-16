from typing import List, Dict, Optional
from abc import ABC, abstractmethod
from backend.data.task import Task, TaskStatus, Position
from backend.data.vehicle import Vehicle, VehicleStatus
from backend.data.charging_station import ChargingStation
from backend.data.path_calculator import PathCalculator

class SchedulingStrategy(ABC):
    def __init__(self, idle_vehicles: List[Vehicle], pending_tasks: List[Task],
                 charging_stations: List[ChargingStation], global_params: Dict,
                 path_calculator: PathCalculator):
        self.idle_vehicles = idle_vehicles
        self.pending_tasks = pending_tasks
        self.charging_stations = charging_stations
        self.global_params = global_params
        self.path_calculator = path_calculator
        # 修复 KeyError，使用 warehouse_position 并添加异常处理
        warehouse_pos = global_params.get("warehouse_position", (0, 0))
        if isinstance(warehouse_pos, tuple):
            self.warehouse_pos = warehouse_pos
        else:
            try:
                self.warehouse_pos = (warehouse_pos.x, warehouse_pos.y)
            except:
                self.warehouse_pos = (0, 0)
        self.grid_unit = global_params.get("grid_unit", 1.0)
        self.assigned_task_ids = set()
        self.assigned_vehicle_ids = set()
        self.commands = []

    def filter_feasible_tasks(self, vehicle: Vehicle) -> List[Task]:
        return [
            task for task in self.pending_tasks
            if task.id not in self.assigned_task_ids
               and task.weight <= (vehicle.max_load - vehicle.current_load)
        ]

    def select_batch_tasks(self, vehicle: Vehicle, main_task: Task, 
                         feasible_tasks: List[Task], max_batch: int = 3) -> List[Task]:
        candidate_tasks = [main_task]
        remaining_load = vehicle.max_load - vehicle.current_load - main_task.weight

        if remaining_load <= 0:
            return candidate_tasks

        batch_candidates = [
            t for t in feasible_tasks
            if t.id not in self.assigned_task_ids
               and t.id != main_task.id
               and t.weight <= remaining_load
        ]

        if not batch_candidates:
            return candidate_tasks

        batch_candidates.sort(
            key=lambda t: self.path_calculator.calculate_distance_from_positions(
                [main_task.position, t.position]
            )
        )

        for task in batch_candidates:
            if len(candidate_tasks) >= max_batch:
                break
            if self._check_batch_feasibility(vehicle, candidate_tasks + [task]):
                candidate_tasks.append(task)

        return candidate_tasks

    def _check_batch_feasibility(self, vehicle: Vehicle, tasks: List[Task]) -> bool:
        total_weight = sum(task.weight for task in tasks)
        return total_weight <= vehicle.max_load

    def generate_vehicle_command(self, vehicle: Vehicle):
        feasible_tasks = self.filter_feasible_tasks(vehicle)

        if not feasible_tasks:
            self.commands.append(self._generate_idle_command(vehicle))
            return

        sorted_tasks = self.sort_tasks(vehicle, feasible_tasks)
        if not sorted_tasks:
            self.commands.append(self._generate_idle_command(vehicle))
            return

        main_task = sorted_tasks[0]
        candidate_tasks = self.select_batch_tasks(vehicle, main_task, feasible_tasks)

        task_positions = [(t.position.x, t.position.y) for t in candidate_tasks]
        path = [(vehicle.position.x, vehicle.position.y)] + task_positions + [self.warehouse_pos]

        if self._is_energy_sufficient(vehicle, path):
            self.assigned_task_ids.update([t.id for t in candidate_tasks])
            self.commands.append(self._generate_transport_command(vehicle, candidate_tasks, path))
        else:
            station_id = self._select_optimal_charging_station(vehicle)
            if station_id:
                self.commands.append(self._generate_charge_command(vehicle, station_id))
            else:
                self.commands.append(self._generate_idle_command(vehicle))

    def _is_energy_sufficient(self, vehicle: Vehicle, path: List[tuple]) -> bool:
        energy_needed = self.path_calculator.calculate_energy_consumption(vehicle, path)
        return vehicle.battery >= energy_needed

    def _select_optimal_charging_station(self, vehicle: Vehicle) -> Optional[str]:
        return self.path_calculator.find_nearest_charging_station(vehicle, self.charging_stations)

    @abstractmethod
    def sort_tasks(self, vehicle: Vehicle, feasible_tasks: List[Task]) -> List[Task]:
        pass

    @abstractmethod
    def execute(self) -> List[Dict]:
        pass

    def _generate_idle_command(self, vehicle: Vehicle) -> Dict:
        return {
            "vehicle_id": vehicle.id,
            "action_type": "idle",
            "assigned_tasks": [],
            "path": [],
            "charging_station_id": None,
            "estimated_time": 0
        }

    def _generate_transport_command(self, vehicle: Vehicle, tasks: List[Task], 
                                   path: List[tuple], vehicle_speed: float = 0.1) -> Dict:
        try:
            total_dist = self.path_calculator.calculate_distance(path)
            estimated_time = int(total_dist / vehicle_speed)
            return {
                "vehicle_id": vehicle.id,
                "action_type": "transport",
                "assigned_tasks": [t.id for t in tasks],
                "path": path,
                "charging_station_id": None,
                "estimated_time": estimated_time
            }
        except Exception as e:
            print(f"生成运输指令失败（车辆{vehicle.id}）：{e}")
            return self._generate_idle_command(vehicle)

    def _generate_charge_command(self, vehicle: Vehicle, station_id: Optional[str],
                                vehicle_speed: float = 0.1, charging_rate: float = 10.0) -> Dict:
        if station_id is None or not self.charging_stations:
            return self._generate_idle_command(vehicle)

        try:
            target_station = next((s for s in self.charging_stations if s.id == station_id), None)
            if not target_station:
                return self._generate_idle_command(vehicle)

            charge_path = [(vehicle.position.x, vehicle.position.y), 
                          (target_station.position.x, target_station.position.y)]
            
            drive_time = self.path_calculator.calculate_distance(charge_path) / vehicle_speed
            remaining_energy = vehicle.battery
            charge_needed = vehicle.max_battery - remaining_energy
            charge_time = charge_needed / charging_rate if charging_rate > 0 else 0
            estimated_time = int(drive_time + charge_time + target_station.queue_count * 5)

            return {
                "vehicle_id": vehicle.id,
                "action_type": "charge",
                "assigned_tasks": [],
                "path": charge_path,
                "charging_station_id": station_id,
                "estimated_time": estimated_time
            }
        except Exception as e:
            print(f"生成充电指令失败（车辆{vehicle.id}）：{e}")
            return self._generate_idle_command(vehicle)
