from typing import List, Tuple, Dict
from collections import defaultdict
import heapq
import math
from .task import Position, Task
from .vehicle import Vehicle
from .charging_station import ChargingStation

class PathCalculator:
    def __init__(self, grid_unit: float = 1.0):
        self.graph = defaultdict(dict)
        self.grid_unit = grid_unit

    def add_edge(self, from_pos: Tuple[float, float], to_pos: Tuple[float, float], distance: float):
        from_key = self._position_to_key(from_pos)
        to_key = self._position_to_key(to_pos)
        self.graph[from_key][to_key] = distance

    def _position_to_key(self, pos: Tuple[float, float]) -> str:
        return f"{pos[0]:.2f},{pos[1]:.2f}"

    def _position_to_key_from_obj(self, pos: Position) -> str:
        return f"{pos.x:.2f},{pos.y:.2f}"

    def calculate_distance(self, path: List[Tuple[float, float]]) -> float:
        if len(path) < 2:
            return 0.0
        total_distance = 0.0
        for i in range(len(path) - 1):
            total_distance += self._euclidean_distance(path[i], path[i + 1])
        return total_distance * self.grid_unit

    def calculate_distance_from_positions(self, positions: List[Position]) -> float:
        path = [(p.x, p.y) for p in positions]
        return self.calculate_distance(path)

    def _euclidean_distance(self, pos1: Tuple[float, float], pos2: Tuple[float, float]) -> float:
        return math.sqrt((pos1[0] - pos2[0])**2 + (pos1[1] - pos2[1])**2)

    def calculate_energy_consumption(self, vehicle: Vehicle, path: List[Tuple[float, float]]) -> float:
        distance = self.calculate_distance(path)
        return distance * vehicle.unit_energy_consumption

    def calculate_energy_consumption_from_positions(self, vehicle: Vehicle, positions: List[Position]) -> float:
        path = [(p.x, p.y) for p in positions]
        return self.calculate_energy_consumption(vehicle, path)

    def find_shortest_path(self, start: Tuple[float, float], end: Tuple[float, float]) -> List[Tuple[float, float]]:
        start_key = self._position_to_key(start)
        end_key = self._position_to_key(end)

        if start_key not in self.graph:
            return [start, end]

        distances = {start_key: 0}
        previous = {}
        pq = [(0, start_key)]

        while pq:
            current_dist, current_key = heapq.heappop(pq)

            if current_key == end_key:
                path = []
                while current_key in previous:
                    pos = self._key_to_position(current_key)
                    path.append(pos)
                    current_key = previous[current_key]
                path.append(start)
                return path[::-1]

            if current_dist > distances.get(current_key, float('inf')):
                continue

            for neighbor_key, edge_dist in self.graph[current_key].items():
                dist = current_dist + edge_dist
                if dist < distances.get(neighbor_key, float('inf')):
                    distances[neighbor_key] = dist
                    previous[neighbor_key] = current_key
                    heapq.heappush(pq, (dist, neighbor_key))

        return [start, end]

    def _key_to_position(self, key: str) -> Tuple[float, float]:
        x, y = key.split(',')
        return (float(x), float(y))

    def find_nearest_charging_station(self, vehicle: Vehicle, stations: List[ChargingStation]) -> str:
        if not stations:
            return None

        vehicle_pos = (vehicle.position.x, vehicle.position.y)
        nearest_station = None
        min_distance = float('inf')

        for station in stations:
            station_pos = (station.position.x, station.position.y)
            distance = self._euclidean_distance(vehicle_pos, station_pos)
            if distance < min_distance:
                min_distance = distance
                nearest_station = station

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
            
            # 计算该段距离
            distance = self._euclidean_distance(from_pos, to_pos)
            
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

    def calculate_task_score(self, task, completion_time: float, complete_path_distance: float, avg_path_length: float = 1000.0) -> float:
        """
        计算任务得分
        
        得分规则：
        - 按时完成：+100 分
        - 超时完成：-50 分
        - 路径长度影响：路径越短，得分越高
        
        参数:
            task: 任务对象
            completion_time: 实际完成时间
            complete_path_distance: 完整路径距离
            avg_path_length: 平均路径长度
        
        返回:
            score: 任务得分
        """
        # 基础得分
        if completion_time <= task.deadline:
            base_score = 100.0
        else:
            base_score = -50.0
        
        # 路径长度影响（基于完整路径）
        if complete_path_distance > 0:
            path_length_bonus = (avg_path_length / complete_path_distance) * 10.0
        else:
            path_length_bonus = 0.0
        
        # 总得分
        score = base_score + path_length_bonus
        
        return score
