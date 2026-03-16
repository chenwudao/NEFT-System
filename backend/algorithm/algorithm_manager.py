from typing import List, Dict, Optional
from backend.data.task import Task
from backend.data.vehicle import Vehicle
from backend.data.charging_station import ChargingStation
from backend.data.path_calculator import PathCalculator
from .solution import Solution
from .mip_solver import MIPSolver
from .genetic_algorithm import GeneticAlgorithm
from .clustering_algorithm import ClusteringAlgorithm
from .scheduling_strategy import SchedulingStrategy
from .shortest_task_first import ShortestTaskFirstStrategy
from .heaviest_task_first import HeaviestTaskFirstStrategy

class AlgorithmManager:
    def __init__(self, path_calculator: PathCalculator):
        self.path_calculator = path_calculator
        self.mip_solver = MIPSolver()
        self.genetic_algorithm = GeneticAlgorithm()
        self.clustering_algorithm = ClusteringAlgorithm()
        self.strategy_classes = {
            "shortest_task_first": ShortestTaskFirstStrategy,
            "heaviest_task_first": HeaviestTaskFirstStrategy,
            "genetic": ShortestTaskFirstStrategy,  # genetic 使用相同的实时调度策略
            "mip": ShortestTaskFirstStrategy,  # mip 也使用相同的实时调度策略
            "clustering+genetic": ShortestTaskFirstStrategy  # clustering+genetic 也使用相同的实时调度策略
        }

    def solve_mip(self, tasks: List[Task], vehicles: List[Vehicle],
                  charging_stations: List[ChargingStation],
                  warehouse_position: tuple) -> Optional[Solution]:
        return self.mip_solver.solve_with_gurobi(
            tasks, vehicles, charging_stations, warehouse_position
        )

    def solve_genetic(self, tasks: List[Task], vehicles: List[Vehicle],
                      charging_stations: List[ChargingStation],
                      warehouse_position: tuple) -> Solution:
        return self.genetic_algorithm.evolve(tasks, vehicles)

    def cluster_tasks(self, tasks: List[Task], method: str = "kmeans") -> List[List[Task]]:
        if method == "kmeans":
            return self.clustering_algorithm.kmeans_clustering(tasks)
        elif method == "region":
            return self.clustering_algorithm.region_partition(tasks)
        else:
            return [[task] for task in tasks]

    def schedule_realtime(self, strategy: str, idle_vehicles: List[Vehicle],
                          pending_tasks: List[Task], charging_stations: List[ChargingStation],
                          global_params: Dict) -> List[Dict]:
        print(f"Schedule realtime called with strategy: {strategy}, idle_vehicles: {len(idle_vehicles)}, pending_tasks: {len(pending_tasks)}")
        
        if strategy not in self.strategy_classes:
            print(f"Unknown strategy: {strategy}, using shortest_task_first")
            strategy = "shortest_task_first"

        strategy_class = self.strategy_classes[strategy]
        strategy_instance = strategy_class(
            idle_vehicles, pending_tasks, charging_stations,
            global_params, self.path_calculator
        )

        commands = strategy_instance.execute()
        print(f"Generated {len(commands)} commands")
        return commands

    def get_available_strategies(self) -> List[str]:
        return list(self.strategy_classes.keys())
