"""车辆实体。

重构后语义（必读）：
    - 车辆要么停在某个图节点上（IDLE/CHARGING），要么正沿最短路径前往
      `current_target_xy`（MOVING_*）。
    - 车辆"正在送哪一批货"由 `assigned_task_ids` 表示。
    - 每次一辆车 IDLE 且已在一个"决策点"（仓库 / 某个任务点 / 充电站），
      调度器都会被再次询问下一步。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

from .position import Position


class VehicleStatus(Enum):
    """车辆状态。注意：'车的状态' 描述的是"车本身去哪 / 在干嘛"，
    与"货物的状态"分开（货物的状态在 Task.status 里独立维护）。
    一辆车可以同时承载多个货物，但它自己只有一个状态。
    """
    IDLE = "idle"                              # 在某节点，等待下一个调度命令
    MOVING_TO_TASK = "moving_to_task"          # 正前往某个任务点（去卸一件货）
    MOVING_TO_NODE = "moving_to_node"          # 正前往一个"特殊节点"
                                               #   场景 1: 一批任务的 MST 汇聚节点
                                               #   场景 2: 与其他车的接力碰头点
                                               #   场景 3: 任何"没有业务语义、只是要求车走到某个坐标"的需求
    MOVING_TO_CHARGE = "moving_to_charge"      # 正前往充电站
    MOVING_TO_WAREHOUSE = "moving_to_warehouse"  # 正返回仓库
    CHARGING = "charging"                      # 在充电站充电
    WAITING_CHARGE = "waiting_charge"          # 充电站桩位已满，排队
    STRANDED = "stranded"                      # 电量耗尽，原地抛锚，不再接受任何命令


@dataclass
class Vehicle:
    id: int
    position: Position
    battery: float
    max_battery: float
    current_load: float
    max_load: float
    unit_energy_consumption: float  # kWh等效/m
    speed: float = 10.0              # m/s
    vehicle_type: str = "medium"
    charging_power: float = 0.022    # kWh/s

    status: VehicleStatus = VehicleStatus.IDLE

    # 当前车上挂着的任务（到仓库才会被统一标记 COMPLETED）
    assigned_task_ids: List[int] = field(default_factory=list)

    # 最短路径运动相关（都在 Position/坐标层面，不存图 node id）
    #   - current_target_xy: 当前这一步要到的终点（可能是任务点 / 站 / 仓库）
    #   - current_route:     从 position 到 target 的 Dijkstra 路径（逐段推进用）
    #   - _route_index:      当前走到 route 的哪一段（0 表示还没开始走下一段）
    #   - current_task_id:   MOVING_TO_TASK 时，对应的是哪个 task
    current_target_xy: Optional[Tuple[float, float]] = None
    current_route: List[Tuple[float, float]] = field(default_factory=list)
    _route_index: int = 0
    current_task_id: Optional[int] = None

    # 充电相关
    charging_station_id: Optional[str] = None

    # 统计指标
    energy_consumption: float = 0.0         # 当前"这一趟"累计能耗（回仓库时清零）
    total_distance_traveled: float = 0.0    # 车辆全生命周期累计里程

    # 本 tick 走过的折线（用于前端沿真实道路平滑插值，避免"直线切弯"）：
    #   [tick 开始位置, 途经节点1, 途经节点2, ..., tick 结束位置]
    # 每个 tick 开始时应当先被清空，没动的车保持空列表。
    tick_path: List[Tuple[float, float]] = field(default_factory=list)

    # ------------------------------------------------------------------
    # 基础查询
    # ------------------------------------------------------------------
    def get_battery_percentage(self) -> float:
        return (self.battery / self.max_battery) * 100 if self.max_battery > 0 else 0.0

    def get_load_percentage(self) -> float:
        return (self.current_load / self.max_load) * 100 if self.max_load > 0 else 0.0

    def get_remaining_load(self) -> float:
        return max(0.0, self.max_load - self.current_load)

    def is_idle(self) -> bool:
        return self.status == VehicleStatus.IDLE

    def is_moving(self) -> bool:
        return self.status in (
            VehicleStatus.MOVING_TO_TASK,
            VehicleStatus.MOVING_TO_NODE,
            VehicleStatus.MOVING_TO_CHARGE,
            VehicleStatus.MOVING_TO_WAREHOUSE,
        )

    def is_charging(self) -> bool:
        return self.status == VehicleStatus.CHARGING

    def is_waiting_for_charge(self) -> bool:
        return self.status == VehicleStatus.WAITING_CHARGE

    def is_stranded(self) -> bool:
        return self.status == VehicleStatus.STRANDED

    def has_target(self) -> bool:
        return self.current_target_xy is not None

    # ------------------------------------------------------------------
    # 基础变更
    # ------------------------------------------------------------------
    def update_position(self, position: Position):
        self.position = position

    def update_battery(self, battery: float):
        self.battery = max(0.0, min(battery, self.max_battery))

    def update_load(self, load: float):
        self.current_load = max(0.0, min(load, self.max_load))

    def update_status(self, status: VehicleStatus):
        self.status = status

    def add_task(self, task_id: int):
        if task_id not in self.assigned_task_ids:
            self.assigned_task_ids.append(task_id)

    def remove_task(self, task_id: int):
        if task_id in self.assigned_task_ids:
            self.assigned_task_ids.remove(task_id)

    def set_route(
        self,
        target_xy: Tuple[float, float],
        route: List[Tuple[float, float]],
    ) -> None:
        """准备前往一个新目的地：记录 target + 整条路径，重置段索引。"""
        self.current_target_xy = target_xy
        self.current_route = list(route) if route else [target_xy]
        self._route_index = 0

    def clear_route(self) -> None:
        """到达后清空路径信息。"""
        self.current_target_xy = None
        self.current_route = []
        self._route_index = 0
        self.current_task_id = None

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------
    def get_path_progress(self) -> float:
        """当前路径走了多少（0~1），用于前端进度条显示。"""
        if not self.current_route or len(self.current_route) < 2:
            return 0.0
        total = max(len(self.current_route) - 1, 1)
        return min(1.0, self._route_index / total)

    def get_remaining_route(self) -> List[Tuple[float, float]]:
        """从车辆当前实时位置到 target 的"剩余"路径。

        第一个点 = 当前 position（可能在某段中间），
        后面跟着当前还没走过的所有图节点，最后一个点 = current_target_xy。
        用于前端画"从车头到目的地"的实时高亮线。
        """
        if not self.current_route or len(self.current_route) < 2:
            return []
        # _route_index 是"最近一次已经到达的节点下标"，
        # 下一个还没到的节点是 _route_index + 1
        next_idx = self._route_index + 1
        if next_idx >= len(self.current_route):
            return []
        here = (self.position.x, self.position.y)
        rest = list(self.current_route[next_idx:])
        return [here] + rest

    def to_dict(self) -> dict:
        # 把 current_route 同时以 [{x,y}, ...] 形式导出为 complete_path，
        # 便于前端沿用旧字段画线。
        route_dicts = [{"x": p[0], "y": p[1]} for p in self.current_route]
        remaining_dicts = [
            {"x": p[0], "y": p[1]} for p in self.get_remaining_route()
        ]
        return {
            "id": self.id,
            "position": {"x": self.position.x, "y": self.position.y},
            "battery": self.battery,
            "max_battery": self.max_battery,
            "battery_percentage": self.get_battery_percentage(),
            "current_load": self.current_load,
            "max_load": self.max_load,
            "load_percentage": self.get_load_percentage(),
            "unit_energy_consumption": self.unit_energy_consumption,
            "speed": self.speed,
            "vehicle_type": self.vehicle_type,
            "charging_power": self.charging_power,
            "status": self.status.value,
            "assigned_task_ids": list(self.assigned_task_ids),
            "current_target": (
                {"x": self.current_target_xy[0], "y": self.current_target_xy[1]}
                if self.current_target_xy is not None
                else None
            ),
            "current_route": route_dicts,
            "remaining_route": remaining_dicts,         # 从"车当前位置"出发的剩余路径
            "tick_waypoints": [                         # 本 tick 真实走过的折线
                {"x": p[0], "y": p[1]} for p in self.tick_path
            ],
            "complete_path": route_dicts,               # 向后兼容前端
            "path_progress": self.get_path_progress(),  # 向后兼容前端
            "charging_station_id": self.charging_station_id,
            "energy_consumption": self.energy_consumption,
            "total_distance_traveled": self.total_distance_traveled,
        }
