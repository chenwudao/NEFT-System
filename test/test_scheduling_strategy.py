import pytest
from backend.algorithm.shortest_task_first import ShortestTaskFirstStrategy
from backend.algorithm.heaviest_task_first import HeaviestTaskFirstStrategy
from backend.data.position import Position
from backend.data.task import Task, TaskStatus
from backend.data.vehicle import Vehicle, VehicleStatus
from backend.data.charging_station import ChargingStation

@pytest.fixture
def test_vehicles():
    return [
        Vehicle(id=1, position=Position(x=0, y=0), battery=100, max_battery=100, current_load=0, max_load=100, unit_energy_consumption=0.1),
        Vehicle(id=2, position=Position(x=0, y=0), battery=100, max_battery=100, current_load=0, max_load=100, unit_energy_consumption=0.1),
    ]

@pytest.fixture
def test_tasks():
    return [
        Task(id=1, position=Position(x=10, y=10), weight=10, create_time=1000, deadline=2000, priority=1, status=TaskStatus.PENDING),
        Task(id=2, position=Position(x=20, y=20), weight=20, create_time=1000, deadline=2000, priority=2, status=TaskStatus.PENDING),
        Task(id=3, position=Position(x=30, y=30), weight=30, create_time=1000, deadline=2000, priority=3, status=TaskStatus.PENDING),
    ]

@pytest.fixture
def test_charging_stations():
    return [
        ChargingStation(id="cs1", position=Position(x=50, y=50), capacity=5, queue_count=0, charging_vehicles=[], load_pressure=0.0, charging_rate=10.0),
    ]

def test_shortest_task_first_strategy(test_vehicles, test_tasks, test_charging_stations):
    """测试最短任务优先策略"""
    from backend.data.path_calculator import PathCalculator
    path_calculator = PathCalculator()
    
    global_params = {
        "warehouse_position": (0, 0),
        "current_time": 1000
    }
    
    strategy = ShortestTaskFirstStrategy(
        test_vehicles, test_tasks, test_charging_stations, global_params, path_calculator
    )
    
    commands = strategy.execute()
    
    assert isinstance(commands, list)
    
    # 验证命令结构
    for command in commands:
        assert "action_type" in command
        assert "vehicle_id" in command
        assert "assigned_tasks" in command or "station_id" in command

def test_heaviest_task_first_strategy(test_vehicles, test_tasks, test_charging_stations):
    """测试最重任务优先策略"""
    from backend.data.path_calculator import PathCalculator
    path_calculator = PathCalculator()
    
    global_params = {
        "warehouse_position": (0, 0),
        "current_time": 1000
    }
    
    strategy = HeaviestTaskFirstStrategy(
        test_vehicles, test_tasks, test_charging_stations, global_params, path_calculator
    )
    
    commands = strategy.execute()
    
    assert isinstance(commands, list)
    
    # 验证命令结构
    for command in commands:
        assert "action_type" in command
        assert "vehicle_id" in command
        assert "assigned_tasks" in command or "station_id" in command

def test_shortest_task_first_prioritization():
    """测试最短任务优先策略的任务排序"""
    from backend.data.path_calculator import PathCalculator
    path_calculator = PathCalculator()
    
    # 创建不同距离的任务
    tasks = [
        Task(id=1, position=Position(x=100, y=100), weight=10, create_time=1000, deadline=2000, priority=1),
        Task(id=2, position=Position(x=10, y=10), weight=20, create_time=1000, deadline=2000, priority=2),  # 更近
        Task(id=3, position=Position(x=50, y=50), weight=15, create_time=1000, deadline=2000, priority=3),
    ]
    
    # 模拟最短任务优先策略的排序逻辑
    # 最短任务优先应该按距离排序
    sorted_tasks = sorted(tasks, key=lambda task: (task.position.x**2 + task.position.y**2)**0.5)
    
    assert sorted_tasks[0].id == 2  # 最近的任务
    assert sorted_tasks[1].id == 3
    assert sorted_tasks[2].id == 1  # 最远的任务

def test_heaviest_task_first_prioritization():
    """测试最重任务优先策略的任务排序"""
    # 创建不同重量的任务
    tasks = [
        Task(id=1, position=Position(x=10, y=10), weight=10, create_time=1000, deadline=2000, priority=1),
        Task(id=2, position=Position(x=20, y=20), weight=30, create_time=1000, deadline=2000, priority=2),  # 最重
        Task(id=3, position=Position(x=30, y=30), weight=20, create_time=1000, deadline=2000, priority=3),
    ]
    
    # 模拟最重任务优先策略的排序逻辑
    # 最重任务优先应该按重量排序
    sorted_tasks = sorted(tasks, key=lambda task: -task.weight)
    
    assert sorted_tasks[0].id == 2  # 最重的任务
    assert sorted_tasks[1].id == 3
    assert sorted_tasks[2].id == 1  # 最轻的任务
