from typing import List, Dict
from .scheduling_strategy import SchedulingStrategy
from backend.data.task import Task
from backend.data.vehicle import Vehicle


class PriorityBasedStrategy(SchedulingStrategy):
    """
    明确优先级策略（Priority-Based）。
    按任务优先级降序分配；同优先级时，按车辆到任务的距离升序（就近优先）。
    适用场景：混合优先级任务场景，高优任务必须率先处理。
    """

    def sort_tasks(self, vehicle: Vehicle, feasible_tasks: List[Task]) -> List[Task]:
        def get_sort_key(task):
            try:
                distance = self.path_calculator.calculate_distance_from_positions(
                    [vehicle.position, task.position]
                )
            except Exception:
                # 路径不可达，返回无穷大距离
                distance = float('inf')
            return (-task.priority, distance)
        
        return sorted(feasible_tasks, key=get_sort_key)

    def execute(self) -> List[Dict]:
        for vehicle in self.idle_vehicles:
            if vehicle.id in self.assigned_vehicle_ids:
                continue
            self.generate_vehicle_command(vehicle)
            self.assigned_vehicle_ids.add(vehicle.id)

        return self.commands
