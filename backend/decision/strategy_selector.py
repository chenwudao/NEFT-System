from typing import List, Dict, Optional
from backend.data.task import Task
from backend.data.vehicle import Vehicle
from backend.data.position import Position

class StrategySelector:
    def __init__(self):
        self.strategy_performance: Dict[str, float] = {
            "shortest_task_first": 0.0,
            "heaviest_task_first": 0.0
        }
        self.heavy_task_ratio = 0.8
        self.light_task_ratio = 0.2
        self.long_distance_threshold = 5.0

    def analyze_task_features(self, tasks: List[Task]) -> Dict:
        if not tasks:
            return {
                "avg_weight": 0.0,
                "max_weight": 0.0,
                "avg_distance": 0.0,
                "task_count": 0,
                "weight_variance": 0.0
            }

        weights = [task.weight for task in tasks]
        avg_weight = sum(weights) / len(weights)
        max_weight = max(weights)
        weight_variance = sum((w - avg_weight) ** 2 for w in weights) / len(weights)

        return {
            "avg_weight": avg_weight,
            "max_weight": max_weight,
            "avg_distance": 0.0,
            "task_count": len(tasks),
            "weight_variance": weight_variance
        }

    def evaluate_system_state(self, vehicles: List[Vehicle], 
                             warehouse_pos: Position) -> Dict:
        if not vehicles:
            return {
                "avg_battery": 0.0,
                "avg_load": 0.0,
                "idle_count": 0,
                "total_capacity": 0.0
            }

        batteries = [v.battery for v in vehicles]
        loads = [v.current_load for v in vehicles]
        idle_count = sum(1 for v in vehicles if v.status.value == "idle")

        return {
            "avg_battery": sum(batteries) / len(batteries),
            "avg_load": sum(loads) / len(loads),
            "idle_count": idle_count,
            "total_capacity": sum(v.max_load for v in vehicles)
        }

    def select_strategy(self, tasks: List[Task], vehicles: List[Vehicle],
                      global_params: Dict) -> str:
        if not tasks or not vehicles:
            return "shortest_task_first"

        try:
            task_features = self.analyze_task_features(tasks)
            system_state = self.evaluate_system_state(
                vehicles, global_params.get("warehouse_pos", Position(x=0, y=0))
            )

            avg_vehicle_remaining_load = system_state["total_capacity"] - system_state["avg_load"] * len(vehicles)
            avg_vehicle_remaining_load = avg_vehicle_remaining_load / len(vehicles) if vehicles else 0

            if task_features["max_weight"] > avg_vehicle_remaining_load * self.heavy_task_ratio:
                return "heaviest_task_first"

            elif (task_features["avg_weight"] < avg_vehicle_remaining_load * self.light_task_ratio
                  and task_features["avg_distance"] > global_params.get("long_distance_threshold", 
                                                                              self.long_distance_threshold)):
                return "shortest_task_first"

            else:
                return "shortest_task_first"

        except Exception as e:
            print(f"自动选择策略失败，使用默认策略：{e}")
            return "shortest_task_first"

    def evaluate_performance(self, strategy: str, metrics: Dict) -> float:
        if strategy not in self.strategy_performance:
            return 0.0

        completion_rate = metrics.get("completion_rate", 0.0)
        avg_completion_time = metrics.get("avg_completion_time", 0.0)
        total_distance = metrics.get("total_distance", 0.0)

        if avg_completion_time > 0:
            time_score = 1.0 / avg_completion_time
        else:
            time_score = 0.0

        if total_distance > 0:
            distance_score = 1.0 / total_distance
        else:
            distance_score = 0.0

        performance = (completion_rate * 0.5 + time_score * 0.3 + distance_score * 0.2)

        self.strategy_performance[strategy] = performance

        return performance

    def get_best_strategy(self) -> str:
        if not self.strategy_performance:
            return "shortest_task_first"

        return max(self.strategy_performance.items(), key=lambda x: x[1])[0]

    def update_strategy_performance(self, strategy: str, performance: float):
        if strategy in self.strategy_performance:
            self.strategy_performance[strategy] = performance

    def get_strategy_performance(self) -> Dict[str, float]:
        return self.strategy_performance.copy()
