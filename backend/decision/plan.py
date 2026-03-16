from typing import List, Dict, Optional
from dataclasses import dataclass
from backend.data.task import Task, TaskStatus
from backend.data.vehicle import Vehicle
from backend.data.charging_station import ChargingStation
from backend.data.position import Position

@dataclass
class Plan:
    vehicle_routes: Dict[int, List[int]]
    task_assignments: Dict[int, int]
    charging_schedule: Dict[int, List[str]]
    total_distance: float
    total_time: float
    objective_value: float

    def to_dict(self) -> Dict:
        return {
            "vehicle_routes": self.vehicle_routes,
            "task_assignments": self.task_assignments,
            "charging_schedule": self.charging_schedule,
            "total_distance": self.total_distance,
            "total_time": self.total_time,
            "objective_value": self.objective_value
        }
