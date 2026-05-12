"""Deadline unification, PENDING-only feasible tasks, and meta-strategy consistency."""
import pytest

from backend.algorithm.algorithm_manager import AlgorithmManager
from backend.algorithm.shortest_task_first import ShortestTaskFirstStrategy
from backend.data.data_manager import DataManager
from backend.data.position import Position
from backend.data.task import Task, TaskStatus, apply_deadline_timeouts
from backend.data.vehicle import Vehicle, VehicleStatus
@pytest.fixture
def data_manager():
    dm = DataManager()
    dm.set_warehouse_position(Position(x=0, y=0))
    return dm


@pytest.fixture
def algorithm_manager(data_manager):
    return AlgorithmManager(data_manager.path_calculator)


def test_apply_deadline_timeouts_marks_overdue_only():
    t_ok = Task(
        id=1, position=Position(x=0, y=0), weight=1, create_time=0,
        deadline=9999, priority=1, status=TaskStatus.PENDING,
    )
    t_old = Task(
        id=2, position=Position(x=0, y=0), weight=1, create_time=0,
        deadline=100, priority=1, status=TaskStatus.PENDING,
    )
    apply_deadline_timeouts([t_ok, t_old], current_timestamp=1000)
    assert t_ok.status == TaskStatus.PENDING
    assert t_old.status == TaskStatus.TIMEOUT


def test_filter_feasible_tasks_excludes_non_pending(data_manager):
    path_calculator = data_manager.path_calculator
    vehicle = Vehicle(
        id=1, position=Position(x=0, y=0), battery=100, max_battery=100,
        current_load=0, max_load=100, unit_energy_consumption=0.1,
    )
    t_pending = Task(
        id=1, position=Position(x=100, y=0), weight=10, create_time=0,
        deadline=9999, priority=1, status=TaskStatus.PENDING,
    )
    t_timeout = Task(
        id=2, position=Position(x=200, y=0), weight=10, create_time=0,
        deadline=1, priority=1, status=TaskStatus.TIMEOUT,
    )
    global_params = {"warehouse_position": (0.0, 0.0), "timestamp": 1000}
    strategy = ShortestTaskFirstStrategy(
        [vehicle], [t_pending, t_timeout], [], global_params, path_calculator
    )
    feas = strategy.filter_feasible_tasks(vehicle)
    assert len(feas) == 1
    assert feas[0].id == 1


def test_strategy_selection_with_deadline_timeout(data_manager, algorithm_manager):
    """测试截止时间超时后任务状态变更和策略执行"""
    vehicle = Vehicle(
        id=1, position=Position(x=0, y=0), battery=100, max_battery=100,
        current_load=0, max_load=100, unit_energy_consumption=0.1, speed=10.0,
    )
    overdue = Task(
        id=1, position=Position(x=100, y=0), weight=10, create_time=0,
        deadline=500, priority=1, status=TaskStatus.PENDING,
    )
    data_manager.add_vehicle(vehicle)
    data_manager.add_task(overdue)

    global_params = {
        "warehouse_position": (data_manager.warehouse_position.x, data_manager.warehouse_position.y),
        "timestamp": 1000,
    }
    
    # 直接执行策略，验证超时任务被过滤
    commands = algorithm_manager.schedule_realtime(
        strategy="shortest_task_first",
        idle_vehicles=data_manager.get_idle_vehicles(),
        pending_tasks=data_manager.get_pending_tasks(),
        charging_stations=[],
        global_params=global_params,
    )
    
    # 验证任务已被标记为TIMEOUT
    assert overdue.status == TaskStatus.TIMEOUT
    # 验证返回的是命令列表
    assert isinstance(commands, list)


def test_clear_completed_commands_removes_stale_transport(data_manager, algorithm_manager):
    from backend.decision.dynamic_scheduling_module import DynamicSchedulingModule

    dsm = DynamicSchedulingModule(data_manager, algorithm_manager)
    v = Vehicle(
        id=1, position=Position(x=0, y=0), battery=100, max_battery=100,
        current_load=0, max_load=100, unit_energy_consumption=0.1,
    )
    data_manager.add_vehicle(v)
    dsm.active_commands.append({
        "vehicle_id": 1,
        "action_type": "transport",
        "assigned_tasks": [],
        "path": [],
    })
    data_manager.get_vehicle(1).update_status(VehicleStatus.IDLE)
    dsm.clear_completed_commands()
    assert dsm.active_commands == []
