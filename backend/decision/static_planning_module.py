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

    def generate_global_plan(self, algorithm: str = "ortools") -> Optional[Plan]:
        """生成全局规划方案
        
        Args:
            algorithm: 使用的算法，"mip" 或 "genetic"
        """
        import logging
        import time
        
        current_timestamp = int(time.time())
        
        # 获取所有待处理任务，但只考虑已经出现（create_time <= current_timestamp）的任务
        all_pending_tasks = self.data_manager.get_pending_tasks()
        tasks = [
            task for task in all_pending_tasks
            if task.create_time <= current_timestamp
        ]
        
        # 记录被过滤的未来任务
        future_tasks = [
            task for task in all_pending_tasks
            if task.create_time > current_timestamp
        ]
        if future_tasks:
            logging.info(f"[StaticPlanning] Filtered {len(future_tasks)} future tasks (not yet available)")
        
        vehicles = self.data_manager.get_vehicles()
        charging_stations = self.data_manager.get_charging_stations()
        warehouse_pos = self.data_manager.warehouse_position

        if not tasks or not vehicles:
            logging.warning(f"[StaticPlanning] No available tasks or vehicles (filtered {len(future_tasks)} future tasks)")
            return None

        logging.info(f"[StaticPlanning] Generating plan with {algorithm} for {len(tasks)} tasks ({len(future_tasks)} future tasks filtered), {len(vehicles)} vehicles")

        # 求解策略：OR-Tools(免费) -> MIP(Gurobi) -> GA(启发式)
        solution = None
        
        # 1. 首先尝试 OR-Tools（完全免费，无限制）
        try:
            solution = self.algorithm_manager.solve_ortools(
                tasks, vehicles, charging_stations,
                (warehouse_pos.x, warehouse_pos.y)
            )
            if solution and solution.vehicle_assignments:
                logging.info(f"[StaticPlanning] OR-Tools solution: {len(solution.vehicle_assignments)} vehicles assigned")
            else:
                logging.warning("[StaticPlanning] OR-Tools returned no solution, trying MIP")
                solution = None
        except Exception as e:
            logging.warning(f"[StaticPlanning] OR-Tools failed: {e}, trying MIP")
            solution = None
        
        # 2. 如果 OR-Tools 失败，尝试 MIP（可能受限）
        if solution is None and algorithm == "mip":
            try:
                solution = self.algorithm_manager.solve_mip(
                    tasks, vehicles, charging_stations,
                    (warehouse_pos.x, warehouse_pos.y)
                )
                if solution and solution.vehicle_assignments:
                    logging.info(f"[StaticPlanning] MIP solution: {len(solution.vehicle_assignments)} vehicles assigned")
                else:
                    logging.warning("[StaticPlanning] MIP returned no solution, falling back to GA")
                    solution = None
            except Exception as e:
                logging.error(f"[StaticPlanning] MIP failed: {e}, falling back to GA")
                solution = None
        
        # 3. 如果前面都失败，使用 GA（总是可用）
        if solution is None:
            try:
                solution = self.algorithm_manager.solve_genetic(
                    tasks, vehicles, charging_stations,
                    (warehouse_pos.x, warehouse_pos.y)
                )
                if solution and solution.vehicle_assignments:
                    logging.info(f"[StaticPlanning] GA solution: {len(solution.vehicle_assignments)} vehicles assigned")
                else:
                    logging.warning("[StaticPlanning] GA also returned no solution")
            except Exception as e:
                logging.error(f"[StaticPlanning] GA failed: {e}")
                solution = None

        vehicle_routes = {}
        task_assignments = {}
        charging_schedule = {}
        total_distance = 0.0
        total_time = 0.0

        if solution and solution.vehicle_assignments:
            for vehicle_id, task_ids in solution.vehicle_assignments.items():
                vehicle_routes[vehicle_id] = task_ids
                for task_id in task_ids:
                    task_assignments[task_id] = vehicle_id

            total_distance = solution.total_distance
            total_time = solution.total_time

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
