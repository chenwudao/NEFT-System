from typing import List, Dict, Optional, Callable
from datetime import datetime
import threading
import asyncio
import inspect
from .task import Task, TaskStatus, Position
from .vehicle import Vehicle, VehicleStatus
from .charging_station import ChargingStation
from .path_calculator import PathCalculator

class DataManager:
    def __init__(self):
        self.tasks: Dict[int, Task] = {}
        self.vehicles: Dict[int, Vehicle] = {}
        self.charging_stations: Dict[str, ChargingStation] = {}
        self.path_calculator = PathCalculator()
        self.warehouse_position = Position(x=0, y=0)
        self.task_update_callbacks: List[Callable] = []
        self.vehicle_update_callbacks: List[Callable] = []
        self.station_update_callbacks: List[Callable] = []
        self.lock = threading.Lock()

    def set_warehouse_position(self, position: Position):
        self.warehouse_position = position

    def get_warehouse_position(self) -> Position:
        return self.warehouse_position

    def is_at_warehouse(self, position: Position, tolerance: float = 5.0) -> bool:
        """检查车辆是否在仓库位置"""
        distance = ((position.x - self.warehouse_position.x) ** 2 + 
                   (position.y - self.warehouse_position.y) ** 2) ** 0.5
        return distance <= tolerance

    def get_tasks(self) -> List[Task]:
        with self.lock:
            return list(self.tasks.values())

    def get_pending_tasks(self) -> List[Task]:
        with self.lock:
            return [task for task in self.tasks.values() if task.status == TaskStatus.PENDING]

    def get_task(self, task_id: int) -> Optional[Task]:
        with self.lock:
            return self.tasks.get(task_id)

    def add_task(self, task: Task):
        with self.lock:
            self.tasks[task.id] = task
            self._notify_task_update(task)

    def update_task_status(self, task_id: int, status: TaskStatus):
        with self.lock:
            if task_id in self.tasks:
                self.tasks[task_id].update_status(status)
                self._notify_task_update(self.tasks[task_id])

    def assign_task_to_vehicle(self, task_id: int, vehicle_id: int):
        with self.lock:
            if task_id in self.tasks and vehicle_id in self.vehicles:
                self.tasks[task_id].assigned_vehicle_id = vehicle_id
                self.tasks[task_id].update_status(TaskStatus.ASSIGNED)
                self.vehicles[vehicle_id].add_task(task_id)
                self._notify_task_update(self.tasks[task_id])
                self._notify_vehicle_update(self.vehicles[vehicle_id])

    def get_vehicles(self) -> List[Vehicle]:
        with self.lock:
            return list(self.vehicles.values())

    def get_idle_vehicles(self) -> List[Vehicle]:
        with self.lock:
            return [vehicle for vehicle in self.vehicles.values() if vehicle.status == VehicleStatus.IDLE]

    def get_vehicle(self, vehicle_id: int) -> Optional[Vehicle]:
        with self.lock:
            return self.vehicles.get(vehicle_id)

    def add_vehicle(self, vehicle: Vehicle):
        with self.lock:
            self.vehicles[vehicle.id] = vehicle
            self._notify_vehicle_update(vehicle)

    def update_vehicle_status(self, vehicle_id: int, status: VehicleStatus):
        with self.lock:
            if vehicle_id in self.vehicles:
                self.vehicles[vehicle_id].update_status(status)
                self._notify_vehicle_update(self.vehicles[vehicle_id])

    def update_vehicle_position(self, vehicle_id: int, position: Position):
        with self.lock:
            if vehicle_id in self.vehicles:
                self.vehicles[vehicle_id].update_position(position)
                self._notify_vehicle_update(self.vehicles[vehicle_id])

    def update_vehicle_battery(self, vehicle_id: int, battery: float):
        with self.lock:
            if vehicle_id in self.vehicles:
                self.vehicles[vehicle_id].update_battery(battery)
                self._notify_vehicle_update(self.vehicles[vehicle_id])

    def update_vehicle_load(self, vehicle_id: int, load: float):
        with self.lock:
            if vehicle_id in self.vehicles:
                self.vehicles[vehicle_id].update_load(load)
                self._notify_vehicle_update(self.vehicles[vehicle_id])

    def get_charging_stations(self) -> List[ChargingStation]:
        with self.lock:
            return list(self.charging_stations.values())

    def get_charging_station(self, station_id: str) -> Optional[ChargingStation]:
        with self.lock:
            return self.charging_stations.get(station_id)

    def add_charging_station(self, station: ChargingStation):
        with self.lock:
            self.charging_stations[station.id] = station
            self._notify_station_update(station)

    def update_charging_station_status(self, station_id: str, queue_count: int, charging_vehicles: List[int]):
        with self.lock:
            if station_id in self.charging_stations:
                self.charging_stations[station_id].queue_count = queue_count
                self.charging_stations[station_id].charging_vehicles = charging_vehicles
                self.charging_stations[station_id].update_load_pressure()
                self._notify_station_update(self.charging_stations[station_id])

    def add_vehicle_to_charging_station(self, vehicle_id: int, station_id: str):
        with self.lock:
            if station_id in self.charging_stations and vehicle_id in self.vehicles:
                self.charging_stations[station_id].add_vehicle(vehicle_id)
                self.vehicles[vehicle_id].charging_station_id = station_id
                self.vehicles[vehicle_id].update_status(VehicleStatus.CHARGING)
                self._notify_station_update(self.charging_stations[station_id])
                self._notify_vehicle_update(self.vehicles[vehicle_id])

    def remove_vehicle_from_charging_station(self, vehicle_id: int, station_id: str):
        with self.lock:
            if station_id in self.charging_stations and vehicle_id in self.vehicles:
                self.charging_stations[station_id].remove_vehicle(vehicle_id)
                self.vehicles[vehicle_id].charging_station_id = None
                self.vehicles[vehicle_id].update_status(VehicleStatus.IDLE)
                self._notify_station_update(self.charging_stations[station_id])
                self._notify_vehicle_update(self.vehicles[vehicle_id])

    def get_path_calculator(self) -> PathCalculator:
        return self.path_calculator

    def get_map_data(self) -> Dict:
        with self.lock:
            return {
                "warehouse_position": {"x": self.warehouse_position.x, "y": self.warehouse_position.y},
                "task_positions": [{"id": task.id, "x": task.position.x, "y": task.position.y} for task in self.tasks.values()],
                "vehicle_positions": [{"id": vehicle.id, "x": vehicle.position.x, "y": vehicle.position.y} for vehicle in self.vehicles.values()],
                "station_positions": [{"id": station.id, "x": station.position.x, "y": station.position.y} for station in self.charging_stations.values()]
            }

    def register_task_update_callback(self, callback: Callable):
        self.task_update_callbacks.append(callback)

    def register_vehicle_update_callback(self, callback: Callable):
        self.vehicle_update_callbacks.append(callback)

    def register_station_update_callback(self, callback: Callable):
        self.station_update_callbacks.append(callback)

    def _notify_task_update(self, task: Task):
        for callback in self.task_update_callbacks:
            try:
                if inspect.iscoroutinefunction(callback):
                    asyncio.create_task(callback(task))
                else:
                    callback(task)
            except Exception as e:
                print(f"Error in task update callback: {e}")

    def _notify_vehicle_update(self, vehicle: Vehicle):
        for callback in self.vehicle_update_callbacks:
            try:
                if inspect.iscoroutinefunction(callback):
                    asyncio.create_task(callback(vehicle))
                else:
                    callback(vehicle)
            except Exception as e:
                print(f"Error in vehicle update callback: {e}")

    def _notify_station_update(self, station: ChargingStation):
        for callback in self.station_update_callbacks:
            try:
                if inspect.iscoroutinefunction(callback):
                    asyncio.create_task(callback(station))
                else:
                    callback(station)
            except Exception as e:
                print(f"Error in station update callback: {e}")

    def calculate_complete_path(self, task_id: int, vehicle_id: int) -> dict:
        """
        计算完整路径：仓库 → 任务点 → 仓库
        
        参数:
            task_id: 任务ID
            vehicle_id: 车辆ID
        
        返回:
            complete_path_info: 完整路径信息
        """
        with self.lock:
            task = self.tasks.get(task_id)
            vehicle = self.vehicles.get(vehicle_id)
            
            if not task or not vehicle:
                return None
            
            # 计算完整路径
            complete_path, total_distance = self.path_calculator.calculate_complete_path(
                self.warehouse_position, task.position
            )
            
            # 计算电量消耗
            energy_consumption, is_feasible = self.path_calculator.calculate_energy_consumption_for_complete_path(
                vehicle, complete_path
            )
            
            # 计算预计完成时间
            estimated_completion_time = self.path_calculator.calculate_task_completion_time(complete_path)
            
            # 更新任务的完整路径信息
            task.complete_path = [Position(x=p[0], y=p[1]) for p in complete_path]
            task.complete_path_distance = total_distance
            task.estimated_completion_time = estimated_completion_time
            
            return {
                "task_id": task_id,
                "vehicle_id": vehicle_id,
                "complete_path": complete_path,
                "total_distance": total_distance,
                "energy_consumption": energy_consumption,
                "is_feasible": is_feasible,
                "estimated_completion_time": estimated_completion_time
            }

    def check_and_complete_task(self, vehicle_id: int) -> List[Task]:
        """
        检查并完成任务
        
        完成条件：
        1. 车辆已到达任务点并完成配送
        2. 车辆已从任务点返回仓库
        3. 车辆状态更新为空闲
        
        参数:
            vehicle_id: 车辆ID
        
        返回:
            completed_tasks: 已完成的任务列表
        """
        with self.lock:
            vehicle = self.vehicles.get(vehicle_id)
            if not vehicle:
                return []
            
            completed_tasks = []
            
            # 检查车辆是否在仓库
            if not self.is_at_warehouse(vehicle.position):
                return completed_tasks
            
            # 检查所有进行中的任务
            for task_id in vehicle.assigned_task_ids[:]:
                task = self.tasks.get(task_id)
                if not task:
                    continue
                
                # 检查任务是否完成
                if task.status == TaskStatus.IN_PROGRESS:
                    # 计算实际完成时间
                    completion_time = int(datetime.now().timestamp())
                    actual_completion_time = completion_time - task.start_time if task.start_time else 0
                    
                    # 更新任务状态
                    task.status = TaskStatus.COMPLETED
                    task.complete_time = completion_time
                    
                    # 计算任务得分
                    task.score = self.path_calculator.calculate_task_score(
                        task, completion_time, task.complete_path_distance
                    )
                    task.is_on_time = completion_time <= task.deadline
                    
                    # 更新车辆状态
                    vehicle.remove_task(task_id)
                    vehicle.total_distance_traveled += task.complete_path_distance
                    
                    completed_tasks.append(task)
                    self._notify_task_update(task)
            
            # 如果没有进行中的任务了，更新车辆状态为空闲
            if not any(self.tasks.get(tid).status == TaskStatus.IN_PROGRESS 
                      for tid in vehicle.assigned_task_ids if tid in self.tasks):
                vehicle.update_status(VehicleStatus.IDLE)
                vehicle.complete_path = []
                vehicle.path_progress = 0.0
                vehicle.energy_consumption = 0.0
                self._notify_vehicle_update(vehicle)
            
            return completed_tasks

    def update_vehicle_path_progress(self, vehicle_id: int, current_position: Position):
        """
        更新车辆路径进度
        
        参数:
            vehicle_id: 车辆ID
            current_position: 当前位置
        """
        with self.lock:
            vehicle = self.vehicles.get(vehicle_id)
            if not vehicle or not vehicle.complete_path:
                return
            
            # 计算路径进度
            total_distance = 0.0
            traveled_distance = 0.0
            
            for i in range(len(vehicle.complete_path) - 1):
                from_pos = vehicle.complete_path[i]
                to_pos = vehicle.complete_path[i + 1]
                segment_distance = ((to_pos[0] - from_pos[0]) ** 2 + 
                                  (to_pos[1] - from_pos[1]) ** 2) ** 0.5
                total_distance += segment_distance
                
                # 计算已行驶距离
                if i < len(vehicle.complete_path) - 2:
                    traveled_distance += segment_distance
                else:
                    # 最后一段，计算当前位置到起点的距离
                    current_dist = ((current_position.x - from_pos[0]) ** 2 + 
                                  (current_position.y - from_pos[1]) ** 2) ** 0.5
                    traveled_distance += min(current_dist, segment_distance)
            
            if total_distance > 0:
                vehicle.path_progress = min(1.0, traveled_distance / total_distance)
            
            self._notify_vehicle_update(vehicle)

    def update_vehicle_position_by_speed(self, vehicle_id: int, time_delta: float = 1.0):
        """
        基于速度和时间更新车辆位置
        
        参数:
            vehicle_id: 车辆ID
            time_delta: 时间增量（秒）
        """
        with self.lock:
            vehicle = self.vehicles.get(vehicle_id)
            if not vehicle or not vehicle.complete_path or len(vehicle.complete_path) < 2:
                return
            
            # 只更新正在运输中的车辆
            if vehicle.status != VehicleStatus.TRANSPORTING:
                return
            
            # 计算在时间增量内可以移动的距离
            distance_to_move = vehicle.speed * time_delta
            
            # 沿路径移动车辆
            remaining_distance = distance_to_move
            current_pos = vehicle.position
            
            for i in range(len(vehicle.complete_path) - 1):
                from_pos = vehicle.complete_path[i]
                to_pos = vehicle.complete_path[i + 1]
                
                # 处理路径格式
                from_x = from_pos[0] if isinstance(from_pos, tuple) else from_pos.x
                from_y = from_pos[1] if isinstance(from_pos, tuple) else from_pos.y
                to_x = to_pos[0] if isinstance(to_pos, tuple) else to_pos.x
                to_y = to_pos[1] if isinstance(to_pos, tuple) else to_pos.y
                
                # 计算当前路段的长度
                segment_distance = ((to_x - from_x) ** 2 + (to_y - from_y) ** 2) ** 0.5
                
                # 计算当前位置到路段起点的距离
                dist_to_start = ((current_pos.x - from_x) ** 2 + (current_pos.y - from_y) ** 2) ** 0.5
                
                # 如果当前位置不在这个路段，跳过
                if dist_to_start > segment_distance:
                    continue
                
                # 计算当前位置到路段终点的距离
                dist_to_end = segment_distance - dist_to_start
                
                if remaining_distance <= dist_to_end:
                    # 在当前路段内移动
                    progress = remaining_distance / segment_distance
                    new_x = current_pos.x + (to_x - current_pos.x) * progress
                    new_y = current_pos.y + (to_y - current_pos.y) * progress
                    vehicle.update_position(Position(x=new_x, y=new_y))
                    vehicle.total_distance_traveled += remaining_distance
                    
                    # 更新电池消耗
                    energy_consumed = remaining_distance * vehicle.unit_energy_consumption
                    vehicle.battery = max(0, vehicle.battery - energy_consumed)
                    vehicle.energy_consumption += energy_consumed
                    break
                else:
                    # 移动到路段终点，继续下一段
                    remaining_distance -= dist_to_end
                    current_pos = Position(x=to_x, y=to_y)
                    vehicle.update_position(current_pos)
                    vehicle.total_distance_traveled += dist_to_end
                    
                    # 更新电池消耗
                    energy_consumed = dist_to_start * vehicle.unit_energy_consumption
                    vehicle.battery = max(0, vehicle.battery - energy_consumed)
                    vehicle.energy_consumption += energy_consumed
            
            # 更新路径进度
            self.update_vehicle_path_progress(vehicle_id, vehicle.position)
            
            # 检查是否到达终点
            if vehicle.path_progress >= 1.0:
                # 车辆到达终点，重置状态
                vehicle.update_status(VehicleStatus.IDLE)
                vehicle.path_progress = 0.0
                vehicle.complete_path = []
                
                # 检查并完成任务
                completed_tasks = self.check_and_complete_task(vehicle_id)
                if completed_tasks:
                    for task in completed_tasks:
                        print(f"Vehicle {vehicle_id} completed task {task.id}")
            
            self._notify_vehicle_update(vehicle)

    def get_system_state(self) -> Dict:
        with self.lock:
            # 生成默认地图数据
            map_nodes = []
            map_edges = []
            
            # 添加一些默认节点
            for i in range(5):
                for j in range(5):
                    map_nodes.append({"x": i * 200, "y": j * 200})
            
            # 添加一些默认边
            for i in range(5):
                for j in range(4):
                    # 水平边
                    map_edges.append([i * 5 + j, i * 5 + j + 1])
                    # 垂直边
                    if i < 4:
                        map_edges.append([i * 5 + j, (i + 1) * 5 + j])
            
            # 计算任务完成率
            total_tasks = len(self.tasks)
            completed_tasks = len([task for task in self.tasks.values() if task.status == TaskStatus.COMPLETED])
            completion_rate = completed_tasks / total_tasks if total_tasks > 0 else 0.0
            
            # 计算车辆利用率
            total_vehicles = len(self.vehicles)
            busy_vehicles = len([vehicle for vehicle in self.vehicles.values() if vehicle.status != VehicleStatus.IDLE])
            vehicle_utilization = busy_vehicles / total_vehicles if total_vehicles > 0 else 0.0
            
            # 简单的得分计算
            total_score = completed_tasks * 10  # 每个完成的任务得10分
            
            return {
                "timestamp": int(datetime.now().timestamp()),
                "tasks": [task.to_dict() for task in self.tasks.values()],
                "vehicles": [vehicle.to_dict() for vehicle in self.vehicles.values()],
                "charging_stations": [station.to_dict() for station in self.charging_stations.values()],
                "warehouse_position": {"x": self.warehouse_position.x, "y": self.warehouse_position.y},
                "map_nodes": map_nodes,
                "map_edges": map_edges,
                "total_score": total_score,
                "completion_rate": completion_rate,
                "vehicle_utilization": vehicle_utilization
            }
