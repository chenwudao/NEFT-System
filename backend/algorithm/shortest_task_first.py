from typing import List, Dict
from .scheduling_strategy import SchedulingStrategy
from backend.data.task import Task
from backend.data.vehicle import Vehicle

class ShortestTaskFirstStrategy(SchedulingStrategy):
    def sort_tasks(self, vehicle: Vehicle, feasible_tasks: List[Task]) -> List[Task]:
        def get_distance(task):
            try:
                return self.path_calculator.calculate_distance_from_positions(
                    [vehicle.position, task.position]
                )
            except Exception:
                # 路径不可达，返回无穷大距离（排在最后）
                return float('inf')
        
        return sorted(feasible_tasks, key=get_distance)

    def execute(self) -> List[Dict]:
        for vehicle in self.idle_vehicles:
            if vehicle.id in self.assigned_vehicle_ids:
                continue
            self.generate_vehicle_command(vehicle)
            self.assigned_vehicle_ids.add(vehicle.id)
        return self.commands
