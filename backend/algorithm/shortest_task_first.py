from typing import List, Dict
from .scheduling_strategy import SchedulingStrategy
from backend.data.task import Task, TaskStatus
from backend.data.vehicle import Vehicle

class ShortestTaskFirstStrategy(SchedulingStrategy):
    def sort_tasks(self, vehicle: Vehicle, feasible_tasks: List[Task]) -> List[Task]:
        return sorted(
            feasible_tasks,
            key=lambda t: self.path_calculator.calculate_distance_from_positions(
                [vehicle.position, t.position]
            )
        )

    def execute(self) -> List[Dict]:
        current_timestamp = self.global_params.get("timestamp", 0)
        for task in self.pending_tasks:
            if task.deadline < current_timestamp:
                task.update_status(TaskStatus.TIMEOUT)

        for vehicle in self.idle_vehicles:
            if vehicle.id in self.assigned_vehicle_ids:
                continue
            self.generate_vehicle_command(vehicle)
            self.assigned_vehicle_ids.add(vehicle.id)
        return self.commands
