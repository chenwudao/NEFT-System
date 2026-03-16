import pytest
from backend.algorithm.algorithm_manager import AlgorithmManager
from backend.data.data_manager import DataManager
from backend.data.position import Position
from backend.data.task import Task, TaskStatus
from backend.data.vehicle import Vehicle, VehicleStatus
from backend.data.charging_station import ChargingStation

@pytest.fixture
def data_manager():
    dm = DataManager()
    dm.set_warehouse_position(Position(x=0, y=0))
    return dm

@pytest.fixture
def algorithm_manager(data_manager):
    return AlgorithmManager(data_manager.path_calculator)

def test_algorithm_manager_initialization(algorithm_manager):
    """测试算法管理器初始化"""
    assert algorithm_manager is not None
    assert algorithm_manager.path_calculator is not None
    assert hasattr(algorithm_manager, 'mip_solver')
    assert hasattr(algorithm_manager, 'genetic_algorithm')
    assert hasattr(algorithm_manager, 'clustering_algorithm')

def test_cluster_tasks(algorithm_manager):
    """测试任务聚类功能"""
    # 创建测试任务
    tasks = [
        Task(id=1, position=Position(x=10, y=10), weight=10, create_time=1000, deadline=2000, priority=1),
        Task(id=2, position=Position(x=12, y=12), weight=15, create_time=1000, deadline=2000, priority=2),
        Task(id=3, position=Position(x=50, y=50), weight=20, create_time=1000, deadline=2000, priority=3),
        Task(id=4, position=Position(x=52, y=52), weight=25, create_time=1000, deadline=2000, priority=4),
    ]
    
    # 测试Kmeans聚类
    clusters = algorithm_manager.cluster_tasks(tasks, method="kmeans")
    assert isinstance(clusters, list)
    assert len(clusters) > 0
    
    # 测试区域划分聚类
    region_clusters = algorithm_manager.cluster_tasks(tasks, method="region")
    assert isinstance(region_clusters, list)
    assert len(region_clusters) > 0
    
    # 测试默认聚类方法
    default_clusters = algorithm_manager.cluster_tasks(tasks, method="unknown")
    assert isinstance(default_clusters, list)
    assert len(default_clusters) == len(tasks)

def test_schedule_realtime(algorithm_manager, data_manager):
    """测试实时调度功能"""
    # 创建测试数据
    vehicle = Vehicle(
        id=1, position=Position(x=0, y=0), battery=100, max_battery=100,
        current_load=0, max_load=100, unit_energy_consumption=0.1
    )
    task = Task(
        id=1, position=Position(x=10, y=10), weight=10, create_time=1000, 
        deadline=2000, priority=1, status=TaskStatus.PENDING
    )
    station = ChargingStation(
        id="cs1", position=Position(x=20, y=20), capacity=5, queue_count=0,
        charging_vehicles=[], load_pressure=0.0, charging_rate=10.0
    )
    
    data_manager.add_vehicle(vehicle)
    data_manager.add_task(task)
    data_manager.add_charging_station(station)
    
    # 测试实时调度
    idle_vehicles = data_manager.get_idle_vehicles()
    pending_tasks = data_manager.get_pending_tasks()
    charging_stations = data_manager.get_charging_stations()
    
    global_params = {
        "warehouse_position": (0, 0),
        "current_time": 1000
    }
    
    commands = algorithm_manager.schedule_realtime(
        "shortest_task_first", idle_vehicles, pending_tasks, 
        charging_stations, global_params
    )
    
    assert isinstance(commands, list)
    
    # 测试其他策略
    commands_genetic = algorithm_manager.schedule_realtime(
        "genetic", idle_vehicles, pending_tasks, 
        charging_stations, global_params
    )
    assert isinstance(commands_genetic, list)

def test_solve_genetic(algorithm_manager, data_manager):
    """测试遗传算法求解"""
    # 创建测试数据
    vehicle = Vehicle(
        id=1, position=Position(x=0, y=0), battery=100, max_battery=100,
        current_load=0, max_load=100, unit_energy_consumption=0.1
    )
    task = Task(
        id=1, position=Position(x=10, y=10), weight=10, create_time=1000, 
        deadline=2000, priority=1
    )
    
    data_manager.add_vehicle(vehicle)
    data_manager.add_task(task)
    
    # 测试遗传算法
    tasks = data_manager.get_tasks()
    vehicles = data_manager.get_vehicles()
    charging_stations = data_manager.get_charging_stations()
    warehouse_position = (0, 0)
    
    solution = algorithm_manager.solve_genetic(
        tasks, vehicles, charging_stations, warehouse_position
    )
    
    assert solution is not None
