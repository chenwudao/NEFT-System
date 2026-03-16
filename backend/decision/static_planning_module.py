from typing import List, Dict, Optional
from datetime import datetime, timedelta
from backend.data.data_manager import DataManager
from backend.data.task import Task, TaskStatus
from backend.data.vehicle import Vehicle, VehicleStatus
from backend.data.charging_station import ChargingStation
from backend.algorithm.algorithm_manager import AlgorithmManager
from backend.algorithm.solution import Solution
from .plan import Plan

class StaticPlanningModule:
    def __init__(self, data_manager: DataManager, algorithm_manager: AlgorithmManager):
        self.data_manager = data_manager
        self.algorithm_manager = algorithm_manager
        self.planning_interval = 3600
        self.historical_tasks: List[Task] = []
        self.current_plan: Optional[Plan] = None

    def set_planning_interval(self, interval: int):
        self.planning_interval = interval

    def collect_historical_data(self, hours: int = 24) -> List[Task]:
        current_time = int(datetime.now().timestamp())
        cutoff_time = current_time - hours * 3600

        all_tasks = self.data_manager.get_tasks()
        self.historical_tasks = [
            task for task in all_tasks
            if task.create_time >= cutoff_time
        ]

        return self.historical_tasks

    def predict_tasks(self, prediction_window: int = 3600) -> List[Task]:
        predicted_tasks = []

        if not self.historical_tasks:
            return predicted_tasks

        avg_weight = sum(task.weight for task in self.historical_tasks) / len(self.historical_tasks)
        current_time = int(datetime.now().timestamp())

        for i in range(min(10, len(self.historical_tasks))):
            predicted_task = Task(
                id=current_time + i,
                position=self.historical_tasks[i].position,
                weight=avg_weight,
                create_time=current_time + i * 60,
                deadline=current_time + prediction_window + i * 60,
                priority=self.historical_tasks[i].priority
            )
            predicted_tasks.append(predicted_task)

        return predicted_tasks

    def generate_global_plan(self) -> Optional[Plan]:
        tasks = self.data_manager.get_pending_tasks()
        vehicles = self.data_manager.get_vehicles()
        charging_stations = self.data_manager.get_charging_stations()
        warehouse_pos = self.data_manager.warehouse_position

        if not tasks or not vehicles:
            return None

        task_clusters = self.algorithm_manager.cluster_tasks(tasks, method="kmeans")

        vehicle_routes = {}
        task_assignments = {}
        charging_schedule = {}
        total_distance = 0.0
        total_time = 0.0

        for cluster in task_clusters:
            if not cluster:
                continue

            solution = self.algorithm_manager.solve_genetic(
                cluster, vehicles, charging_stations, 
                (warehouse_pos.x, warehouse_pos.y)
            )

            if solution and solution.vehicle_assignments:
                for vehicle_id, task_ids in solution.vehicle_assignments.items():
                    if vehicle_id not in vehicle_routes:
                        vehicle_routes[vehicle_id] = []
                    vehicle_routes[vehicle_id].extend(task_ids)

                    for task_id in task_ids:
                        task_assignments[task_id] = vehicle_id

                total_distance += solution.total_distance
                total_time += solution.total_time

        for vehicle_id in vehicle_routes:
            charging_schedule[vehicle_id] = []

        self.current_plan = Plan(
            vehicle_routes=vehicle_routes,
            task_assignments=task_assignments,
            charging_schedule=charging_schedule,
            total_distance=total_distance,
            total_time=total_time,
            objective_value=total_distance + total_time
        )

        return self.current_plan

    def evaluate_plan(self, plan: Plan) -> float:
        if not plan:
            return 0.0

        score = 0.0

        for task_id, vehicle_id in plan.task_assignments.items():
            task = self.data_manager.get_task(task_id)
            vehicle = self.data_manager.get_vehicle(vehicle_id)

            if task and vehicle:
                distance = self.data_manager.path_calculator.calculate_distance_from_positions(
                    [vehicle.position, task.position]
                )
                score += 1.0 / (1.0 + distance)

        return score

    def execute_planning(self) -> Optional[Plan]:
        self.collect_historical_data()
        plan = self.generate_global_plan()

        if plan:
            self.evaluate_plan(plan)

        return plan
