import pytest
from backend.data.data_manager import DataManager
from backend.data.position import Position
from backend.data.task import Task
from backend.data.vehicle import Vehicle
from backend.data.charging_station import ChargingStation
from backend.data.path_calculator import PathCalculator

@pytest.fixture
def data_manager():
    return DataManager()

@pytest.fixture
def path_calculator(data_manager):
    return PathCalculator()

def test_calculate_distance_from_positions(path_calculator):
    positions = [
        Position(x=0.0, y=0.0),
        Position(x=3.0, y=4.0),
        Position(x=6.0, y=8.0)
    ]
    
    distance = path_calculator.calculate_distance_from_positions(positions)
    assert distance == 10.0

def test_calculate_energy_consumption(path_calculator):
    vehicle = Vehicle(
        id=1,
        position=Position(x=0.0, y=0.0),
        battery=100.0,
        max_battery=100.0,
        current_load=50.0,
        max_load=100.0,
        unit_energy_consumption=0.1
    )
    
    positions = [
        Position(x=0.0, y=0.0),
        Position(x=10.0, y=0.0)
    ]
    
    energy = path_calculator.calculate_energy_consumption_from_positions(vehicle, positions)
    assert energy > 0
    assert energy < vehicle.battery

def test_find_nearest_charging_station(path_calculator, data_manager):
    vehicle = Vehicle(
        id=1,
        position=Position(x=100.0, y=100.0),
        battery=100.0,
        max_battery=100.0,
        current_load=0.0,
        max_load=100.0,
        unit_energy_consumption=0.1
    )
    
    station1 = ChargingStation(
        id="cs1",
        position=Position(x=150.0, y=150.0),
        capacity=5,
        queue_count=0,
        charging_vehicles=[],
        load_pressure=0.0,
        charging_rate=10.0
    )
    
    station2 = ChargingStation(
        id="cs2",
        position=Position(x=300.0, y=300.0),
        capacity=5,
        queue_count=0,
        charging_vehicles=[],
        load_pressure=0.0,
        charging_rate=10.0
    )
    
    data_manager.add_charging_station(station1)
    data_manager.add_charging_station(station2)
    
    nearest_station_id = path_calculator.find_nearest_charging_station(vehicle, [station1, station2])
    assert nearest_station_id == "cs1"

def test_calculate_path_distance(path_calculator):
    start_pos = Position(x=0.0, y=0.0)
    end_pos = Position(x=3.0, y=4.0)
    
    distance = path_calculator.calculate_distance([(start_pos.x, start_pos.y), (end_pos.x, end_pos.y)])
    assert distance == 5.0


def test_calculate_complete_path(path_calculator):
    """测试完整路径计算：仓库 → 任务点 → 仓库"""
    warehouse_pos = Position(x=0.0, y=0.0)
    task_pos = Position(x=3.0, y=4.0)
    
    complete_path, total_distance = path_calculator.calculate_complete_path(warehouse_pos, task_pos)
    
    # 验证路径长度
    assert len(complete_path) >= 3  # 至少包含仓库 → 任务点 → 仓库
    
    # 验证总距离（仓库到任务点是5，返回也是5，总距离应该是10）
    assert total_distance == 10.0
    
    # 验证路径起点和终点都是仓库
    assert complete_path[0] == (0.0, 0.0)
    assert complete_path[-1] == (0.0, 0.0)


def test_calculate_energy_consumption_for_complete_path(path_calculator):
    """测试基于完整路径的电量消耗计算"""
    vehicle = Vehicle(
        id=1,
        position=Position(x=0.0, y=0.0),
        battery=100.0,
        max_battery=100.0,
        current_load=50.0,
        max_load=100.0,
        unit_energy_consumption=0.1
    )
    
    # 完整路径：(0,0) → (3,4) → (0,0)
    complete_path = [(0.0, 0.0), (3.0, 4.0), (0.0, 0.0)]
    
    total_energy, is_feasible = path_calculator.calculate_energy_consumption_for_complete_path(vehicle, complete_path)
    
    # 验证电量消耗计算正确
    assert total_energy > 0
    assert total_energy == 10.0 * 0.1  # 10单位距离，每单位0.1电量
    
    # 验证电量是否充足
    assert is_feasible == True


def test_calculate_task_completion_time(path_calculator):
    """测试任务完成时间计算"""
    # 完整路径：(0,0) → (3,4) → (0,0)
    complete_path = [(0.0, 0.0), (3.0, 4.0), (0.0, 0.0)]
    
    completion_time = path_calculator.calculate_task_completion_time(complete_path)
    
    # 验证完成时间计算正确
    # 距离10，速度1，时间10秒，加上30秒卸载时间，总时间40秒
    assert completion_time == 40.0


def test_calculate_task_score(path_calculator):
    """测试任务得分计算"""
    task = Task(
        id=1,
        position=Position(x=3.0, y=4.0),
        weight=10.0,
        create_time=1000,
        deadline=2000,
        priority=1
    )
    
    # 测试按时完成的情况
    completion_time = 1500  # 1500 < 2000，按时完成
    complete_path_distance = 10.0
    score = path_calculator.calculate_task_score(task, completion_time, complete_path_distance)
    
    # 按时完成基础分100，路径长度 bonus (1000/10)*10 = 1000
    assert score > 100.0
    
    # 测试超时完成的情况
    completion_time = 2500  # 2500 > 2000，超时完成
    score = path_calculator.calculate_task_score(task, completion_time, complete_path_distance)
    
    # 超时完成基础分-50，路径长度 bonus 仍然存在
    assert score > -50.0
