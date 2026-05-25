from typing import List, Dict, Optional, Callable
from datetime import datetime
import threading
import asyncio
import inspect
import logging
import math
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

    # ------------------------------------------------------------------
    # 货物接力：把挂在 src 车上的若干 task 转交给同位置的 dst 车
    # ------------------------------------------------------------------
    def transfer_cargo(
        self,
        src_vehicle_id: int,
        dst_vehicle_id: int,
        task_ids: List[int],
        position_eps: float = 1e-4,
    ) -> bool:
        """把 `src` 车上指定的 task 转给 `dst` 车（原地接力）。

        前置条件：
          1. 两辆车都存在、都不是 STRANDED；
          2. 两辆车当前位置几乎重合（|dx|,|dy| < eps）；
          3. 这些 task 目前确实挂在 src 上（assigned_vehicle_id == src_id）；
          4. dst 剩余载重足以承担这批 task 的总重。

        效果（原子：要么全过、要么全不过）：
          - task.assigned_vehicle_id: src -> dst
          - src.assigned_task_ids 移除 / dst.assigned_task_ids 追加
          - src.current_load 相应减少；dst.current_load 相应增加

        目前调度/算法层没有任何策略会主动使用它；但框架保留这个能力，
        方便以后写"多车接力"算法（在算法层就能做到，无需再改这里）。
        """
        with self.lock:
            src = self.vehicles.get(src_vehicle_id)
            dst = self.vehicles.get(dst_vehicle_id)
            if src is None or dst is None:
                return False
            if src_vehicle_id == dst_vehicle_id:
                return False
            if src.is_stranded() or dst.is_stranded():
                return False
            # 同位置检查
            if (abs(src.position.x - dst.position.x) > position_eps
                    or abs(src.position.y - dst.position.y) > position_eps):
                return False

            # 收集合法 task + 总重
            pending_transfer = []
            total_weight = 0.0
            for tid in task_ids:
                task = self.tasks.get(tid)
                if task is None:
                    return False
                if task.assigned_vehicle_id != src_vehicle_id:
                    return False
                # 只允许在"正挂在车上"的阶段做接力：
                # ASSIGNED / IN_PROGRESS 都算"被某辆车背着"。
                if task.status not in (TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS):
                    return False
                pending_transfer.append(task)
                total_weight += task.weight

            if dst.get_remaining_load() + 1e-9 < total_weight:
                return False

            # 正式转移
            for task in pending_transfer:
                task.assigned_vehicle_id = dst_vehicle_id
                src.remove_task(task.id)
                dst.add_task(task.id)
                self._notify_task_update(task)

            src.update_load(max(0.0, src.current_load - total_weight))
            dst.update_load(dst.current_load + total_weight)
            self._notify_vehicle_update(src)
            self._notify_vehicle_update(dst)
            return True

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

    # ------------------------------------------------------------------
    # 运动推进（重构核心）
    #
    # 新模型下车辆的轨迹管理极简：
    #   1) start_vehicle_route(vehicle_id, target_xy, new_status, task_id)
    #      计算 Dijkstra 路径并写入 vehicle.current_route；
    #   2) advance_vehicle(vehicle_id, dt)
    #      按 speed*dt 沿 current_route 向前推，到达终点时触发
    #      _on_arrival() 执行对应动作（卸货 / 进站 / 批量完成）。
    # ------------------------------------------------------------------

    def start_vehicle_route(
        self,
        vehicle_id: int,
        target_xy,
        new_status: VehicleStatus,
        task_id: Optional[int] = None,
    ) -> bool:
        """给车辆设置一条"下一步"路径（Dijkstra）。

        参数:
            target_xy  : (x, y) 目标节点坐标
            new_status : 对应的运动状态，MOVING_TO_TASK / MOVING_TO_CHARGE / MOVING_TO_WAREHOUSE
            task_id    : 若是送货，这里传对应任务 id，到达时用来标记卸货
        返回:
            是否成功（路径可达）
        """
        with self.lock:
            vehicle = self.vehicles.get(vehicle_id)
            if vehicle is None:
                return False

            tx, ty = float(target_xy[0]), float(target_xy[1])
            try:
                route = self.path_calculator.find_shortest_path(
                    (vehicle.position.x, vehicle.position.y),
                    (tx, ty),
                )
            except Exception as e:
                self.logger.warning(
                    "start_vehicle_route: cannot find path for vehicle %s -> (%.6f, %.6f): %s",
                    vehicle_id, tx, ty, e,
                )
                return False

            if not route:
                return False

            vehicle.set_route((tx, ty), route)
            vehicle.current_task_id = task_id
            vehicle.update_status(new_status)
            self._notify_vehicle_update(vehicle)
            return True

    def advance_vehicle(self, vehicle_id: int, time_delta: float) -> None:
        """沿 current_route 推进车辆；到达 target 时调用 _on_arrival。

        time_delta 单位为"仿真秒"（即 SIM_SPEED_FACTOR * 真实 dt）。
        距离/能耗在此函数里统一累加。
        """
        with self.lock:
            vehicle = self.vehicles.get(vehicle_id)
            if vehicle is None:
                return
            if not vehicle.is_moving():
                return
            if not vehicle.current_route or len(vehicle.current_route) < 2:
                # 无路径：直接视为已到
                self._on_arrival(vehicle)
                return

            remaining = vehicle.speed * float(time_delta)
            if remaining <= 0:
                return

            route = vehicle.current_route

            # 本 tick 先把 tick_path 清一下，并记录起点（前端沿此折线平滑过渡）
            vehicle.tick_path = [(vehicle.position.x, vehicle.position.y)]

            # 沿 route 一段段走。每段两端都是图节点，_route_index 表示
            # "下一个还没到的节点下标"。
            while remaining > 0 and vehicle._route_index < len(route) - 1:
                here_xy = (vehicle.position.x, vehicle.position.y)
                seg_start_xy = route[vehicle._route_index]
                nxt_xy = route[vehicle._route_index + 1]
                try:
                    seg_total_len = self.path_calculator.calculate_pair_distance(
                        seg_start_xy, nxt_xy
                    )
                except Exception:
                    # 不可达：直接跳到该节点当已到
                    seg_total_len = 0.0

                # here_xy 可能是段内插值点，不一定是图节点；如果拿它去重算
                # 路网距离，会被吸附到最近节点，导致“视觉几乎不动但持续扣电”。
                # 因此用当前段的坐标剩余比例折算剩余米数。
                coord_total = math.hypot(
                    nxt_xy[0] - seg_start_xy[0],
                    nxt_xy[1] - seg_start_xy[1],
                )
                coord_remaining = math.hypot(
                    nxt_xy[0] - here_xy[0],
                    nxt_xy[1] - here_xy[1],
                )
                if coord_total > 1e-12:
                    remain_ratio = min(1.0, max(0.0, coord_remaining / coord_total))
                    seg_len = seg_total_len * remain_ratio
                else:
                    seg_len = 0.0

                if seg_len <= 1e-6:
                    vehicle._route_index += 1
                    vehicle.update_position(Position(x=nxt_xy[0], y=nxt_xy[1]))
                    vehicle.tick_path.append((nxt_xy[0], nxt_xy[1]))
                    continue

                if remaining >= seg_len:
                    # 这一段能整段跨过
                    vehicle._route_index += 1
                    vehicle.update_position(Position(x=nxt_xy[0], y=nxt_xy[1]))
                    self._apply_motion_cost(vehicle, seg_len)
                    vehicle.tick_path.append((nxt_xy[0], nxt_xy[1]))
                    remaining -= seg_len
                else:
                    # 段内部分前进，向目标线性插值（段两端是相邻图节点，线段近似合理）
                    ratio = remaining / seg_len
                    new_x = vehicle.position.x + (nxt_xy[0] - vehicle.position.x) * ratio
                    new_y = vehicle.position.y + (nxt_xy[1] - vehicle.position.y) * ratio
                    vehicle.update_position(Position(x=new_x, y=new_y))
                    self._apply_motion_cost(vehicle, remaining)
                    vehicle.tick_path.append((new_x, new_y))
                    remaining = 0.0

                # 电量耗尽：就地抛锚，路径信息清空，本次 tick 后续不再推进
                if vehicle.battery <= 0:
                    self._strand_vehicle(vehicle)
                    self._notify_vehicle_update(vehicle)
                    return

            # 到达终点？
            if vehicle._route_index >= len(route) - 1:
                self._on_arrival(vehicle)
            else:
                self._notify_vehicle_update(vehicle)

    def _strand_vehicle(self, vehicle: Vehicle) -> None:
        """电量耗尽时调用：清空路径/任务挂载信息，转为 STRANDED。调用方已持锁。"""
        print(
            f"[Sim] Vehicle {vehicle.id} ({vehicle.vehicle_type}) ran out of battery "
            f"at ({vehicle.position.x:.5f},{vehicle.position.y:.5f}) — STRANDED"
        )
        vehicle.battery = 0.0
        vehicle.status = VehicleStatus.STRANDED
        # 挂在车上的任务保持 ASSIGNED/IN_PROGRESS 不动：它们永远完不成也领不到分，
        # 这是刻意的——用来惩罚把车开到没电的算法。
        vehicle.clear_route()

    def _apply_motion_cost(self, vehicle: Vehicle, distance_m: float) -> None:
        """在 lock 中调用：累加里程 + 扣电量 + 更新这一趟的累计能耗。"""
        if distance_m <= 0:
            return
        vehicle.total_distance_traveled += distance_m
        energy = distance_m * vehicle.unit_energy_consumption
        vehicle.battery = max(0.0, vehicle.battery - energy)
        vehicle.energy_consumption += energy

    def _on_arrival(self, vehicle: Vehicle) -> None:
        """车辆到达其 current_target_xy 时触发。调用方必须已持锁。"""
        arrived_status = vehicle.status

        # 把坐标精确对齐到 target
        if vehicle.current_target_xy is not None:
            tx, ty = vehicle.current_target_xy
            vehicle.update_position(Position(x=tx, y=ty))

        if arrived_status == VehicleStatus.MOVING_TO_TASK:
            self._handle_arrival_at_task(vehicle)
        elif arrived_status == VehicleStatus.MOVING_TO_CHARGE:
            self._handle_arrival_at_station(vehicle)
        elif arrived_status == VehicleStatus.MOVING_TO_WAREHOUSE:
            self._handle_arrival_at_warehouse(vehicle)
        elif arrived_status == VehicleStatus.MOVING_TO_NODE:
            # "特殊节点"到了：车本身没有业务需要结算（没有卸货、没有入站、没有回仓库清账）。
            # 只要把路径清掉、状态置 IDLE 就行；具体要做的事（比如接力货物）由调度器
            # 在下一轮看到这辆"在特殊节点上 IDLE"的车时决定。
            vehicle.clear_route()
            vehicle.update_status(VehicleStatus.IDLE)
        else:
            # 不应发生：只有 MOVING_* 状态会走到 _on_arrival
            vehicle.clear_route()
            vehicle.update_status(VehicleStatus.IDLE)

        self._notify_vehicle_update(vehicle)

    def _handle_arrival_at_task(self, vehicle: Vehicle) -> None:
        """送达：对应 task 从 ASSIGNED → IN_PROGRESS，车载重相应减少。"""
        task_id = vehicle.current_task_id
        if task_id is not None:
            task = self.tasks.get(task_id)
            if task is not None:
                # 记录送达距离（这是这一趟走过的路径；仓库->任务的距离累计）
                # 我们这里只记这一段的 target 距离作为该任务的"配送腿"距离。
                try:
                    seg_dist = self.path_calculator.calculate_distance(
                        [(p[0], p[1]) for p in vehicle.current_route]
                    ) if vehicle.current_route else 0.0
                except Exception:
                    seg_dist = 0.0
                task.complete_path_distance = max(task.complete_path_distance, seg_dist)
                if task.status == TaskStatus.ASSIGNED:
                    task.update_status(TaskStatus.IN_PROGRESS)
                # 卸货
                vehicle.update_load(max(0.0, vehicle.current_load - task.weight))
                self._notify_task_update(task)

        vehicle.clear_route()
        vehicle.update_status(VehicleStatus.IDLE)

    def _handle_arrival_at_station(self, vehicle: Vehicle) -> None:
        """到充电站：进站 / 排队。"""
        target_station_id = None
        # current_route 保留了 target 坐标；匹配是哪个站
        tx = vehicle.position.x
        ty = vehicle.position.y
        for sid, st in self.charging_stations.items():
            if abs(st.position.x - tx) < 1e-4 and abs(st.position.y - ty) < 1e-4:
                target_station_id = sid
                break

        vehicle.clear_route()

        if target_station_id is None:
            # 找不到站：退回 IDLE
            vehicle.update_status(VehicleStatus.IDLE)
            return

        # add_vehicle_to_charging_station 本身会请求 self.lock，但我们用的是 RLock，OK
        self.add_vehicle_to_charging_station(vehicle.id, target_station_id)

    def _handle_arrival_at_warehouse(self, vehicle: Vehicle) -> None:
        """回仓库：车上 IN_PROGRESS 的任务批量 COMPLETED，清空载重。"""
        completion_ts = int(datetime.now().timestamp())
        completed: List[Task] = []
        for task_id in list(vehicle.assigned_task_ids):
            task = self.tasks.get(task_id)
            if task is None:
                vehicle.remove_task(task_id)
                continue
            # 已送达的（IN_PROGRESS）才算 COMPLETED
            if task.status == TaskStatus.IN_PROGRESS:
                task.update_status(TaskStatus.COMPLETED)
                actual_ts = task.complete_time if task.complete_time else completion_ts
                task.score = self.path_calculator.calculate_task_score(
                    task, actual_ts, task.complete_path_distance, vehicle=vehicle
                )
                task.is_on_time = actual_ts <= task.deadline
                completed.append(task)
                vehicle.remove_task(task_id)
                self._notify_task_update(task)
            # 极端情况：ASSIGNED 但没送达就回仓库（比如算法主动放弃）——回收
            elif task.status == TaskStatus.ASSIGNED:
                task.assigned_vehicle_id = None
                task.update_status(TaskStatus.PENDING)
                vehicle.remove_task(task_id)
                self._notify_task_update(task)

        if completed:
            print(
                f"Vehicle {vehicle.id} returned to warehouse, "
                f"completed {len(completed)} task(s): {[t.id for t in completed]}"
            )

        # 清空状态准备下一轮装货
        vehicle.update_load(0.0)
        vehicle.energy_consumption = 0.0
        vehicle.clear_route()
        vehicle.update_status(VehicleStatus.IDLE)

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
