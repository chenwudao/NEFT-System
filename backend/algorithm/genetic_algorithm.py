from typing import List, Dict
import random
import copy
from backend.data.task import Task
from backend.data.vehicle import Vehicle
from backend.data.charging_station import ChargingStation
from .solution import Solution

class Gene:
    def __init__(self, tasks: List[int], vehicle_assignments: Dict[int, List[int]], fitness: float = 0.0):
        self.tasks = tasks
        self.vehicle_assignments = vehicle_assignments
        self.fitness = fitness

class GeneticAlgorithm:
    def __init__(self, population_size: int = 100, max_generations: int = 500,
                 mutation_rate: float = 0.1, crossover_rate: float = 0.8):
        self.population_size = population_size
        self.max_generations = max_generations
        self.mutation_rate = mutation_rate
        self.crossover_rate = crossover_rate
        self.population: List[Gene] = []

    def initialize_population(self, tasks: List[Task], vehicles: List[Vehicle]):
        self.population = []
        task_ids = [task.id for task in tasks]

        for _ in range(self.population_size):
            random.shuffle(task_ids)
            vehicle_assignments = self._assign_tasks_to_vehicles(task_ids.copy(), vehicles)
            fitness = self._calculate_fitness(vehicle_assignments, tasks, vehicles)
            gene = Gene(task_ids.copy(), vehicle_assignments, fitness)
            self.population.append(gene)

    def _assign_tasks_to_vehicles(self, task_ids: List[int], vehicles: List[Vehicle]) -> Dict[int, List[int]]:
        vehicle_assignments = {}
        
        # 处理空车辆列表的情况
        if not vehicles:
            return vehicle_assignments
            
        vehicle_index = 0

        for task_id in task_ids:
            if vehicle_index >= len(vehicles):
                vehicle_index = 0

            vehicle = vehicles[vehicle_index]
            if vehicle.id not in vehicle_assignments:
                vehicle_assignments[vehicle.id] = []

            vehicle_assignments[vehicle.id].append(task_id)
            vehicle_index += 1

        return vehicle_assignments

    def _calculate_fitness(self, vehicle_assignments: Dict[int, List[int]], 
                         tasks: List[Task], vehicles: List[Vehicle]) -> float:
        total_tasks = len(tasks)
        assigned_tasks = sum(len(tasks) for tasks in vehicle_assignments.values())
        
        if total_tasks == 0:
            return 0.0

        fitness = assigned_tasks / total_tasks

        for vehicle_id, task_ids in vehicle_assignments.items():
            vehicle = next((v for v in vehicles if v.id == vehicle_id), None)
            if vehicle:
                total_weight = sum(next((t.weight for t in tasks if t.id == task_id), 0) 
                                 for task_id in task_ids)
                if total_weight > vehicle.max_load:
                    fitness *= 0.5

        return fitness

    def select(self) -> List[Gene]:
        self.population.sort(key=lambda gene: gene.fitness, reverse=True)
        return self.population[:self.population_size // 2]

    def crossover(self, parent1: Gene, parent2: Gene) -> Gene:
        if random.random() > self.crossover_rate:
            return copy.deepcopy(parent1)

        # 处理任务数量为1的情况
        if len(parent1.tasks) <= 1:
            return copy.deepcopy(parent1)

        crossover_point = random.randint(1, len(parent1.tasks) - 1)

        child_tasks = parent1.tasks[:crossover_point]
        remaining_tasks = [task for task in parent2.tasks if task not in child_tasks]
        child_tasks.extend(remaining_tasks)

        # 处理空车辆列表的情况
        child_assignments = self._assign_tasks_to_vehicles(child_tasks, [])
        fitness = self._calculate_fitness(child_assignments, [], [])

        return Gene(child_tasks, child_assignments, fitness)

    def mutate(self, gene: Gene) -> Gene:
        if random.random() > self.mutation_rate:
            return gene

        mutated_gene = copy.deepcopy(gene)

        if len(mutated_gene.tasks) > 1:
            i, j = random.sample(range(len(mutated_gene.tasks)), 2)
            mutated_gene.tasks[i], mutated_gene.tasks[j] = mutated_gene.tasks[j], mutated_gene.tasks[i]

        return mutated_gene

    def evolve(self, tasks: List[Task], vehicles: List[Vehicle]) -> Solution:
        self.initialize_population(tasks, vehicles)

        for generation in range(self.max_generations):
            selected = self.select()

            new_population = selected[:self.population_size // 4]

            while len(new_population) < self.population_size:
                parent1, parent2 = random.sample(selected, 2)
                child = self.crossover(parent1, parent2)
                child = self.mutate(child)
                new_population.append(child)

            self.population = new_population

        best_gene = max(self.population, key=lambda gene: gene.fitness)

        return Solution(
            objective_value=best_gene.fitness,
            routes=[],
            vehicle_assignments=best_gene.vehicle_assignments,
            charging_stations_used=[],
            total_distance=0.0,
            total_time=0.0
        )
