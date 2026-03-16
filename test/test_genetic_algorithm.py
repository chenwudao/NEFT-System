import pytest
from backend.algorithm.genetic_algorithm import GeneticAlgorithm, Gene
from backend.data.position import Position
from backend.data.task import Task
from backend.data.vehicle import Vehicle

@pytest.fixture
def genetic_algorithm():
    return GeneticAlgorithm(population_size=10, max_generations=10)

@pytest.fixture
def test_tasks():
    return [
        Task(id=1, position=Position(x=10, y=10), weight=10, create_time=1000, deadline=2000, priority=1),
        Task(id=2, position=Position(x=20, y=20), weight=15, create_time=1000, deadline=2000, priority=2),
        Task(id=3, position=Position(x=30, y=30), weight=20, create_time=1000, deadline=2000, priority=3),
        Task(id=4, position=Position(x=40, y=40), weight=25, create_time=1000, deadline=2000, priority=4),
    ]

@pytest.fixture
def test_vehicles():
    return [
        Vehicle(id=1, position=Position(x=0, y=0), battery=100, max_battery=100, current_load=0, max_load=100, unit_energy_consumption=0.1),
        Vehicle(id=2, position=Position(x=0, y=0), battery=100, max_battery=100, current_load=0, max_load=100, unit_energy_consumption=0.1),
    ]

def test_genetic_algorithm_initialization(genetic_algorithm):
    """测试遗传算法初始化"""
    assert genetic_algorithm is not None
    assert genetic_algorithm.population_size == 10
    assert genetic_algorithm.max_generations == 10
    assert genetic_algorithm.mutation_rate == 0.1
    assert genetic_algorithm.crossover_rate == 0.8
    assert len(genetic_algorithm.population) == 0

def test_initialize_population(genetic_algorithm, test_tasks, test_vehicles):
    """测试种群初始化"""
    genetic_algorithm.initialize_population(test_tasks, test_vehicles)
    
    assert len(genetic_algorithm.population) == 10
    
    for gene in genetic_algorithm.population:
        assert isinstance(gene, Gene)
        assert len(gene.tasks) == len(test_tasks)
        assert len(gene.vehicle_assignments) > 0
        assert gene.fitness >= 0

def test_assign_tasks_to_vehicles(genetic_algorithm, test_tasks, test_vehicles):
    """测试任务分配到车辆"""
    task_ids = [task.id for task in test_tasks]
    vehicle_assignments = genetic_algorithm._assign_tasks_to_vehicles(task_ids.copy(), test_vehicles)
    
    assert isinstance(vehicle_assignments, dict)
    assert len(vehicle_assignments) <= len(test_vehicles)
    
    # 验证所有任务都被分配
    assigned_tasks = []
    for vehicle_id, tasks in vehicle_assignments.items():
        assigned_tasks.extend(tasks)
    assert len(assigned_tasks) == len(test_tasks)
    assert set(assigned_tasks) == set(task_ids)

def test_calculate_fitness(genetic_algorithm, test_tasks, test_vehicles):
    """测试适应度计算"""
    task_ids = [task.id for task in test_tasks]
    vehicle_assignments = genetic_algorithm._assign_tasks_to_vehicles(task_ids.copy(), test_vehicles)
    
    fitness = genetic_algorithm._calculate_fitness(vehicle_assignments, test_tasks, test_vehicles)
    
    assert fitness >= 0

def test_evolve(genetic_algorithm, test_tasks, test_vehicles):
    """测试进化过程"""
    solution = genetic_algorithm.evolve(test_tasks, test_vehicles)
    
    assert solution is not None
    assert hasattr(solution, 'vehicle_assignments')
    assert hasattr(solution, 'total_distance')
    assert hasattr(solution, 'objective_value')
    assert solution.total_distance >= 0
    assert solution.objective_value >= 0
