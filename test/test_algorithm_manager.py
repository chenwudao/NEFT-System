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
    # 聚类算法已删除
    assert hasattr(algorithm_manager, 'strategy_classes')
    # 验证精简后的策略（3个）
    assert len(algorithm_manager.strategy_classes) == 3
    assert 'shortest_task_first' in algorithm_manager.strategy_classes
    assert 'priority_based' in algorithm_manager.strategy_classes
    assert 'composite_score' in algorithm_manager.strategy_classes


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
    
    # 测试3个精简后的策略
    for strategy in ['shortest_task_first', 'priority_based', 'composite_score']:
        commands = algorithm_manager.schedule_realtime(
            strategy, idle_vehicles, pending_tasks, 
            charging_stations, global_params
        )
        assert isinstance(commands, list)
    
    # 测试无效策略回退到默认策略
    commands_invalid = algorithm_manager.schedule_realtime(
        "invalid_strategy", idle_vehicles, pending_tasks, 
        charging_stations, global_params
    )
    assert isinstance(commands_invalid, list)


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


def test_solve_mip(algorithm_manager, data_manager):
    """测试MIP求解器"""
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
    
    # 测试MIP求解（如果没有Gurobi会回退）
    tasks = data_manager.get_tasks()
    vehicles = data_manager.get_vehicles()
    charging_stations = data_manager.get_charging_stations()
    warehouse_position = (0, 0)
    
    solution = algorithm_manager.solve_mip(
        tasks, vehicles, charging_stations, warehouse_position
    )
    
    # MIP可能返回None（如果没有求解器）或Solution
    assert solution is None or hasattr(solution, 'vehicle_assignments')


def test_get_available_strategies(algorithm_manager):
    """测试获取可用策略列表"""
    strategies = algorithm_manager.get_available_strategies()
    assert isinstance(strategies, list)
    assert len(strategies) == 3
    assert 'shortest_task_first' in strategies
    assert 'priority_based' in strategies
    assert 'composite_score' in strategies
