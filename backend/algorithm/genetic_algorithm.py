from typing import List, Dict, Optional, Tuple
import random
import copy
from backend.data.task import Task
from backend.data.vehicle import Vehicle
from backend.data.charging_station import ChargingStation
from backend.data.path_calculator import PathCalculator
from .solution import Solution


class Gene:
    def __init__(self, tasks: List[int], vehicle_assignments: Dict[int, List[int]], fitness: float = 0.0):
        self.tasks = tasks
        self.vehicle_assignments = vehicle_assignments
        self.fitness = fitness


class GeneticAlgorithm:
    """
    遗传算法任务调度优化器。

    改进（B8 修复）：
    - 适应度函数引入真实路网路径成本（仓库→任务→仓库往返距离之和）
    - evolve() 返回真实 total_distance
    - 构造函数接受 path_calculator 和 warehouse_pos 以支持路网计算
    """

    def __init__(
        self,
        population_size: int = 100,
        max_generations: int = 300,
        mutation_rate: float = 0.1,
        crossover_rate: float = 0.8,
        path_calculator: Optional[PathCalculator] = None,
        warehouse_pos: Tuple[float, float] = (0.0, 0.0),
    ):
        self.population_size = population_size
        self.max_generations = max_generations
        self.mutation_rate = mutation_rate
        self.crossover_rate = crossover_rate
        self.path_calculator = path_calculator
        self.warehouse_pos = warehouse_pos
        self.population: List[Gene] = []

    def initialize_population(self, tasks: List[Task], vehicles: List[Vehicle]):
        self.population = []
        task_ids = [task.id for task in tasks]

        for _ in range(self.population_size):
            shuffled = task_ids.copy()
            random.shuffle(shuffled)
            vehicle_assignments = self._assign_tasks_to_vehicles(shuffled, vehicles)
            fitness = self._calculate_fitness(vehicle_assignments, tasks, vehicles)
            self.population.append(Gene(shuffled, vehicle_assignments, fitness))

    def _assign_tasks_to_vehicles(self, task_ids: List[int],
                                   vehicles: List[Vehicle]) -> Dict[int, List[int]]:
        vehicle_assignments: Dict[int, List[int]] = {}
        if not vehicles:
            return vehicle_assignments

        vehicle_index = 0
        for task_id in task_ids:
            if vehicle_index >= len(vehicles):
                vehicle_index = 0
            vehicle = vehicles[vehicle_index]
            vehicle_assignments.setdefault(vehicle.id, []).append(task_id)
            vehicle_index += 1

        return vehicle_assignments

    def _calculate_fitness(
        self,
        vehicle_assignments: Dict[int, List[int]],
        tasks: List[Task],
        vehicles: List[Vehicle],
    ) -> float:
        """
        适应度函数（改进版，B8 修复）：
          fitness = completion_ratio × 1000
                  - load_violation × 500
                  - total_distance × 0.001   （路网成本，辅助优化）

        total_distance：所有分配路程的仓库→任务→仓库往返距离之和（路网真实距离）
        """
        total_tasks = len(tasks)
        if total_tasks == 0:
            return 0.0

        task_dict = {t.id: t for t in tasks}
        vehicle_dict = {v.id: v for v in vehicles}

        assigned_count = sum(len(tids) for tids in vehicle_assignments.values())
        completion_ratio = assigned_count / total_tasks

        # 超载惩罚
        load_violation = 0.0
        for vid, task_ids in vehicle_assignments.items():
            vehicle = vehicle_dict.get(vid)
            if vehicle is None:
                continue
            total_weight = sum(task_dict[tid].weight for tid in task_ids if tid in task_dict)
            if total_weight > vehicle.max_load:
                load_violation += (total_weight - vehicle.max_load) / vehicle.max_load

        # 路网路径成本（有 path_calculator 时才计算）
        total_distance = 0.0
        if self.path_calculator is not None:
            for vid, task_ids in vehicle_assignments.items():
                for tid in task_ids:
                    task = task_dict.get(tid)
                    if task is None:
                        continue
                    try:
                        task_pos = (task.position.x, task.position.y)
                        dist = self.path_calculator.calculate_pair_distance(
                            self.warehouse_pos, task_pos
                        ) * 2  # 仓库→任务→仓库（往返近似）
                        total_distance += dist
                    except Exception:
                        pass  # 路网查找失败时跳过，不影响其他评估

        fitness = (
            completion_ratio * 1000.0
            - load_violation  * 500.0
            - total_distance  * 0.001   # 路程成本权重较小，避免压制完成率目标
        )
        return fitness

    def _compute_total_distance(
        self,
        vehicle_assignments: Dict[int, List[int]],
        tasks: List[Task],
    ) -> float:
        """计算最优解的真实路网总距离，用于填充 Solution.total_distance。"""
        if self.path_calculator is None:
            return 0.0
        task_dict = {t.id: t for t in tasks}
        total = 0.0
        for task_ids in vehicle_assignments.values():
            for tid in task_ids:
                task = task_dict.get(tid)
                if task is None:
                    continue
                try:
                    task_pos = (task.position.x, task.position.y)
                    total += self.path_calculator.calculate_pair_distance(
                        self.warehouse_pos, task_pos
                    ) * 2
                except Exception:
                    pass
        return total

    def select(self) -> List[Gene]:
        self.population.sort(key=lambda gene: gene.fitness, reverse=True)
        return self.population[:self.population_size // 2]

    def crossover(self, parent1: Gene, parent2: Gene,
                  tasks: List[Task], vehicles: List[Vehicle]) -> Gene:
        if random.random() > self.crossover_rate:
            cloned = copy.deepcopy(parent1)
            cloned.vehicle_assignments = self._assign_tasks_to_vehicles(cloned.tasks, vehicles)
            cloned.fitness = self._calculate_fitness(cloned.vehicle_assignments, tasks, vehicles)
            return cloned

        if len(parent1.tasks) <= 1:
            return copy.deepcopy(parent1)

        crossover_point = random.randint(1, len(parent1.tasks) - 1)
        child_tasks = parent1.tasks[:crossover_point]
        remaining = [t for t in parent2.tasks if t not in child_tasks]
        child_tasks.extend(remaining)

        child_assignments = self._assign_tasks_to_vehicles(child_tasks, vehicles)
        fitness = self._calculate_fitness(child_assignments, tasks, vehicles)
        return Gene(child_tasks, child_assignments, fitness)

    def mutate(self, gene: Gene) -> Gene:
        if random.random() > self.mutation_rate:
            return gene
        mutated = copy.deepcopy(gene)
        if len(mutated.tasks) > 1:
            i, j = random.sample(range(len(mutated.tasks)), 2)
            mutated.tasks[i], mutated.tasks[j] = mutated.tasks[j], mutated.tasks[i]
        return mutated

    def evolve(self, tasks: List[Task], vehicles: List[Vehicle]) -> Solution:
        self.initialize_population(tasks, vehicles)

        for _ in range(self.max_generations):
            selected = self.select()
            new_population = selected[:self.population_size // 4]

            while len(new_population) < self.population_size:
                parent1, parent2 = random.sample(selected, 2)
                child = self.crossover(parent1, parent2, tasks, vehicles)
                child = self.mutate(child)
                child.vehicle_assignments = self._assign_tasks_to_vehicles(child.tasks, vehicles)
                child.fitness = self._calculate_fitness(child.vehicle_assignments, tasks, vehicles)
                new_population.append(child)

            self.population = new_population

        best_gene = max(self.population, key=lambda gene: gene.fitness)
        total_distance = self._compute_total_distance(best_gene.vehicle_assignments, tasks)

        return Solution(
            objective_value=best_gene.fitness,
            routes=[],
            vehicle_assignments=best_gene.vehicle_assignments,
            charging_stations_used=[],
            total_distance=total_distance,   # 修复：填充真实路网距离
            total_time=0.0,
        )
