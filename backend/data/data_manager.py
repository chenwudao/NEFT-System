from typing import List, Dict, Optional, Callable
from datetime import datetime
import threading
import asyncio
import inspect
import logging
import random
from .task import Task, TaskStatus, Position
from .vehicle import Vehicle, VehicleStatus
from .charging_station import ChargingStation
from .path_calculator import PathCalculator
from .geo_display import enrich_wgs84_point_dict
from backend.config import config

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
        # 使用可重入锁，避免同一线程内的嵌套调用导致死锁。
        self.lock = threading.RLock()
        self.logger = logging.getLogger(__name__)
        self._initialize_routing_graph_if_enabled()

    def _initialize_routing_graph_if_enabled(self):
        """初始化图路由。支持完整OSM路网或主干路精简版。"""
        routing_config = config.get_routing_config()
        graph_config = routing_config.get("graph", {})
        
        # 延迟导入 osmnx，避免模块级循环依赖
        try:
            import osmnx as ox
            import networkx as nx
        except ImportError as e:
            raise RuntimeError(f"osmnx must be installed for graph routing: {e}")

        place_name = graph_config.get("place_name")
        network_type = graph_config.get("network_type", "drive")
        main_roads_only = graph_config.get("main_roads_only", True)  # 默认使用主干路精简版
        
        try:
            ox.settings.use_cache = True
            
            if main_roads_only:
                # 主干路精简版：只保留高等级道路
                self.logger.info("Initializing graph with MAIN ROADS ONLY mode...")
                
                # 先获取行政边界
                gdf = ox.geocode_to_gdf(place_name)
                if gdf.empty:
                    raise RuntimeError(f"Cannot geocode place: {place_name}")
                
                # 选面积最大的面
                gdf_metric = gdf.to_crs("EPSG:3857").copy()
                gdf_metric["_area"] = gdf_metric.geometry.area
                largest_idx = gdf_metric["_area"].idxmax()
                polygon = gdf.loc[largest_idx].geometry
                
                # 主干路过滤条件
                custom_filter = '["highway"~"motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link"]'
                
                graph = ox.graph_from_polygon(
                    polygon,
                    network_type=network_type,
                    simplify=True,
                    retain_all=False,
                    truncate_by_edge=True,
                    custom_filter=custom_filter
                )
                
                # PathCalculator 会自动保留最大连通分量，这里不需要额外处理
                self.logger.info(f"Main roads graph initialized: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")
            else:
                # 完整OSM路网
                graph = ox.graph_from_place(place_name, network_type=network_type)
                self.logger.info("Full OSM graph initialized for place=%s network_type=%s", place_name, network_type)
            
            self.path_calculator.set_networkx_graph(graph)
        except Exception as exc:
            raise RuntimeError(f"Failed to initialize graph routing (REQUIRED): {exc}") from exc

    def set_warehouse_position(self, position: Position):
        self.warehouse_position = position

    def get_warehouse_position(self) -> Position:
        return self.warehouse_position

    def is_at_warehouse(self, position: Position, tolerance_m: float = 120.0) -> bool:
        """检查车辆是否在仓库附近（图距离，米）。"""
        try:
            d = self.path_calculator.calculate_pair_distance(
                (position.x, position.y),
                (self.warehouse_position.x, self.warehouse_position.y),
            )
            return d <= tolerance_m
        except Exception:
            return (
                abs(position.x - self.warehouse_position.x) + abs(position.y - self.warehouse_position.y)
            ) < 1e-4

    def sample_graph_position(self, rng: Optional[random.Random] = None) -> Position:
        xy = self.path_calculator.sample_random_node_xy(rng=rng)
        return Position(x=xy[0], y=xy[1])

    def sample_graph_positions_unique(self, count: int, rng: Optional[random.Random] = None) -> List[Position]:
        """Sample up to count distinct node positions (may return fewer if graph small).
        
        确保采样的节点与仓库位置连通。
        """
        r = rng or random
        
        # 获取仓库节点ID
        if self.warehouse_position is None:
            # 如果没有仓库位置，使用普通采样
            nodes = self.path_calculator.iter_valid_node_xy()
            if not nodes:
                raise RuntimeError("No graph nodes for sampling")
            picks = r.sample(nodes, k=min(count, len(nodes)))
            return [Position(x=p[0], y=p[1]) for p in picks]
        
        # 获取与仓库连通的节点
        warehouse_xy = (self.warehouse_position.x, self.warehouse_position.y)
        connected_nodes = self.path_calculator.get_connected_nodes_xy(warehouse_xy)
        
        if not connected_nodes:
            raise RuntimeError("No connected graph nodes for sampling")
        
        picks = r.sample(connected_nodes, k=min(count, len(connected_nodes)))
        return [Position(x=p[0], y=p[1]) for p in picks]

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
        """添加车辆到充电站。根据槽位决定状态：CHARGING（充电中）或 WAITING_CHARGE（排队中）。"""
        with self.lock:
            if station_id not in self.charging_stations or vehicle_id not in self.vehicles:
                return
            station = self.charging_stations[station_id]
            vehicle = self.vehicles[vehicle_id]
            result = station.add_vehicle(vehicle_id)
            vehicle.charging_station_id = station_id
            if result == 'charging':
                vehicle.update_status(VehicleStatus.CHARGING)
            elif result == 'waiting':
                vehicle.update_status(VehicleStatus.WAITING_CHARGE)
            # result == 'existing': 已在站内，不变
            self._notify_station_update(station)
            self._notify_vehicle_update(vehicle)

    def remove_vehicle_from_charging_station(self, vehicle_id: int, station_id: str):
        """移除充电完成的车辆；若等待队列非空，自动晋升队首车辆为 CHARGING。"""
        with self.lock:
            if station_id not in self.charging_stations or vehicle_id not in self.vehicles:
                return
            station = self.charging_stations[station_id]
            vehicle = self.vehicles[vehicle_id]
            promoted_id = station.remove_vehicle(vehicle_id)
            vehicle.charging_station_id = None
            vehicle.update_status(VehicleStatus.IDLE)
            self._notify_station_update(station)
            self._notify_vehicle_update(vehicle)
            # 晋升等待队列中的车辆
            if promoted_id is not None and promoted_id in self.vehicles:
                promoted_vehicle = self.vehicles[promoted_id]
                promoted_vehicle.update_status(VehicleStatus.CHARGING)
                self._notify_vehicle_update(promoted_vehicle)
                self.logger.info("Vehicle %s promoted from waiting_queue to CHARGING at station %s", promoted_id, station_id)

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

                    # 若完整路径距离未写入，按当前完整路径补齐，确保实验指标可统计。
                    if task.complete_path_distance <= 0 and vehicle.complete_path and len(vehicle.complete_path) >= 2:
                        normalized_path = []
                        for p in vehicle.complete_path:
                            if isinstance(p, tuple):
                                normalized_path.append((p[0], p[1]))
                            else:
                                normalized_path.append((p.x, p.y))
                        task.complete_path_distance = self.path_calculator.calculate_distance(normalized_path)

                    # 使用状态机更新，保证 complete_time 被统一写入。
                    task.update_status(TaskStatus.COMPLETED)
                    completion_time = task.complete_time if task.complete_time else completion_time
                    
                    # 计算任务得分（使用统一的评分机制）
                    task.score = self.path_calculator.calculate_task_score(
                        task, completion_time, task.complete_path_distance,
                        vehicle=vehicle
                    )
                    task.is_on_time = completion_time <= task.deadline

                    # 修复 B2：任务完成后归还车辆载重（原代码缺失，导致车辆永久满载）
                    vehicle.update_load(max(0.0, vehicle.current_load - task.weight))

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
                from_xy = (from_pos[0], from_pos[1]) if isinstance(from_pos, tuple) else (from_pos.x, from_pos.y)
                to_xy = (to_pos[0], to_pos[1]) if isinstance(to_pos, tuple) else (to_pos.x, to_pos.y)
                segment_distance = self.path_calculator.calculate_pair_distance(from_xy, to_xy)
                total_distance += segment_distance
                
                # 计算已行驶距离
                if i < len(vehicle.complete_path) - 2:
                    traveled_distance += segment_distance
                else:
                    # 最后一段，计算当前位置到起点的距离
                    current_dist = self.path_calculator.calculate_pair_distance(
                        (current_position.x, current_position.y),
                        from_xy
                    )
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
            if distance_to_move <= 0:
                return

            # 初始化路径索引（用于稳定沿路径前进，避免在路段间振荡）
            if not hasattr(vehicle, "_route_segment_index"):
                vehicle._route_segment_index = 0

            remaining_distance = distance_to_move

            while remaining_distance > 0 and vehicle._route_segment_index < len(vehicle.complete_path) - 1:
                from_pos = vehicle.complete_path[vehicle._route_segment_index]
                to_pos = vehicle.complete_path[vehicle._route_segment_index + 1]

                from_x = from_pos[0] if isinstance(from_pos, tuple) else from_pos.x
                from_y = from_pos[1] if isinstance(from_pos, tuple) else from_pos.y
                to_x = to_pos[0] if isinstance(to_pos, tuple) else to_pos.x
                to_y = to_pos[1] if isinstance(to_pos, tuple) else to_pos.y

                # 当前位置到该段终点的剩余距离
                dx = to_x - vehicle.position.x
                dy = to_y - vehicle.position.y
                dist_to_end = self.path_calculator.calculate_pair_distance(
                    (vehicle.position.x, vehicle.position.y),
                    (to_x, to_y)
                )

                if dist_to_end <= 1e-6:
                    # 已到达当前段终点，进入下一段
                    vehicle._route_segment_index += 1
                    continue

                move_dist = min(remaining_distance, dist_to_end)
                progress = move_dist / dist_to_end

                new_x = vehicle.position.x + dx * progress
                new_y = vehicle.position.y + dy * progress
                vehicle.update_position(Position(x=new_x, y=new_y))

                vehicle.total_distance_traveled += move_dist
                energy_consumed = move_dist * vehicle.unit_energy_consumption
                vehicle.battery = max(0, vehicle.battery - energy_consumed)
                vehicle.energy_consumption += energy_consumed

                remaining_distance -= move_dist

                # 若已到达当前段终点则推进段索引
                if abs(move_dist - dist_to_end) <= 1e-6:
                    vehicle._route_segment_index += 1
            
            # 更新路径进度
            self.update_vehicle_path_progress(vehicle_id, vehicle.position)
            
            # 检查是否到达终点（路径段索引到末尾或非常接近终点）
            end_pos = vehicle.complete_path[-1]
            end_x = end_pos[0] if isinstance(end_pos, tuple) else end_pos.x
            end_y = end_pos[1] if isinstance(end_pos, tuple) else end_pos.y
            end_distance = self.path_calculator.calculate_pair_distance(
                (vehicle.position.x, vehicle.position.y),
                (end_x, end_y)
            )
            reached_end = (
                vehicle._route_segment_index >= len(vehicle.complete_path) - 1
                or vehicle.path_progress >= 0.999
                or end_distance <= 1.0
            )

            if reached_end:
                vehicle.update_position(Position(x=end_x, y=end_y))
                # 车辆到达终点，重置状态
                vehicle.update_status(VehicleStatus.IDLE)
                vehicle.path_progress = 0.0
                vehicle.complete_path = []
                vehicle._route_segment_index = 0
                
                # 检查并完成任务
                completed_tasks = self.check_and_complete_task(vehicle_id)
                if completed_tasks:
                    for task in completed_tasks:
                        print(f"Vehicle {vehicle_id} completed task {task.id}")
            
            self._notify_vehicle_update(vehicle)

    def get_avg_completed_task_distance(self, recent_n: int = 50) -> float:
        """
        动态统计最近 N 条已完成任务的平均路径距离（米）。
        用于得分函数中的 avg_path_length，避免硬编码偏差。
        若无已完成任务，返回默认值 5000m（番禺区合理估计）。
        """
        with self.lock:
            completed = [
                task for task in self.tasks.values()
                if task.status == TaskStatus.COMPLETED and task.complete_path_distance > 0
            ]
            if not completed:
                return 5000.0  # 番禺区任务默认往返距离估计
            recent = sorted(completed, key=lambda t: t.complete_time or 0, reverse=True)[:recent_n]
            distances = [t.complete_path_distance for t in recent if t.complete_path_distance > 0]
            return sum(distances) / len(distances) if distances else 5000.0

    def get_system_state(self) -> Dict:
        with self.lock:
            map_nodes = []
            map_edges = []
            nx_graph = self.path_calculator.nx_graph
            if nx_graph is not None:
                for node_id, attrs in nx_graph.nodes(data=True):
                    if attrs.get("x") is None or attrs.get("y") is None:
                        continue
                    map_nodes.append({
                        "id": int(node_id) if isinstance(node_id, (int, float)) else str(node_id),
                        "x": float(attrs["x"]),
                        "y": float(attrs["y"])
                    })

                for u, v in nx_graph.edges():
                    map_edges.append([u, v])
            
            # 计算任务完成率
            total_tasks = len(self.tasks)
            completed_tasks = len([task for task in self.tasks.values() if task.status == TaskStatus.COMPLETED])
            completion_rate = completed_tasks / total_tasks if total_tasks > 0 else 0.0
            
            # 计算车辆利用率
            total_vehicles = len(self.vehicles)
            busy_vehicles = len([vehicle for vehicle in self.vehicles.values() if vehicle.status != VehicleStatus.IDLE])
            vehicle_utilization = busy_vehicles / total_vehicles if total_vehicles > 0 else 0.0
            
            # 与任务评分逻辑保持一致。
            total_score = sum(
                task.score for task in self.tasks.values()
                if task.status == TaskStatus.COMPLETED
            )
            
            tasks_out = []
            for task in self.tasks.values():
                td = task.to_dict()
                enrich_wgs84_point_dict(td.get("position"))
                tasks_out.append(td)

            vehicles_out = []
            for vehicle in self.vehicles.values():
                vd = vehicle.to_dict()
                enrich_wgs84_point_dict(vd.get("position"))
                vehicles_out.append(vd)

            stations_out = []
            for station in self.charging_stations.values():
                sd = station.to_dict()
                enrich_wgs84_point_dict(sd.get("position"))
                stations_out.append(sd)

            wh = {"x": self.warehouse_position.x, "y": self.warehouse_position.y}
            enrich_wgs84_point_dict(wh)

            return {
                "timestamp": int(datetime.now().timestamp()),
                "tasks": tasks_out,
                "vehicles": vehicles_out,
                "charging_stations": stations_out,
                "warehouse_position": wh,
                "map_nodes": map_nodes,
                "map_edges": map_edges,
                "total_score": total_score,
                "completion_rate": completion_rate,
                "vehicle_utilization": vehicle_utilization
            }
