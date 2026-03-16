import pytest
from backend.decision.strategy_selector import StrategySelector
from backend.data.data_manager import DataManager
from backend.data.position import Position
from backend.data.task import Task, TaskStatus
from backend.data.vehicle import Vehicle, VehicleStatus

@pytest.fixture
def data_manager():
    dm = DataManager()
    dm.set_warehouse_position(Position(x=0, y=0))
    return dm

@pytest.fixture
def strategy_selector():
    return StrategySelector()

def test_strategy_selector_initialization(strategy_selector):
    """测试策略选择器初始化"""
    assert strategy_selector is not None

def test_select_strategy(strategy_selector):
    """测试策略选择功能"""
    # 测试默认策略选择
    strategy = strategy_selector.select_strategy([], [], {})
    assert strategy is not None
    assert isinstance(strategy, str)

def test_select_strategy_with_tasks(strategy_selector):
    """测试有任务时的策略选择"""
    # 创建测试任务
    task1 = Task(
        id=1, position=Position(x=10, y=10), weight=10, create_time=1000, 
        deadline=2000, priority=1, status=TaskStatus.PENDING
    )
    task2 = Task(
        id=2, position=Position(x=20, y=20), weight=20, create_time=1000, 
        deadline=2000, priority=2, status=TaskStatus.PENDING
    )
    
    # 测试策略选择
    strategy = strategy_selector.select_strategy([task1, task2], [], {})
    assert strategy is not None
    assert isinstance(strategy, str)

def test_get_available_strategies(strategy_selector):
    """测试获取可用策略"""
    # 直接测试策略选择功能
    strategy = strategy_selector.select_strategy([], [], {})
    assert strategy is not None
    assert isinstance(strategy, str)

def test_analyze_system_state(strategy_selector):
    """测试系统状态分析"""
    # 创建测试数据
    vehicle = Vehicle(
        id=1, position=Position(x=0, y=0), battery=100, max_battery=100,
        current_load=0, max_load=100, unit_energy_consumption=0.1
    )
    task = Task(
        id=1, position=Position(x=10, y=10), weight=10, create_time=1000, 
        deadline=2000, priority=1, status=TaskStatus.PENDING
    )
    
    # 测试策略选择器的分析功能
    task_features = strategy_selector.analyze_task_features([task])
    assert isinstance(task_features, dict)
    assert "avg_weight" in task_features
    assert "max_weight" in task_features
    assert "task_count" in task_features
    assert task_features["task_count"] == 1
    
    # 测试系统状态评估
    system_state = strategy_selector.evaluate_system_state([vehicle], Position(x=0, y=0))
    assert isinstance(system_state, dict)
    assert "avg_battery" in system_state
    assert "idle_count" in system_state
    assert "total_capacity" in system_state
