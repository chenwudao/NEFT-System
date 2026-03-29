from typing import Optional, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from .position import Position

class VehicleStatus(Enum):
    IDLE = "idle"
    TRANSPORTING_TO_TASK = "transporting_to_task"
    DELIVERING = "delivering"
    RETURNING_TO_WAREHOUSE = "returning_to_warehouse"
    TRANSPORTING = "transporting"       # 通用运输状态（向后兼容）
    CHARGING = "charging"               # 正在充电
    WAITING_CHARGE = "waiting_charge"   # 排队等待充电桩（新增）
    MAINTENANCE = "maintenance"

@dataclass
class Vehicle:
    id: int
    position: Position
    battery: float
    max_battery: float
    current_load: float
    max_load: float
    unit_energy_consumption: float
    speed: float = 10.0                 # m/s（已修正：原为0.1度/s，单位错误）
    vehicle_type: str = "medium"        # 车型：small/medium/large（新增）
    charging_power: float = 0.022       # 充电功率 kWh/s（新增，medium默认）
    status: VehicleStatus = VehicleStatus.IDLE
    assigned_task_ids: list = None
    current_path: list = None
    charging_station_id: Optional[str] = None
    complete_path: list = None
    path_progress: float = 0.0
    energy_consumption: float = 0.0
    total_distance_traveled: float = 0.0

    def __post_init__(self):
        if self.assigned_task_ids is None:
            self.assigned_task_ids = []
        if self.current_path is None:
            self.current_path = []
        if self.complete_path is None:
            self.complete_path = []

    def get_position(self) -> Position:
        return self.position

    def get_battery(self) -> float:
        return self.battery

    def get_current_load(self) -> float:
        return self.current_load

    def get_battery_percentage(self) -> float:
        return (self.battery / self.max_battery) * 100 if self.max_battery > 0 else 0

    def get_load_percentage(self) -> float:
        return (self.current_load / self.max_load) * 100 if self.max_load > 0 else 0

    def get_remaining_load(self) -> float:
        """剩余可载重（kg）"""
        return max(0.0, self.max_load - self.current_load)

    def is_waiting_for_charge(self) -> bool:
        return self.status == VehicleStatus.WAITING_CHARGE

    def is_charging(self) -> bool:
        return self.status == VehicleStatus.CHARGING

    def is_idle(self) -> bool:
        return self.status == VehicleStatus.IDLE

    def update_position(self, position: Position):
        self.position = position

    def update_battery(self, battery: float):
        self.battery = max(0, min(battery, self.max_battery))

    def update_load(self, load: float):
        self.current_load = max(0, min(load, self.max_load))

    def add_task(self, task_id: int):
        if task_id not in self.assigned_task_ids:
            self.assigned_task_ids.append(task_id)

    def remove_task(self, task_id: int):
        if task_id in self.assigned_task_ids:
            self.assigned_task_ids.remove(task_id)

    def update_status(self, status: VehicleStatus):
        self.status = status

    def to_dict(self) -> dict:
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
            "assigned_task_ids": self.assigned_task_ids,
            "current_path": self.current_path,
            "charging_station_id": self.charging_station_id,
            "complete_path": self.complete_path,
            "path_progress": self.path_progress,
            "energy_consumption": self.energy_consumption,
            "total_distance_traveled": self.total_distance_traveled
        }
