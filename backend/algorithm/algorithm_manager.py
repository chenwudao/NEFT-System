from typing import List, Dict, Optional
from backend.data.task import Task, apply_deadline_timeouts
from backend.data.vehicle import Vehicle
from backend.data.charging_station import ChargingStation
from backend.data.path_calculator import PathCalculator
from backend.config import config
from .solution import Solution
from .mip_solver import MIPSolver
from .genetic_algorithm import GeneticAlgorithm
from .ortools_solver import ORToolsSolver
from .scheduling_strategy import SchedulingStrategy
from .shortest_task_first import ShortestTaskFirstStrategy
from .priority_based_strategy import PriorityBasedStrategy
from .composite_score_strategy import CompositeScoreStrategy


class AlgorithmManager:
    def __init__(self, path_calculator: PathCalculator):
        self.path_calculator = path_calculator
        self.mip_solver = MIPSolver(path_calculator)
        self.ortools_solver = ORToolsSolver(path_calculator)

        ga_conf = config.get_algorithm_config("genetic")
        # 修复 B8：将 path_calculator 注入 GA，使适应度函数能使用真实路网成本
        self.genetic_algorithm = GeneticAlgorithm(
            population_size=ga_conf.get("population_size", 100),
            max_generations=ga_conf.get("max_generations", 300),
            mutation_rate=ga_conf.get("mutation_rate", 0.1),
            crossover_rate=ga_conf.get("crossover_rate", 0.8),
            path_calculator=path_calculator,
        )

        # 实时调度策略（精简为3个核心策略）
        self.strategy_classes = {
            "shortest_task_first":  ShortestTaskFirstStrategy,
            "priority_based":       PriorityBasedStrategy,
            "composite_score":      CompositeScoreStrategy,
        }

    # -------------------------------------------------------------------
    # 静态规划接口（GA / MIP）
    # -------------------------------------------------------------------

    def solve_mip(self, tasks: List[Task], vehicles: List[Vehicle],
                  charging_stations: List[ChargingStation],
                  warehouse_position: tuple) -> Optional[Solution]:
        return self.mip_solver.solve_with_gurobi(
            tasks, vehicles, charging_stations, warehouse_position
        )

    def solve_genetic(self, tasks: List[Task], vehicles: List[Vehicle],
                      charging_stations: List[ChargingStation],
                      warehouse_position: tuple) -> Solution:
        # 修复 B8：将仓库位置传入 GA 供适应度计算使用
        self.genetic_algorithm.warehouse_pos = warehouse_position
        return self.genetic_algorithm.evolve(tasks, vehicles)

    def solve_ortools(self, tasks: List[Task], vehicles: List[Vehicle],
                      charging_stations: List[ChargingStation],
                      warehouse_position: tuple) -> Optional[Solution]:
        """使用 OR-Tools + CBC 开源求解器（完全免费）"""
        return self.ortools_solver.solve(tasks, vehicles, charging_stations, warehouse_position)

    # -------------------------------------------------------------------
    # 实时调度接口（策略模式）
    # -------------------------------------------------------------------

    def schedule_realtime(self, strategy: str, idle_vehicles: List[Vehicle],
                          pending_tasks: List[Task], charging_stations: List[ChargingStation],
                          global_params: Dict) -> List[Dict]:
        ts = int(global_params.get("timestamp", 0))
        apply_deadline_timeouts(pending_tasks, ts)

        if strategy not in self.strategy_classes:
            strategy = "shortest_task_first"

        strategy_class = self.strategy_classes[strategy]
        strategy_instance = strategy_class(
            idle_vehicles, pending_tasks, charging_stations,
            global_params, self.path_calculator
        )
        return strategy_instance.execute()

    def get_available_strategies(self) -> List[str]:
        return list(self.strategy_classes.keys())
