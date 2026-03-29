import pytest
from backend.algorithm.meta_strategy_selector import MetaStrategySelector
from backend.data.path_calculator import PathCalculator
from backend.data.task import Task
from backend.data.vehicle import Vehicle, VehicleStatus

def test_meta_strategy_selector_evaluate():
    pc = PathCalculator()
    selector = MetaStrategySelector(path_calculator=pc)
    
    # 构建测试用的空闲车辆和待处理任务
    t1 = Task(id=1, weight=100, position=None, 
              create_time=1000, deadline=2000, priority=1)
    t2 = Task(id=2, weight=200, position=None,
              create_time=1000, deadline=3000, priority=5)
    
    v1 = Vehicle(id=101, position=None, battery=100.0, max_battery=100.0,
                 current_load=0, max_load=1500, unit_energy_consumption=0.0003,
                 speed=500.0, vehicle_type='medium', charging_power=0.022)
    
    # 模拟两个不同的策略生成的 commands (V3 规范：使用 assigned_tasks 列表及 action_type)
    # 策略A 只分配了 t1
    cmds_A = [{"vehicle_id": 101, "assigned_tasks": [1], "action_type": "transport", "estimated_time": 10.0}]
    # 策略B 只分配了 t2
    cmds_B = [{"vehicle_id": 101, "assigned_tasks": [2], "action_type": "transport", "estimated_time": 10.0}]
    
    candidate_commands = {
        "strategy_A": cmds_A,
        "strategy_B": cmds_B
    }
    
    current_time = 1500
    
    res = selector.evaluate(
        candidate_commands=candidate_commands,
        pending_tasks=[t1, t2],
        vehicles=[v1],
        charging_stations=[],
        current_timestamp=current_time
    )
    
    assert "selected_strategy" in res
    assert "strategy_scores" in res
    
    scores = res["strategy_scores"]
    assert "strategy_A" in scores
    assert "strategy_B" in scores
    
    # B策略分配了优先级为5的任务，应当得分远高于A策略分配的优先级为1的任务
    # 按照代码逻辑 total_priority * 30.0，B的基础优先级得分 5 * 30 = 150，A的只有 1 * 30 = 30
    assert scores["strategy_B"]["total_score"] > scores["strategy_A"]["total_score"]
    assert res["selected_strategy"] == "strategy_B"
