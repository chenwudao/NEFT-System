from typing import List, Dict, Optional
from dataclasses import dataclass

@dataclass
class Solution:
    objective_value: float
    routes: List[List[int]]
    vehicle_assignments: Dict[int, List[int]]
    charging_stations_used: List[str]
    total_distance: float
    total_time: float

    def to_dict(self) -> Dict:
        return {
            "objective_value": self.objective_value,
            "routes": self.routes,
            "vehicle_assignments": self.vehicle_assignments,
            "charging_stations_used": self.charging_stations_used,
            "total_distance": self.total_distance,
            "total_time": self.total_time
        }
