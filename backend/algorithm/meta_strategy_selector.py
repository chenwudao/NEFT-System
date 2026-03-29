from typing import Dict, List, Any
from backend.data.task import Task
from backend.data.vehicle import Vehicle
from backend.data.charging_station import ChargingStation
from backend.data.path_calculator import PathCalculator
from backend.algorithm.scoring_config import (
    TASK_ASSIGN_REWARD,
    PRIORITY_REWARD,
    DISTANCE_PENALTY,
    ENERGY_PENALTY,
    OVERDUE_PENALTY_PER_MIN,
    IDLE_PENALTY
)


class MetaStrategySelector:
    """Evaluate candidate realtime strategies and pick the best one."""

    def __init__(self, path_calculator: PathCalculator):
        self.path_calculator = path_calculator

    def evaluate(
        self,
        candidate_commands: Dict[str, List[Dict[str, Any]]],
        pending_tasks: List[Task],
        vehicles: List[Vehicle],
        charging_stations: List[ChargingStation],
        current_timestamp: int,
    ) -> Dict[str, Any]:
        task_by_id = {task.id: task for task in pending_tasks}
        vehicle_by_id = {vehicle.id: vehicle for vehicle in vehicles}
        _ = charging_stations  # reserved for future queue-aware scoring

        strategy_scores: Dict[str, Dict[str, float]] = {}
        best_strategy = ""
        best_score = float("-inf")

        for strategy_name, commands in candidate_commands.items():
            details = self._score_commands(
                commands=commands,
                task_by_id=task_by_id,
                vehicle_by_id=vehicle_by_id,
                current_timestamp=current_timestamp,
            )
            strategy_scores[strategy_name] = details
            if details["total_score"] > best_score:
                best_score = details["total_score"]
                best_strategy = strategy_name

        if not best_strategy and strategy_scores:
            best_strategy = next(iter(strategy_scores.keys()))

        return {
            "selected_strategy": best_strategy,
            "strategy_scores": strategy_scores,
            "selection_reason": "meta_selector_best_score",
        }

    def _score_commands(
        self,
        commands: List[Dict[str, Any]],
        task_by_id: Dict[int, Task],
        vehicle_by_id: Dict[int, Vehicle],
        current_timestamp: int,
    ) -> Dict[str, float]:
        assigned_tasks = 0
        total_priority = 0.0
        total_distance = 0.0
        total_energy = 0.0
        overdue_penalty = 0.0
        idle_penalty = 0.0

        for command in commands:
            action_type = command.get("action_type")
            vehicle = vehicle_by_id.get(command.get("vehicle_id"))
            if action_type == "idle":
                idle_penalty += 1.0
                continue

            path = command.get("path", [])
            if len(path) >= 2 and vehicle is not None:
                try:
                    distance = self.path_calculator.calculate_distance(path)
                    total_distance += distance
                    total_energy += distance * vehicle.unit_energy_consumption
                except Exception:
                    # keep scoring robust even when a command path is malformed
                    total_distance += 0.0

            eta = float(command.get("estimated_time", 0.0))
            for task_id in command.get("assigned_tasks", []):
                task = task_by_id.get(task_id)
                if task is None:
                    continue
                assigned_tasks += 1
                total_priority += float(task.priority)
                expected_finish = current_timestamp + eta
                if expected_finish > task.deadline:
                    # normalize tardiness to minutes to avoid dominating score
                    overdue_penalty += (expected_finish - task.deadline) / 60.0

        total_score = (
            assigned_tasks * TASK_ASSIGN_REWARD
            + total_priority * PRIORITY_REWARD
            - total_distance * DISTANCE_PENALTY
            - total_energy * ENERGY_PENALTY
            - overdue_penalty * OVERDUE_PENALTY_PER_MIN
            - idle_penalty * IDLE_PENALTY
        )

        return {
            "total_score": float(total_score),
            "assigned_tasks": float(assigned_tasks),
            "priority_gain": float(total_priority),
            "distance_cost": float(total_distance),
            "energy_cost": float(total_energy),
            "overdue_penalty": float(overdue_penalty),
            "idle_penalty": float(idle_penalty),
        }
