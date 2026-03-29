import pytest
from backend.data.data_manager import DataManager
from backend.data.position import Position
from backend.data.task import Task, TaskStatus
from backend.data.vehicle import Vehicle, VehicleStatus
from backend.data.charging_station import ChargingStation

@pytest.fixture
def data_manager():
    return DataManager()

def test_add_task(data_manager):
    task = Task(
        id=1,
        position=Position(x=100.0, y=200.0),
        weight=50.0,
        create_time=1678888888,
        deadline=1678892488,
        priority=2
    )
    data_manager.add_task(task)
    
    retrieved_task = data_manager.get_task(1)
    assert retrieved_task is not None
    assert retrieved_task.id == 1
    assert retrieved_task.weight == 50.0

def test_get_tasks(data_manager):
    task1 = Task(
        id=1,
        position=Position(x=100.0, y=200.0),
        weight=50.0,
        create_time=1678888888,
        deadline=1678892488,
        priority=2
    )
    task2 = Task(
        id=2,
        position=Position(x=150.0, y=250.0),
        weight=30.0,
        create_time=1678888889,
        deadline=1678892489,
        priority=1
    )
    data_manager.add_task(task1)
    data_manager.add_task(task2)
    
    tasks = data_manager.get_tasks()
    assert len(tasks) == 2

def test_get_pending_tasks(data_manager):
    task1 = Task(
        id=1,
        position=Position(x=100.0, y=200.0),
        weight=50.0,
        create_time=1678888888,
        deadline=1678892488,
        priority=2,
        status=TaskStatus.PENDING
    )
    task2 = Task(
        id=2,
        position=Position(x=150.0, y=250.0),
        weight=30.0,
        create_time=1678888889,
        deadline=1678892489,
        priority=1,
        status=TaskStatus.COMPLETED
    )
    data_manager.add_task(task1)
    data_manager.add_task(task2)
    
    pending_tasks = data_manager.get_pending_tasks()
    assert len(pending_tasks) == 1
    assert pending_tasks[0].id == 1

def test_add_vehicle(data_manager):
    vehicle = Vehicle(
        id=1,
        position=Position(x=100.0, y=100.0),
        battery=80.0,
        max_battery=100.0,
        current_load=0.0,
        max_load=100.0,
        unit_energy_consumption=0.1
    )
    data_manager.add_vehicle(vehicle)
    
    retrieved_vehicle = data_manager.get_vehicle(1)
    assert retrieved_vehicle is not None
    assert retrieved_vehicle.id == 1
    assert retrieved_vehicle.battery == 80.0

def test_get_vehicles(data_manager):
    vehicle1 = Vehicle(
        id=1,
        position=Position(x=100.0, y=100.0),
        battery=80.0,
        max_battery=100.0,
        current_load=0.0,
        max_load=100.0,
        unit_energy_consumption=0.1
    )
    vehicle2 = Vehicle(
        id=2,
        position=Position(x=150.0, y=150.0),
        battery=90.0,
        max_battery=100.0,
        current_load=0.0,
        max_load=100.0,
        unit_energy_consumption=0.1
    )
    data_manager.add_vehicle(vehicle1)
    data_manager.add_vehicle(vehicle2)
    
    vehicles = data_manager.get_vehicles()
    assert len(vehicles) == 2

def test_get_idle_vehicles(data_manager):
    vehicle1 = Vehicle(
        id=1,
        position=Position(x=100.0, y=100.0),
        battery=80.0,
        max_battery=100.0,
        current_load=0.0,
        max_load=100.0,
        unit_energy_consumption=0.1,
        status=VehicleStatus.IDLE
    )
    vehicle2 = Vehicle(
        id=2,
        position=Position(x=150.0, y=150.0),
        battery=90.0,
        max_battery=100.0,
        current_load=0.0,
        max_load=100.0,
        unit_energy_consumption=0.1,
        status=VehicleStatus.TRANSPORTING
    )
    data_manager.add_vehicle(vehicle1)
    data_manager.add_vehicle(vehicle2)
    
    idle_vehicles = data_manager.get_idle_vehicles()
    assert len(idle_vehicles) == 1
    assert idle_vehicles[0].id == 1

def test_charging_vehicle_can_return_to_idle(data_manager):
    vehicle = Vehicle(
        id=1,
        position=Position(x=100.0, y=100.0),
        battery=20.0,
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

    data_manager.add_vehicle_to_charging_station(vehicle_id=1, station_id="cs1")
    assert data_manager.get_vehicle(1).status == VehicleStatus.CHARGING
    assert data_manager.get_vehicle(1).charging_station_id == "cs1"

    data_manager.remove_vehicle_from_charging_station(vehicle_id=1, station_id="cs1")
    assert data_manager.get_vehicle(1).status == VehicleStatus.IDLE
    assert data_manager.get_vehicle(1).charging_station_id is None

def test_add_charging_station(data_manager):
    station = ChargingStation(
        id="cs1",
        position=Position(x=200.0, y=200.0),
        capacity=5,
        queue_count=0,
        charging_vehicles=[],
        load_pressure=0.0,
        charging_rate=10.0
    )
    data_manager.add_charging_station(station)
    
    retrieved_station = data_manager.get_charging_station("cs1")
    assert retrieved_station is not None
    assert retrieved_station.id == "cs1"
    assert retrieved_station.capacity == 5

def test_get_charging_stations(data_manager):
    station1 = ChargingStation(
        id="cs1",
        position=Position(x=200.0, y=200.0),
        capacity=5,
        queue_count=0,
        charging_vehicles=[],
        load_pressure=0.0,
        charging_rate=10.0
    )
    station2 = ChargingStation(
        id="cs2",
        position=Position(x=250.0, y=250.0),
        capacity=3,
        queue_count=0,
        charging_vehicles=[],
        load_pressure=0.0,
        charging_rate=15.0
    )
    data_manager.add_charging_station(station1)
    data_manager.add_charging_station(station2)
    
    stations = data_manager.get_charging_stations()
    assert len(stations) == 2

def test_set_warehouse_position(data_manager):
    warehouse_pos = Position(x=0.0, y=0.0)
    data_manager.set_warehouse_position(warehouse_pos)
    
    assert data_manager.warehouse_position.x == 0.0
    assert data_manager.warehouse_position.y == 0.0

def test_get_system_state(data_manager):
    task = Task(
        id=1,
        position=Position(x=100.0, y=200.0),
        weight=50.0,
        create_time=1678888888,
        deadline=1678892488,
        priority=2
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
    station = ChargingStation(
        id="cs1",
        position=Position(x=200.0, y=200.0),
        capacity=5,
        queue_count=0,
        charging_vehicles=[],
        load_pressure=0.0,
        charging_rate=10.0
    )
    
    data_manager.set_warehouse_position(Position(x=0.0, y=0.0))
    data_manager.add_task(task)
    data_manager.add_vehicle(vehicle)
    data_manager.add_charging_station(station)
    
    state = data_manager.get_system_state()
    assert state is not None
    assert "tasks" in state
    assert "vehicles" in state
    assert "charging_stations" in state
    assert len(state["tasks"]) == 1
    assert len(state["vehicles"]) == 1
    assert len(state["charging_stations"]) == 1


def test_calculate_complete_path(data_manager):
    """测试完整路径计算功能"""
    # 设置仓库位置
    data_manager.set_warehouse_position(Position(x=0.0, y=0.0))
    
    # 添加任务和车辆（坐标应位于模拟图节点范围内）
    task = Task(
        id=1,
        position=Position(x=100.0, y=100.0),  # 调整为与 100m 步进网格匹配
        weight=10.0,
        create_time=1000,
        deadline=2000,
        priority=1
    )
    vehicle = Vehicle(
        id=1,
        position=Position(x=0.0, y=0.0),
        battery=100.0,
        max_battery=100.0,
        current_load=0.0,
        max_load=100.0,
        unit_energy_consumption=0.1
    )
    
    data_manager.add_task(task)
    data_manager.add_vehicle(vehicle)
    
    # 计算完整路径
    result = data_manager.calculate_complete_path(1, 1)
    
    # 验证结果
    assert result is not None
    assert result["task_id"] == 1
    assert result["vehicle_id"] == 1
    # 模拟图中从 (0,0) 到 (100,100) 的距离应为 200 (100+100)
    assert result["total_distance"] >= 200.0
    assert result["is_feasible"] == True
    assert len(result["complete_path"]) >= 3


def test_check_and_complete_task(data_manager):
    """测试任务完成判定功能"""
    # 设置仓库位置
    data_manager.set_warehouse_position(Position(x=0.0, y=0.0))
    
    # 添加任务和车辆
    task = Task(
        id=1,
        position=Position(x=3.0, y=4.0),
        weight=10.0,
        create_time=1000,
        deadline=2000,
        priority=1,
        status=TaskStatus.IN_PROGRESS,
        assigned_vehicle_id=1,
        start_time=1100
    )
    vehicle = Vehicle(
        id=1,
        position=Position(x=0.0, y=0.0),  # 车辆在仓库位置
        battery=100.0,
        max_battery=100.0,
        current_load=0.0,
        max_load=100.0,
        unit_energy_consumption=0.1,
        status=VehicleStatus.RETURNING_TO_WAREHOUSE,
        assigned_task_ids=[1]
    )
    
    data_manager.add_task(task)
    data_manager.add_vehicle(vehicle)
    
    # 检查并完成任务
    completed_tasks = data_manager.check_and_complete_task(1)
    
    # 验证任务已完成
    assert len(completed_tasks) == 1
    assert completed_tasks[0].id == 1
    assert completed_tasks[0].status == TaskStatus.COMPLETED
    
    # 验证车辆状态已更新
    updated_vehicle = data_manager.get_vehicle(1)
    assert updated_vehicle.status == VehicleStatus.IDLE
    assert len(updated_vehicle.assigned_task_ids) == 0


def test_is_at_warehouse(data_manager):
    """测试车辆是否在仓库位置的检测功能"""
    # 设置仓库位置
    data_manager.set_warehouse_position(Position(x=100.0, y=100.0))
    
    # 测试在仓库位置的情况
    position1 = Position(x=100.0, y=100.0)
    assert data_manager.is_at_warehouse(position1) == True
    
    # 测试接近仓库位置的情况
    position2 = Position(x=102.0, y=102.0)  # 在容差范围内
    assert data_manager.is_at_warehouse(position2) == True
    
    # 测试远离仓库位置的情况
    position3 = Position(x=5000.0, y=5000.0)  # 超出容差范围
    assert data_manager.is_at_warehouse(position3) == False


def test_update_vehicle_position_by_speed_completes_task(data_manager):
    """测试车辆沿完整路径推进后触发任务完成闭环"""
    data_manager.set_warehouse_position(Position(x=0.0, y=0.0))

    task = Task(
        id=101,
        position=Position(x=3.0, y=4.0),
        weight=10.0,
        create_time=1000,
        deadline=9999999999,
        priority=1,
        status=TaskStatus.IN_PROGRESS,
        assigned_vehicle_id=1,
        start_time=1001,
        complete_path_distance=10.0
    )
    vehicle = Vehicle(
        id=1,
        position=Position(x=0.0, y=0.0),
        battery=100.0,
        max_battery=100.0,
        current_load=0.0,
        max_load=100.0,
        unit_energy_consumption=0.1,
        speed=20.0,
        status=VehicleStatus.TRANSPORTING,
        assigned_task_ids=[101],
        complete_path=[(0.0, 0.0), (3.0, 4.0), (0.0, 0.0)]
    )

    data_manager.add_task(task)
    data_manager.add_vehicle(vehicle)

    data_manager.update_vehicle_position_by_speed(vehicle_id=1, time_delta=1.0)

    updated_task = data_manager.get_task(101)
    updated_vehicle = data_manager.get_vehicle(1)

    assert updated_task.status == TaskStatus.COMPLETED
    assert updated_vehicle.status == VehicleStatus.IDLE
    assert len(updated_vehicle.assigned_task_ids) == 0
