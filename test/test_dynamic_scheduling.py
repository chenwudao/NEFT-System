import pytest
from backend.decision.dynamic_scheduling_module import DynamicSchedulingModule
from backend.data.data_manager import DataManager
from backend.algorithm.algorithm_manager import AlgorithmManager
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

@pytest.fixture
def dynamic_scheduling_module(data_manager, algorithm_manager):
    return DynamicSchedulingModule(data_manager, algorithm_manager)

def test_dynamic_scheduling_module_initialization(dynamic_scheduling_module, data_manager, algorithm_manager):
    """测试动态调度模块初始化"""
    assert dynamic_scheduling_module is not None
    assert dynamic_scheduling_module.data_manager == data_manager
    assert dynamic_scheduling_module.algorithm_manager == algorithm_manager

def test_dynamic_scheduling(dynamic_scheduling_module, data_manager):
    """测试动态调度功能"""
    # 创建测试数据
    vehicle = Vehicle(
        id=1, position=Position(x=0, y=0), battery=100, max_battery=100,
        current_load=0, max_load=100, unit_energy_consumption=0.1
    )
    task = Task(
        id=1, position=Position(x=100, y=100), weight=10, create_time=1000, 
        deadline=2000, priority=1, status=TaskStatus.PENDING
    )
    station = ChargingStation(
        id="cs1", position=Position(x=20, y=20), capacity=5, queue_count=0,
        charging_vehicles=[], load_pressure=0.0, charging_rate=10.0
    )
    
    data_manager.add_vehicle(vehicle)
    data_manager.add_task(task)
    data_manager.add_charging_station(station)
    
    # 测试动态调度
    commands = dynamic_scheduling_module.process_pending_tasks(strategy="shortest_task_first")
    
    assert isinstance(commands, list)
    
    # 验证命令结构
    for command in commands:
        assert "action_type" in command
        assert "vehicle_id" in command
        assert "assigned_tasks" in command or "station_id" in command

    # 验证点 0-1：下发运输命令后，任务应进入进行中，车辆应具备完整路径并进入运输状态。
    if commands and commands[0]["action_type"] == "transport":
        updated_task = data_manager.get_task(task.id)
        updated_vehicle = data_manager.get_vehicle(vehicle.id)
        assert updated_task.status == TaskStatus.IN_PROGRESS
        assert updated_vehicle.status == VehicleStatus.TRANSPORTING
        assert len(updated_vehicle.complete_path) >= 2

def test_dynamic_scheduling_with_low_battery(dynamic_scheduling_module, data_manager):
    """测试低电量车辆的动态调度"""
    # 创建低电量车辆
    vehicle = Vehicle(
        id=1, position=Position(x=0, y=0), battery=10, max_battery=100,  # 低电量
        current_load=0, max_load=100, unit_energy_consumption=0.1
    )
    station = ChargingStation(
        id="cs1", position=Position(x=20, y=20), capacity=5, queue_count=0,
        charging_vehicles=[], load_pressure=0.0, charging_rate=10.0
    )
    
    data_manager.add_vehicle(vehicle)
    data_manager.add_charging_station(station)
    
    # 测试动态调度（无待处理任务）
    commands = dynamic_scheduling_module.process_pending_tasks(strategy="shortest_task_first")
    
    assert isinstance(commands, list)
    # 由于没有待处理任务，应该返回空列表
    assert len(commands) == 0

def test_dynamic_scheduling_with_no_tasks(dynamic_scheduling_module, data_manager):
    """测试无任务时的动态调度"""
    # 创建车辆但无任务
    vehicle = Vehicle(
        id=1, position=Position(x=0, y=0), battery=100, max_battery=100,
        current_load=0, max_load=100, unit_energy_consumption=0.1
    )
    
    data_manager.add_vehicle(vehicle)
    
    # 测试动态调度
    commands = dynamic_scheduling_module.process_pending_tasks(strategy="shortest_task_first")
    
    assert isinstance(commands, list)
    assert len(commands) == 0  # 无任务时应该返回空列表
