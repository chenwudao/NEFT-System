from typing import List, Optional
from dataclasses import dataclass
from .position import Position

@dataclass
class ChargingStation:
    id: str
    position: Position
    capacity: int
    queue_count: int
    charging_vehicles: List[int]
    load_pressure: float
    charging_rate: float

    def get_position(self) -> Position:
        return self.position

    def get_queue_count(self) -> int:
        return self.queue_count

    def get_load_pressure(self) -> float:
        return self.load_pressure

    def get_available_capacity(self) -> int:
        return max(0, self.capacity - len(self.charging_vehicles))

    def add_vehicle(self, vehicle_id: int):
        if vehicle_id not in self.charging_vehicles:
            self.charging_vehicles.append(vehicle_id)
            self.queue_count = len(self.charging_vehicles)
            self.update_load_pressure()

    def remove_vehicle(self, vehicle_id: int):
        if vehicle_id in self.charging_vehicles:
            self.charging_vehicles.remove(vehicle_id)
            self.queue_count = len(self.charging_vehicles)
            self.update_load_pressure()

    def update_load_pressure(self):
        if self.capacity > 0:
            self.load_pressure = len(self.charging_vehicles) / self.capacity
        else:
            self.load_pressure = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "position": {"x": self.position.x, "y": self.position.y},
            "capacity": self.capacity,
            "queue_count": self.queue_count,
            "charging_vehicles": self.charging_vehicles,
            "load_pressure": self.load_pressure,
            "charging_rate": self.charging_rate,
            "available_capacity": self.get_available_capacity()
        }
