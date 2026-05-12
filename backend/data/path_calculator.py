from typing import List, Tuple, Dict, Optional
import logging
import random
import math
import time
import networkx as nx
from .task import Position, Task
from .vehicle import Vehicle
from .charging_station import ChargingStation
from backend.config import config

class PathCalculator:
    """仅基于图的路径计算器。"""
    
    def __init__(self, grid_unit: float = 1.0):
        self.grid_unit = grid_unit
        self.nx_graph: Optional[nx.Graph] = None
        self.logger = logging.getLogger(__name__)
        # 节点位置到节点ID的映射缓存，用于快速查找
        self._pos_to_node_cache: Dict[Tuple[float, float], any] = {}

    def set_networkx_graph(self, graph: nx.Graph):
        self.nx_graph = graph
        # 确保图是连通的，只保留最大连通分量
        self._ensure_connected_graph()
        # 构建位置到节点的映射缓存
        self._build_pos_to_node_cache()

    def _build_pos_to_node_cache(self):
        """构建节点位置到节点ID的映射缓存，用于快速查找。"""
        self._pos_to_node_cache = {}
        if self.nx_graph is None:
            return
        
        for node_id, attrs in self.nx_graph.nodes(data=True):
            x = attrs.get("x")
            y = attrs.get("y")
            if x is not None and y is not None:
                # 使用四舍五入到6位小数作为key，避免浮点精度问题
                key = (round(float(x), 6), round(float(y), 6))
                self._pos_to_node_cache[key] = node_id
        
        self.logger.info(f"Built position-to-node cache: {len(self._pos_to_node_cache)} nodes")

    def _ensure_connected_graph(self):
        """确保图只包含最大连通分量，避免不可达问题。
        
        对于OSM道路网络，使用强连通分量确保双向可达。
        """
        if self.nx_graph is None or self.nx_graph.number_of_nodes() == 0:
            return
        
        try:
            import networkx as nx
            
            original_nodes = self.nx_graph.number_of_nodes()
            original_edges = self.nx_graph.number_of_edges()
            
            # 对于OSM道路网络，使用强连通分量确保双向可达
            if self.nx_graph.is_directed():
                # 获取所有强连通分量
                sccs = list(nx.strongly_connected_components(self.nx_graph))
                if len(sccs) > 1:
                    # 选择最大的强连通分量
                    largest_scc = max(sccs, key=len)
                    self.nx_graph = self.nx_graph.subgraph(largest_scc).copy()
                    self.logger.info(
                        f"Graph pruned to largest strongly connected component: "
                        f"{original_nodes} -> {self.nx_graph.number_of_nodes()} nodes, "
                        f"{original_edges} -> {self.nx_graph.number_of_edges()} edges"
                    )
                else:
                    self.logger.info(f"Graph is strongly connected: {original_nodes} nodes")
            else:
                # 无向图使用连通分量
                components = list(nx.connected_components(self.nx_graph))
                if len(components) > 1:
                    largest_cc = max(components, key=len)
                    self.nx_graph = self.nx_graph.subgraph(largest_cc).copy()
                    self.logger.info(
                        f"Graph pruned to largest connected component: "
                        f"{original_nodes} -> {self.nx_graph.number_of_nodes()} nodes, "
                        f"{original_edges} -> {self.nx_graph.number_of_edges()} edges"
                    )
                else:
                    self.logger.info(f"Graph is connected: {original_nodes} nodes")
                    
        except Exception as e:
            self.logger.warning(f"Failed to ensure connected graph: {e}")

    def iter_valid_node_xy(self) -> List[Tuple[float, float]]:
        if self.nx_graph is None:
            return []
        out: List[Tuple[float, float]] = []
        for _, attrs in self.nx_graph.nodes(data=True):
            x = attrs.get("x")
            y = attrs.get("y")
            if x is not None and y is not None:
                out.append((float(x), float(y)))
        return out

    def sample_random_node_xy(self, rng: Optional[random.Random] = None) -> Tuple[float, float]:
        """Sample (lon, lat) WGS84 from a graph node — same space as routing."""
        nodes = self.iter_valid_node_xy()
        if not nodes:
            raise RuntimeError("No graph nodes with coordinates for sampling")
        r = rng or random
        return r.choice(nodes)

    def get_central_node_xy(self) -> Tuple[float, float]:
        """获取图的中心节点（质心最近的节点）作为仓库位置。"""
        if self.nx_graph is None or self.nx_graph.number_of_nodes() == 0:
            raise RuntimeError("Graph not initialized")
        
        nodes = list(self.nx_graph.nodes(data=True))
        if not nodes:
            raise RuntimeError("No nodes in graph")
        
        # 计算所有节点的平均位置（质心）
        avg_x = sum(attrs.get("x", 0) for _, attrs in nodes) / len(nodes)
        avg_y = sum(attrs.get("y", 0) for _, attrs in nodes) / len(nodes)
        
        # 找到离质心最近的节点
        closest_node = None
        min_dist = float('inf')
        
        for node_id, attrs in nodes:
            x = attrs.get("x")
            y = attrs.get("y")
            if x is not None and y is not None:
                dist = (x - avg_x) ** 2 + (y - avg_y) ** 2
                if dist < min_dist:
                    min_dist = dist
                    closest_node = (float(x), float(y))
        
        if closest_node is None:
            raise RuntimeError("Cannot find central node with coordinates")
        
        return closest_node

    def get_peripheral_nodes_xy(self, count: int, rng: Optional[random.Random] = None) -> List[Tuple[float, float]]:
        """获取图的四周节点（离中心中等距离的节点）用于分布充电站。
        
        确保选择的节点与中心节点连通（在同一个连通分量中），
        并且在各个方向上均匀分布，形成对中心仓库的包围。
        选择中等距离的节点（不要太靠近边界）。
        """
        if self.nx_graph is None or self.nx_graph.number_of_nodes() == 0:
            raise RuntimeError("Graph not initialized")
        
        # 获取中心节点ID（用于连通性检查）
        center_xy = self.get_central_node_xy()
        center_node_id = self._find_nearest_graph_node(center_xy)
        
        nodes = list(self.nx_graph.nodes(data=True))
        if not nodes:
            raise RuntimeError("No nodes in graph")
        
        center_x, center_y = center_xy
        
        # 计算每个节点到中心的距离和角度，并检查连通性
        node_data = []
        for node_id, attrs in nodes:
            x = attrs.get("x")
            y = attrs.get("y")
            if x is not None and y is not None:
                # 检查是否与中心节点连通
                try:
                    if nx.has_path(self.nx_graph, center_node_id, node_id):
                        dx = x - center_x
                        dy = y - center_y
                        dist = (dx ** 2 + dy ** 2) ** 0.5
                        angle = math.atan2(dy, dx)  # 角度：-π 到 π
                        node_data.append({
                            'pos': (float(x), float(y)),
                            'dist': dist,
                            'angle': angle
                        })
                except Exception:
                    pass
        
        if not node_data:
            raise RuntimeError("No connected nodes with coordinates found")
        
        # 按距离排序
        node_data.sort(key=lambda x: x['dist'], reverse=True)
        
        # 计算距离分布，选择中等距离的节点（30%-70%范围）
        # 这样避免太靠近边界，也避免太靠近中心
        n = len(node_data)
        start_idx = int(n * 0.3)  # 从30%位置开始
        end_idx = int(n * 0.7)    # 到70%位置结束
        
        if end_idx - start_idx < count:
            # 如果范围太小，扩大到前70%
            start_idx = 0
            end_idx = max(int(n * 0.7), count * 2)
        
        candidate_nodes = node_data[start_idx:end_idx]
        
        r = rng or random
        selected = []
        
        if count > 0 and candidate_nodes:
            # 将节点按角度分桶
            angle_buckets = {}  # 桶号 -> 节点列表
            bucket_size = 2 * math.pi / count  # 每个扇区的角度大小
            
            for node in candidate_nodes:
                # 将角度归一化到 [0, 2π)
                normalized_angle = node['angle'] % (2 * math.pi)
                bucket = int(normalized_angle / bucket_size) % count
                
                if bucket not in angle_buckets:
                    angle_buckets[bucket] = []
                angle_buckets[bucket].append(node)
            
            # 从每个桶中选择距离中心最远的节点（在中等距离范围内）
            for i in range(count):
                if i in angle_buckets and angle_buckets[i]:
                    # 选择该角度桶中距离最远的节点
                    best_node = max(angle_buckets[i], key=lambda x: x['dist'])
                    selected.append(best_node['pos'])
                else:
                    # 如果该角度没有节点，从其他桶中随机选择
                    all_nodes = [n for nodes in angle_buckets.values() for n in nodes]
                    if all_nodes:
                        node = r.choice(all_nodes)
                        selected.append(node['pos'])
        
        # 如果不够，从候选节点中补充
        while len(selected) < count and candidate_nodes:
            node = r.choice(candidate_nodes)
            if node['pos'] not in selected:
                selected.append(node['pos'])
        
        # 如果还是不够，从所有节点中补充
        while len(selected) < count and node_data:
            node = r.choice(node_data)
            if node['pos'] not in selected:
                selected.append(node['pos'])
        
        return selected[:count]

    def get_connected_nodes_xy(self, source_xy: Tuple[float, float]) -> List[Tuple[float, float]]:
        """获取与指定位置连通的所有节点坐标。
        
        Args:
            source_xy: 源位置坐标 (x, y)
            
        Returns:
            与该位置连通的所有节点坐标列表
        """
        if self.nx_graph is None or self.nx_graph.number_of_nodes() == 0:
            return []
        
        try:
            # 找到源位置对应的节点ID
            source_node = self._find_nearest_graph_node(source_xy)
            
            # 获取所有可达节点
            connected_nodes = []
            for node_id, attrs in self.nx_graph.nodes(data=True):
                if node_id == source_node:
                    continue
                    
                try:
                    # 检查是否连通
                    if nx.has_path(self.nx_graph, source_node, node_id):
                        x = attrs.get("x")
                        y = attrs.get("y")
                        if x is not None and y is not None:
                            connected_nodes.append((float(x), float(y)))
                except Exception:
                    pass
            
            return connected_nodes
            
        except Exception as e:
            self.logger.warning(f"Failed to get connected nodes: {e}")
            return []

    def build_stitched_path(
        self, waypoints: List[Tuple[float, float]]
    ) -> List[Tuple[float, float]]:
        """Concatenate shortest paths between consecutive waypoints."""
        if len(waypoints) < 2:
            return list(waypoints)
        full_path: List[Tuple[float, float]] = []
        for i in range(len(waypoints) - 1):
            segment = self.find_shortest_path(waypoints[i], waypoints[i + 1])
            if not segment:
                continue
            if full_path and segment[0] == full_path[-1]:
                full_path.extend(segment[1:])
            else:
                full_path.extend(segment)
        return full_path if full_path else list(waypoints)

    def calculate_distance(self, path: List[Tuple[float, float]]) -> float:
        if len(path) < 2:
            return 0.0
        total_distance = 0.0
        for i in range(len(path) - 1):
            total_distance += self.calculate_pair_distance(path[i], path[i + 1])
        return total_distance * self.grid_unit

    def calculate_pair_distance(self, start: Tuple[float, float], end: Tuple[float, float]) -> float:
        """使用图路由计算两点距离（强制）。"""
        if self.nx_graph is None:
            raise RuntimeError("Graph is not initialized. Cannot calculate pair distance without graph.")
        
        graph_distance = self._graph_shortest_path_length(start, end)
        if graph_distance is None:
            raise RuntimeError(f"Cannot compute graph distance between {start} and {end}")
        return graph_distance

    def calculate_distance_from_positions(self, positions: List[Position]) -> float:
        path = [(p.x, p.y) for p in positions]
        return self.calculate_distance(path)

    def calculate_energy_consumption(self, vehicle: Vehicle, path: List[Tuple[float, float]]) -> float:
        distance = self.calculate_distance(path)
        return distance * vehicle.unit_energy_consumption

    def calculate_energy_consumption_from_positions(self, vehicle: Vehicle, positions: List[Position]) -> float:
        path = [(p.x, p.y) for p in positions]
        return self.calculate_energy_consumption(vehicle, path)

    def find_shortest_path(self, start: Tuple[float, float], end: Tuple[float, float]) -> List[Tuple[float, float]]:
        """使用图路由寻找最短路径（强制）。"""
        if self.nx_graph is None:
            raise RuntimeError("Graph is not initialized. Cannot find shortest path without graph.")
        
        graph_path = self._graph_shortest_path(start, end)
        if graph_path is None:
            raise RuntimeError(f"Cannot compute graph path between {start} and {end}")
        return graph_path

    def _graph_shortest_path_length(self, start: Tuple[float, float], end: Tuple[float, float]) -> Optional[float]:
        """基于图计算最短路径长度（强制）。"""
        if self.nx_graph is None:
            raise RuntimeError("Graph is not initialized")
        try:
            start_node = self._find_nearest_graph_node(start)
            end_node = self._find_nearest_graph_node(end)
            return nx.shortest_path_length(self.nx_graph, start_node, end_node, weight="length")
        except Exception as exc:
            self.logger.error("Graph shortest path length failed for %s -> %s: %s", start, end, exc)
            raise

    def _graph_shortest_path(self, start: Tuple[float, float], end: Tuple[float, float]) -> Optional[List[Tuple[float, float]]]:
        """基于图查找最短路径节点序列（强制）。"""
        if self.nx_graph is None:
            raise RuntimeError("Graph is not initialized")
        try:
            start_node = self._find_nearest_graph_node(start)
            end_node = self._find_nearest_graph_node(end)
            node_path = nx.shortest_path(self.nx_graph, start_node, end_node, weight="length")
            return [
                (
                    float(self.nx_graph.nodes[node]["x"]),
                    float(self.nx_graph.nodes[node]["y"])
                )
                for node in node_path
            ]
        except Exception as exc:
            self.logger.error("Graph shortest path failed for %s -> %s: %s", start, end, exc)
            raise

    def _find_nearest_graph_node(self, pos: Tuple[float, float]):
        """通过图工具空间索引查找最近节点。
        
        优化：如果位置已经在节点缓存中，直接返回，避免重新搜索。
        """
        if self.nx_graph is None:
            raise RuntimeError("Graph is not initialized")

        try:
            target_x, target_y = pos
            
            # 优化1：先检查缓存，如果位置已经在节点上，直接返回
            cache_key = (round(float(target_x), 6), round(float(target_y), 6))
            if cache_key in self._pos_to_node_cache:
                return self._pos_to_node_cache[cache_key]
            
            # 优化2：使用 osmnx 的 nearest_nodes（如果可用）
            if self.nx_graph.graph.get("crs") is not None:
                try:
                    import osmnx as ox
                    return ox.distance.nearest_nodes(self.nx_graph, X=target_x, Y=target_y)
                except Exception as exc:
                    self.logger.warning(
                        "Graph nearest_nodes unavailable, fallback to coordinate index search: %s",
                        exc
                    )

            # 回退：线性搜索最近节点
            nearest_node = None
            nearest_score = float("inf")
            for node_id, attrs in self.nx_graph.nodes(data=True):
                node_x = attrs.get("x")
                node_y = attrs.get("y")
                if node_x is None or node_y is None:
                    continue
                score = abs(float(node_x) - target_x) + abs(float(node_y) - target_y)
                if score < nearest_score:
                    nearest_score = score
                    nearest_node = node_id
            if nearest_node is None:
                raise RuntimeError("No graph node has valid coordinates")
            return nearest_node
        except Exception as exc:
            raise RuntimeError(f"Failed to locate nearest graph node for position {pos}: {exc}") from exc

    def find_nearest_charging_station(self, vehicle: Vehicle, stations: List[ChargingStation]) -> str:
        """基于图距离查找最近充电站。"""
        if not stations:
            return None
        if self.nx_graph is None:
            raise RuntimeError("Graph is not initialized. Cannot find charging station without graph.")

        vehicle_pos = (vehicle.position.x, vehicle.position.y)
        nearest_station = None
        min_distance = float('inf')

        for station in stations:
            station_pos = (station.position.x, station.position.y)
            try:
                distance = self._graph_shortest_path_length(vehicle_pos, station_pos)
                if distance is not None and distance < min_distance:
                    min_distance = distance
                    nearest_station = station
            except Exception as exc:
                self.logger.warning("Failed to compute distance to station %s: %s", station.id, exc)
                continue

        return nearest_station.id if nearest_station else None

    def calculate_path_with_stations(self, start: Position, waypoints: List[Position], end: Position) -> List[Position]:
        path = [start]
        path.extend(waypoints)
        path.append(end)
        return path

    def is_energy_sufficient(self, vehicle: Vehicle, path: List[Tuple[float, float]], warehouse_pos: Tuple[float, float]) -> bool:
        energy_needed = self.calculate_energy_consumption(vehicle, path)
        energy_to_warehouse = self.calculate_energy_consumption(vehicle, [path[-1], warehouse_pos])
        total_energy_needed = energy_needed + energy_to_warehouse
        return vehicle.battery >= total_energy_needed

    def calculate_complete_path(self, warehouse_pos: Position, task_pos: Position) -> tuple:
        """
        计算完整路径：仓库 → 任务点 → 仓库
        
        参数:
            warehouse_pos: 仓库位置
            task_pos: 任务点位置
        
        返回:
            complete_path: 完整路径点列表
            total_distance: 总距离
        """
        # 阶段1：仓库到任务点
        path_to_task = self.find_shortest_path(
            (warehouse_pos.x, warehouse_pos.y),
            (task_pos.x, task_pos.y)
        )
        
        # 阶段2：任务点返回仓库
        path_to_warehouse = self.find_shortest_path(
            (task_pos.x, task_pos.y),
            (warehouse_pos.x, warehouse_pos.y)
        )
        
        # 合并完整路径（避免重复任务点）
        complete_path = path_to_task + path_to_warehouse[1:]
        
        # 计算总距离
        total_distance = self.calculate_distance(complete_path)
        
        return complete_path, total_distance

    def calculate_energy_consumption_for_complete_path(self, vehicle: Vehicle, complete_path: List[Tuple[float, float]]) -> tuple:
        """
        基于完整路径计算电量消耗
        
        参数:
            vehicle: 车辆对象
            complete_path: 完整路径点列表
        
        返回:
            total_energy: 总电量消耗
            is_feasible: 电量是否充足
        """
        total_energy = 0.0
        
        # 遍历完整路径的每一段
        for i in range(len(complete_path) - 1):
            from_pos = complete_path[i]
            to_pos = complete_path[i + 1]
            
            # 计算该段距离（使用图路由）
            distance = self.calculate_pair_distance(from_pos, to_pos)
            
            # 计算该段电量消耗（考虑载重）
            energy = distance * vehicle.unit_energy_consumption
            total_energy += energy
        
        # 检查电量是否充足
        is_feasible = total_energy <= vehicle.battery
        
        return total_energy, is_feasible

    def calculate_task_completion_time(self, complete_path: List[Tuple[float, float]], vehicle_speed: float = 1.0, unloading_time: float = 30.0) -> float:
        """
        计算任务完成时间（基于完整路径）
        
        参数:
            complete_path: 完整路径
            vehicle_speed: 车辆速度（单位/秒）
            unloading_time: 卸载时间（秒）
        
        返回:
            completion_time: 完成时间（秒）
        """
        # 计算总距离
        total_distance = self.calculate_distance(complete_path)
        
        # 计算总时间
        total_time = total_distance / vehicle_speed
        
        # 加上任务点停留时间
        completion_time = total_time + unloading_time
        
        return completion_time

    def calculate_task_score(self, task, completion_time: float,
                             complete_path_distance: float,
                             vehicle=None,
                             avg_path_length: float = None) -> float:
        """
        计算任务得分（使用与静态规划、实时调度统一的评分机制）。
        
        统一评分公式（参考 scoring_config.py）：
          得分 = 任务分配奖励(120) + 优先级奖励(30×priority) 
                - 距离惩罚(0.02×距离) - 能耗惩罚(0.2×能耗)
                - 逾期惩罚(50×逾期分钟)

        参数:
            task: 任务对象（需有 deadline, priority 属性）
            completion_time: 实际完成时间（Unix 时间戳）
            complete_path_distance: 完整路径距离（米）
            vehicle: 车辆对象（可选，用于计算能耗）
            avg_path_length: 已废弃，保留参数兼容性
        """
        # 延迟导入避免循环依赖
        from backend.algorithm.scoring_config import (
            TASK_ASSIGN_REWARD,
            PRIORITY_REWARD,
            DISTANCE_PENALTY,
            ENERGY_PENALTY,
            OVERDUE_PENALTY_PER_MIN
        )
        
        # 1. 任务分配奖励
        task_reward = TASK_ASSIGN_REWARD
        
        # 2. 优先级奖励
        priority_reward = getattr(task, 'priority', 1) * PRIORITY_REWARD
        
        # 3. 距离惩罚（使用实际完成路径）
        distance_cost = complete_path_distance * DISTANCE_PENALTY
        
        # 4. 能耗惩罚（如果有车辆信息）
        if vehicle and hasattr(vehicle, 'unit_energy_consumption'):
            energy_cost = complete_path_distance * vehicle.unit_energy_consumption * ENERGY_PENALTY
        else:
            # 默认能耗系数 0.001 kWh/m
            energy_cost = complete_path_distance * 0.001 * ENERGY_PENALTY
        
        # 5. 逾期惩罚
        overdue_minutes = max(0, completion_time - task.deadline) / 60.0
        overdue_cost = overdue_minutes * OVERDUE_PENALTY_PER_MIN
        
        # 综合得分
        total_score = task_reward + priority_reward - distance_cost - energy_cost - overdue_cost
        
        return total_score

    def calculate_round_trip_energy(
        self,
        vehicle,
        start_pos: tuple,
        task_pos: tuple,
        warehouse_pos: tuple
    ) -> float:
        """
        计算完整往返路程能耗：start → task → warehouse。
        用于调度前的可行性预判。

        参数:
            vehicle: 车辆对象（需有 unit_energy_consumption 属性）
            start_pos: 起始位置 (lon, lat)
            task_pos: 任务位置 (lon, lat)
            warehouse_pos: 仓库位置 (lon, lat)
        返回:
            total_energy: 全程总电量消耗
        """
        path = self.build_stitched_path([start_pos, task_pos, warehouse_pos])
        return self.calculate_energy_consumption(vehicle, path)
