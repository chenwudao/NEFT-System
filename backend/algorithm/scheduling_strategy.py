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
        warehouse_pos = global_params.get("warehouse_position", (0, 0))
        if isinstance(warehouse_pos, tuple):
            self.warehouse_pos = warehouse_pos
        else:
            try:
                self.warehouse_pos = (warehouse_pos.x, warehouse_pos.y)
            except Exception:
                self.warehouse_pos = (0, 0)
        self.grid_unit = global_params.get("grid_unit", 1.0)
        self.assigned_task_ids = set()
        self.assigned_vehicle_ids = set()
        self.commands = []

    # ------------------------------------------------------------------
    # 任务过滤 & 批量选取
    # ------------------------------------------------------------------

    def filter_feasible_tasks(self, vehicle: Vehicle) -> List[Task]:
        """过滤出当前车辆可接单的任务（未分配且载重可容纳）"""
        return [
            task for task in self.pending_tasks
            if task.status == TaskStatus.PENDING
               and task.id not in self.assigned_task_ids
               and task.weight <= vehicle.get_remaining_load()
        ]

    def select_batch_tasks(self, vehicle: Vehicle, main_task: Task,
                           feasible_tasks: List[Task], max_batch: int = 3) -> List[Task]:
        """在主任务基础上，尽量顺路打包附近的轻量任务"""
        candidate_tasks = [main_task]
        remaining_load = vehicle.get_remaining_load() - main_task.weight

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
                remaining_load -= task.weight

        return candidate_tasks

    def _check_batch_feasibility(self, vehicle: Vehicle, tasks: List[Task]) -> bool:
        total_weight = sum(task.weight for task in tasks)
        return total_weight <= vehicle.max_load

    # ------------------------------------------------------------------
    # 核心调度指令生成
    # ------------------------------------------------------------------

    def generate_vehicle_command(self, vehicle: Vehicle):
        """
        三阶段充电-调度决策：
          1. 电量充足 → 直接运输
          2. 电量不足但能到达充电站 → 发送充电指令
          3. 电量严重不足（连充电站都可能到不了）→ 仍发充电指令（就近充电）
        """
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
        path = self._build_transport_path(vehicle, candidate_tasks)

        if path is None:
            # 路径不可达，跳过此任务
            self.commands.append(self._generate_idle_command(vehicle))
            return

        if self._is_energy_sufficient(vehicle, path):
            # 电量充足：直接运输
            self.assigned_task_ids.update([t.id for t in candidate_tasks])
            self.commands.append(self._generate_transport_command(vehicle, candidate_tasks, path))
        else:
            # 电量不足：找最优充电站（考虑距离和排队压力）
            station_id = self._find_best_charging_station(vehicle)
            if station_id:
                self.commands.append(self._generate_charge_command(vehicle, station_id))
            else:
                self.commands.append(self._generate_idle_command(vehicle))

    def _is_energy_sufficient(self, vehicle: Vehicle, path: Optional[List[tuple]]) -> bool:
        """
        检查电量是否足以完成完整路程（包含回仓库）。
        path 已由 _build_transport_path 构造为含回仓节点，因此直接计算全程能耗。
        """
        if path is None or len(path) < 2:
            return False
        try:
            energy_needed = self.path_calculator.calculate_energy_consumption(vehicle, path)
            return vehicle.battery >= energy_needed
        except Exception:
            return False

    def _build_transport_path(self, vehicle: Vehicle, tasks: List[Task]) -> Optional[List[tuple]]:
        """构建运输路径：车辆当前位置 → 各任务点 → 仓库（已含回仓）
        
        Returns:
            完整路径，如果任何段无法到达则返回 None
        """
        if not tasks:
            return []

        route_points = [(vehicle.position.x, vehicle.position.y)]
        route_points.extend((t.position.x, t.position.y) for t in tasks)
        route_points.append(self.warehouse_pos)

        full_path: List[tuple] = []
        for i in range(len(route_points) - 1):
            try:
                segment = self.path_calculator.find_shortest_path(route_points[i], route_points[i + 1])
                if not segment:
                    return None  # 路径段为空，视为不可达
                if full_path and segment[0] == full_path[-1]:
                    full_path.extend(segment[1:])
                else:
                    full_path.extend(segment)
            except Exception:
                # 路径不可达（如网络不连通）
                return None

        return full_path if full_path else None

    def _find_best_charging_station(self, vehicle: Vehicle) -> Optional[str]:
        """
        找最优充电站（改进版：综合考虑图距离和排队压力）。
        综合评分 = 距离 × 0.7 + 排队压力 × max_dist × 0.3
        """
        if not self.charging_stations:
            return None

        vehicle_pos = (vehicle.position.x, vehicle.position.y)
        distances = []
        for station in self.charging_stations:
            try:
                dist = self.path_calculator.calculate_pair_distance(
                    vehicle_pos,
                    (station.position.x, station.position.y)
                )
                distances.append(dist)
            except Exception:
                distances.append(float('inf'))

        max_dist = max(d for d in distances if d < float('inf')) or 1.0

        best_station = None
        best_score = float('inf')
        for station, dist in zip(self.charging_stations, distances):
            if dist == float('inf'):
                continue
            score = dist * 0.7 + station.load_pressure * max_dist * 0.3
            if score < best_score:
                best_score = score
                best_station = station.id

        return best_station

    @abstractmethod
    def sort_tasks(self, vehicle: Vehicle, feasible_tasks: List[Task]) -> List[Task]:
        pass

    @abstractmethod
    def execute(self) -> List[Dict]:
        pass

    # ------------------------------------------------------------------
    # 指令生成辅助方法
    # ------------------------------------------------------------------

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
                                    path: List[tuple]) -> Dict:
        """
        生成运输指令。
        修复 B1：使用 vehicle.speed（m/s）计算 estimated_time，不再用硬编码 0.1 度/s。
        """
        try:
            total_dist = self.path_calculator.calculate_distance(path)
            speed = vehicle.speed if vehicle.speed > 0 else 10.0  # m/s
            estimated_time = int(total_dist / speed)
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

    def _generate_charge_command(self, vehicle: Vehicle, station_id: Optional[str]) -> Dict:
        """
        生成充电指令。
        修复 B1：行驶时间用 vehicle.speed（m/s）计算；充电时间用 vehicle.charging_power。
        """
        if station_id is None or not self.charging_stations:
            return self._generate_idle_command(vehicle)

        try:
            target_station = next((s for s in self.charging_stations if s.id == station_id), None)
            if not target_station:
                return self._generate_idle_command(vehicle)

            charge_path = self.path_calculator.find_shortest_path(
                (vehicle.position.x, vehicle.position.y),
                (target_station.position.x, target_station.position.y)
            )
            if not charge_path:
                charge_path = [
                    (vehicle.position.x, vehicle.position.y),
                    (target_station.position.x, target_station.position.y)
                ]

            speed = vehicle.speed if vehicle.speed > 0 else 10.0
            drive_dist = self.path_calculator.calculate_distance(charge_path)
            drive_time = drive_dist / speed

            # 充电时间：按情境感知阈值计算（默认充到80%）
            target_battery_pct = 80.0
            charge_needed = (target_battery_pct / 100.0 * vehicle.max_battery) - vehicle.battery
            charging_power = vehicle.charging_power if vehicle.charging_power > 0 else 0.022
            charge_time = max(0, charge_needed) / charging_power

            # 排队等待预估（每辆排队车辆等待一个充电周期）
            queue_wait = target_station.get_waiting_count() * charge_time
            estimated_time = int(drive_time + queue_wait + charge_time)

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
