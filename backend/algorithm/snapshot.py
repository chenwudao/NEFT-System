"""算法的统一输入。

`Snapshot` 是算法看到的整个世界。它由 `DynamicSchedulingModule.capture()`
在每轮调度前创建，**对算法是只读的**——算法不应直接修改 Snapshot 里的对象，
只需返回 Command，由调用方落地。

使用场景示例：
    for vehicle in snapshot.vehicles_need_decision():
        tasks = snapshot.available_tasks()
        nearest = min(tasks, key=lambda t: snapshot.distance(vehicle.position, t.position))
        ...
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from backend.data.charging_station import ChargingStation
from backend.data.path_calculator import PathCalculator
from backend.data.position import Position
from backend.data.task import Task, TaskStatus
from backend.data.vehicle import Vehicle, VehicleStatus


@dataclass
class Snapshot:
    vehicles: List[Vehicle]
    tasks: List[Task]
    charging_stations: List[ChargingStation]
    warehouse_xy: Tuple[float, float]
    timestamp: int
    path_calculator: PathCalculator

    # ------------------------------------------------------------------
    # 构造：从 DataManager 拍一张当前快照
    # ------------------------------------------------------------------
    @classmethod
    def capture(cls, data_manager) -> "Snapshot":
        wh = data_manager.get_warehouse_position()
        import time

        return cls(
            vehicles=list(data_manager.get_vehicles()),
            tasks=list(data_manager.get_tasks()),
            charging_stations=list(data_manager.get_charging_stations()),
            warehouse_xy=(wh.x, wh.y),
            timestamp=int(time.time()),
            path_calculator=data_manager.path_calculator,
        )

    # ------------------------------------------------------------------
    # 对车辆的视图
    # ------------------------------------------------------------------
    def vehicles_need_decision(self) -> List[Vehicle]:
        """IDLE 且无目标，等调度器发话的车。"""
        return [
            v for v in self.vehicles
            if v.status == VehicleStatus.IDLE and not v.has_target()
        ]

    def idle_vehicles_at_warehouse(self) -> List[Vehicle]:
        """停在仓库、等新任务的车。"""
        wh = self.warehouse_xy
        return [
            v for v in self.vehicles_need_decision()
            if self._near_point((v.position.x, v.position.y), wh)
        ]

    def idle_vehicles_not_at_warehouse(self) -> List[Vehicle]:
        """刚到某个非仓库点、等新指示的车（比如刚送完一单）。"""
        wh = self.warehouse_xy
        return [
            v for v in self.vehicles_need_decision()
            if not self._near_point((v.position.x, v.position.y), wh)
        ]

    # ------------------------------------------------------------------
    # 对任务的视图
    # ------------------------------------------------------------------
    def available_tasks(self) -> List[Task]:
        """还没被派过的 PENDING 任务。"""
        return [t for t in self.tasks if t.status == TaskStatus.PENDING]

    def vehicle_pending_tasks(self, vehicle: Vehicle) -> List[Task]:
        """已经派给某辆车、但还没送到的任务（车上的货）。"""
        tid_set = set(vehicle.assigned_task_ids)
        return [
            t for t in self.tasks
            if t.id in tid_set and t.status in (TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS)
        ]

    def vehicle_undelivered_tasks(self, vehicle: Vehicle) -> List[Task]:
        """车上还没被送到的任务（status=ASSIGNED）——即还需绕去送的点。"""
        tid_set = set(vehicle.assigned_task_ids)
        return [
            t for t in self.tasks
            if t.id in tid_set and t.status == TaskStatus.ASSIGNED
        ]

    # ------------------------------------------------------------------
    # 路由便捷方法
    # ------------------------------------------------------------------
    def distance(self, a, b) -> float:
        """任意两点间的路网距离（米）。不可达返回 +inf。"""
        ax, ay = self._xy(a)
        bx, by = self._xy(b)
        try:
            return self.path_calculator.calculate_pair_distance((ax, ay), (bx, by))
        except Exception:
            return float("inf")

    def path(self, a, b) -> List[Tuple[float, float]]:
        """两点间 Dijkstra 最短路径，返回空列表表示不可达。"""
        ax, ay = self._xy(a)
        bx, by = self._xy(b)
        try:
            return self.path_calculator.find_shortest_path((ax, ay), (bx, by))
        except Exception:
            return []

    # ------------------------------------------------------------------
    # 小工具
    # ------------------------------------------------------------------
    @staticmethod
    def _xy(obj) -> Tuple[float, float]:
        if isinstance(obj, tuple):
            return float(obj[0]), float(obj[1])
        if isinstance(obj, Position):
            return float(obj.x), float(obj.y)
        if hasattr(obj, "position"):
            return float(obj.position.x), float(obj.position.y)
        raise TypeError(f"Cannot derive (x, y) from {type(obj).__name__}")

    @staticmethod
    def _near_point(a: Tuple[float, float], b: Tuple[float, float], eps: float = 1e-4) -> bool:
        return abs(a[0] - b[0]) < eps and abs(a[1] - b[1]) < eps
