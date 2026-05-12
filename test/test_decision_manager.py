import pytest
from backend.data.data_manager import DataManager
from backend.data.position import Position
from backend.data.task import Task, TaskStatus
from backend.data.vehicle import Vehicle, VehicleStatus
from backend.data.charging_station import ChargingStation
from backend.data.path_calculator import PathCalculator
from backend.algorithm.algorithm_manager import AlgorithmManager
from backend.decision.decision_manager import DecisionManager

@pytest.fixture
def data_manager():
    dm = DataManager()
    dm.set_warehouse_position(Position(x=0, y=0))
    return dm

@pytest.fixture
def algorithm_manager(data_manager):
    return AlgorithmManager(data_manager.path_calculator)

@pytest.fixture
def decision_manager(data_manager, algorithm_manager):
    return DecisionManager(data_manager, algorithm_manager)

def test_get_system_status(decision_manager, data_manager):
    task = Task(
        id=1,
        position=Position(x=100.0, y=200.0),
        weight=50.0,
        create_time=1678888888,
        deadline=1678892488,
        priority=2,
        status=TaskStatus.PENDING
    )
    
    vehicle = Vehicle(
        id=1,
        position=Position(x=100.0, y=100.0),
        battery=80.0,
        max_battery=100.0,
        current_load=0.0,
        max_load=100.0,
        unit_energy_consumption=0.1,
        status=VehicleStatus.IDLE
    )
    
    station = ChargingStation(
        id="cs1",
        position=Position(x=200.0, y=200.0),
        capacity=5,
        queue_count=0,
        charging_vehicles=[],
        load_pressure=0.0,
        charging_rate=10.0
    )
    
    data_manager.add_task(task)
    data_manager.add_vehicle(vehicle)
    data_manager.add_charging_station(station)
    
    status = decision_manager.get_system_status()
    assert status is not None
    assert "total_tasks" in status
    assert "total_vehicles" in status
    assert "total_charging_stations" in status
    assert "current_strategy_reason" in status
    assert status["total_tasks"] == 1
    assert status["total_vehicles"] == 1
    assert status["total_charging_stations"] == 1

def test_evaluate_system_performance(decision_manager, data_manager):
    task1 = Task(
        id=1,
        position=Position(x=100.0, y=200.0),
        weight=50.0,
        create_time=1678888888,
        deadline=1678892488,
        priority=2,
        status=TaskStatus.COMPLETED,
        start_time=1678888888,
        complete_time=1678889000
    )
    
    task2 = Task(
        id=2,
        position=Position(x=150.0, y=250.0),
        weight=30.0,
        create_time=1678888889,
        deadline=1678892489,
        priority=1,
        status=TaskStatus.PENDING
    )
    
    vehicle = Vehicle(
        id=1,
        position=Position(x=100.0, y=100.0),
        battery=80.0,
        max_battery=100.0,
        current_load=0.0,
        max_load=100.0,
        unit_energy_consumption=0.1
    )
    
    data_manager.add_task(task1)
    data_manager.add_task(task2)
    data_manager.add_vehicle(vehicle)
    
    performance = decision_manager.evaluate_system_performance()
    assert performance is not None
    assert "completion_rate" in performance
    assert "avg_completion_time" in performance
    assert "total_distance" in performance
    assert "total_score" in performance
    assert performance["completion_rate"] == 0.5

def test_dynamic_scheduling(decision_manager, data_manager):
    task = Task(
        id=1,
        position=Position(x=100.0, y=200.0),
        weight=50.0,
        create_time=1678888888,
        deadline=1678892488,
        priority=2,
        status=TaskStatus.PENDING
    )
    
    vehicle = Vehicle(
        id=1,
        position=Position(x=100.0, y=100.0),
        battery=80.0,
        max_battery=100.0,
        current_load=0.0,
        max_load=100.0,
        unit_energy_consumption=0.1,
        status=VehicleStatus.IDLE
    )
    
    station = ChargingStation(
        id="cs1",
        position=Position(x=200.0, y=200.0),
        capacity=5,
        queue_count=0,
        charging_vehicles=[],
        load_pressure=0.0,
        charging_rate=10.0
    )
    
    data_manager.add_task(task)
    data_manager.add_vehicle(vehicle)
    data_manager.add_charging_station(station)
    
    commands = decision_manager.dynamic_scheduling(strategy="shortest_task_first")
    assert commands is not None
    assert isinstance(commands, list)

def test_manage_battery(decision_manager, data_manager):
    vehicle = Vehicle(
        id=1,
        position=Position(x=100.0, y=100.0),
        battery=10.0,
        max_battery=100.0,
        current_load=0.0,
        max_load=100.0,
        unit_energy_consumption=0.1,
        status=VehicleStatus.IDLE
    )
    
    station = ChargingStation(
        id="cs1",
        position=Position(x=200.0, y=200.0),
        capacity=5,
        queue_count=0,
        charging_vehicles=[],
        load_pressure=0.0,
        charging_rate=10.0
    )
    
    data_manager.add_vehicle(vehicle)
    data_manager.add_charging_station(station)
    
    command = decision_manager.manage_battery(vehicle)
    assert command is not None
    assert command["action_type"] == "charge"
    assert command["vehicle_id"] == 1


def test_evaluate_system_performance_uses_task_score(decision_manager, data_manager):
    completed_task = Task(
        id=11,
        position=Position(x=10.0, y=10.0),
        weight=20.0,
        create_time=1000,
        deadline=2000,
        priority=1,
        status=TaskStatus.COMPLETED,
        start_time=1200,
        complete_time=1800,
        score=123.45,
        complete_path_distance=50.0
    )
    pending_task = Task(
        id=12,
        position=Position(x=20.0, y=20.0),
        weight=10.0,
        create_time=1000,
        deadline=2500,
        priority=1,
        status=TaskStatus.PENDING
    )

    data_manager.add_task(completed_task)
    data_manager.add_task(pending_task)

    metrics = decision_manager.evaluate_system_performance()
    assert metrics["completion_rate"] == 0.5
    assert metrics["total_distance"] == 50.0
    assert metrics["total_score"] == pytest.approx(123.45)
