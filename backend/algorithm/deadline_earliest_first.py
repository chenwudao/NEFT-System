from typing import List, Dict
from .scheduling_strategy import SchedulingStrategy
from backend.data.task import Task
from backend.data.vehicle import Vehicle


class DeadlineEarliestFirstStrategy(SchedulingStrategy):
    """
    最早截止优先（EDF）策略。
    将任务按 deadline 剩余时间升序排列，优先处理最紧迫的任务。
    适用场景：存在时效性强（生鲜/时间窗口）任务的调度。
    """

    def sort_tasks(self, vehicle: Vehicle, feasible_tasks: List[Task]) -> List[Task]:
        current_timestamp = self.global_params.get("timestamp", 0)
        return sorted(feasible_tasks, key=lambda t: t.deadline - current_timestamp)

    def execute(self) -> List[Dict]:
        for vehicle in self.idle_vehicles:
            if vehicle.id in self.assigned_vehicle_ids:
                continue
            self.generate_vehicle_command(vehicle)
            self.assigned_vehicle_ids.add(vehicle.id)

        return self.commands
