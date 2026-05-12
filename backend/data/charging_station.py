from typing import List, Optional
from dataclasses import dataclass, field
from .position import Position

@dataclass
class ChargingStation:
    id: str
    position: Position
    capacity: int           # 充电桩数量（并发充电上限）
    queue_count: int        # 总占用数（充电中 + 排队中）
    charging_vehicles: List[int]   # 正在充电的车辆ID（len <= capacity）
    load_pressure: float    # 综合负荷压力 [0,1]
    charging_rate: float    # 充电速率（保留，向后兼容；实际由 vehicle.charging_power 控制）
    waiting_queue: List[int] = field(default_factory=list)  # 排队等待的车辆ID（新增）

    def get_position(self) -> Position:
        return self.position

    def get_queue_count(self) -> int:
        return self.queue_count

    def get_load_pressure(self) -> float:
        return self.load_pressure

    def get_available_slots(self) -> int:
        """当前可用充电桩数量"""
        return max(0, self.capacity - len(self.charging_vehicles))

    def get_waiting_count(self) -> int:
        """排队等待数量"""
        return len(self.waiting_queue)

    def add_vehicle(self, vehicle_id: int) -> str:
        """
        添加车辆到充电站。
        返回值：
            'charging'  — 直接进入充电桩
            'waiting'   — 充电桩已满，进入等待队列
            'existing'  — 车辆已在充电站（忽略）
        """
        if vehicle_id in self.charging_vehicles or vehicle_id in self.waiting_queue:
            return 'existing'

        if len(self.charging_vehicles) < self.capacity:
            self.charging_vehicles.append(vehicle_id)
            result = 'charging'
        else:
            self.waiting_queue.append(vehicle_id)
            result = 'waiting'

        self.queue_count = len(self.charging_vehicles) + len(self.waiting_queue)
        self.update_load_pressure()
        return result

    def remove_vehicle(self, vehicle_id: int) -> Optional[int]:
        """
        从充电站移除车辆（充电完成或主动离开）。
        若充电桩列表中有空位且等待队列非空，自动晋升队首车辆。
        返回值：被晋升的车辆ID（若有），否则 None
        """
        promoted_vehicle_id = None

        if vehicle_id in self.charging_vehicles:
            self.charging_vehicles.remove(vehicle_id)
            # 自动晋升等待队列中的第一辆车
            if self.waiting_queue:
                promoted_vehicle_id = self.waiting_queue.pop(0)
                self.charging_vehicles.append(promoted_vehicle_id)
        elif vehicle_id in self.waiting_queue:
            self.waiting_queue.remove(vehicle_id)

        self.queue_count = len(self.charging_vehicles) + len(self.waiting_queue)
        self.update_load_pressure()
        return promoted_vehicle_id

    def update_load_pressure(self):
        """
        负荷压力 = 当前总占用 / (充电桩容量 × 2)
        充电中满员=0.5，充电+等待都满=1.0
        """
        total_occupied = len(self.charging_vehicles) + len(self.waiting_queue)
        max_capacity = self.capacity * 2  # 充电桩数 + 相同数量的等待位
        self.load_pressure = min(1.0, total_occupied / max_capacity) if max_capacity > 0 else 0.0

    def is_full(self) -> bool:
        """充电桩是否全满（无法立即充电）"""
        return len(self.charging_vehicles) >= self.capacity

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "position": {"x": self.position.x, "y": self.position.y},
            "capacity": self.capacity,
            "queue_count": self.queue_count,
            "charging_vehicles": self.charging_vehicles,
            "waiting_queue": self.waiting_queue,
            "load_pressure": self.load_pressure,
            "charging_rate": self.charging_rate,
            "available_slots": self.get_available_slots(),
            "waiting_count": self.get_waiting_count(),
        }
