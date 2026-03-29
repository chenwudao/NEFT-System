from typing import List, Dict
from .scheduling_strategy import SchedulingStrategy
from backend.data.task import Task, TaskStatus
from backend.data.vehicle import Vehicle

class HeaviestTaskFirstStrategy(SchedulingStrategy):
    def sort_tasks(self, vehicle: Vehicle, feasible_tasks: List[Task]) -> List[Task]:
        return sorted(feasible_tasks, key=lambda t: t.weight, reverse=True)

    def execute(self) -> List[Dict]:
        sorted_tasks = sorted(
            [t for t in self.pending_tasks if t.status == TaskStatus.PENDING],
            key=lambda t: t.weight,
            reverse=True,
        )
        for task in sorted_tasks:
            if task.id in self.assigned_task_ids:
                continue

            suitable_vehicles = [
                v for v in self.idle_vehicles
                if v.id not in self.assigned_vehicle_ids
                   and (v.max_load - v.current_load) >= task.weight
            ]
            if not suitable_vehicles:
                continue

            suitable_vehicles.sort(
                key=lambda v: self.path_calculator.calculate_distance_from_positions(
                    [v.position, task.position]
                )
            )
            target_vehicle = suitable_vehicles[0]
            self.assigned_vehicle_ids.add(target_vehicle.id)
            self.generate_vehicle_command(target_vehicle)

        for vehicle in self.idle_vehicles:
            if vehicle.id not in self.assigned_vehicle_ids:
                self.commands.append(self._generate_idle_command(vehicle))

        return self.commands
