import pytest
import time
from backend.algorithm.composite_score_strategy import CompositeScoreStrategy
from backend.data.task import Task
from backend.data.position import Position
from backend.data.path_calculator import PathCalculator

def test_composite_strategy_adaptive_weights():
    # 使用无路网计算器
    pc = PathCalculator()
    now = int(time.time())
    
    # 模拟全局参数
    global_params = {"timestamp": now}
    
    # 辅助函数：快速创建策略实例
    def get_strat(tasks):
        return CompositeScoreStrategy(
            idle_vehicles=[], 
            pending_tasks=tasks,
            charging_stations=[],
            global_params=global_params,
            path_calculator=pc
        )
                                   
    # 场景1：常规场景（增加一些轻任务，避免单任务总触发 heavy_ratio > 0.5）
    tasks_normal = [
        Task(id=1, weight=1000, position=None, create_time=now, deadline=now + 3600, priority=1),
        Task(id=11, weight=100, position=None, create_time=now, deadline=now + 3600, priority=1),
        Task(id=12, weight=100, position=None, create_time=now, deadline=now + 3600, priority=1)
    ]
    strat_normal = get_strat(tasks_normal)
    w_normal = strat_normal._compute_adaptive_weights()
    
    # 默认均衡权重
    assert w_normal["urgency"] == 0.15
    assert w_normal["distance"] == 0.30
    assert w_normal["weight"] == 0.30
    assert w_normal["priority"] == 0.25
    
    # 场景2：紧急任务过多（100% 任务在 1800s 内到期）
    tasks_urgent = [
        Task(id=2, weight=100, position=None, create_time=now, deadline=now + 1000, priority=1)
    ]
    strat_urgent = get_strat(tasks_urgent)
    w_urgent = strat_urgent._compute_adaptive_weights()
    
    assert w_urgent["urgency"] == 0.40
    assert w_urgent["priority"] == 0.30
    assert w_urgent["weight"] == 0.15
    assert w_urgent["distance"] == 0.15

    # 场景3：重型任务过多（均重比 0.8 以上占多数）
    tasks_heavy = [
        Task(id=3, weight=1000, position=None, create_time=now, deadline=now + 5000, priority=1),
        Task(id=4, weight=50, position=None, create_time=now, deadline=now + 5000, priority=1),
        Task(id=5, weight=900, position=None, create_time=now, deadline=now + 5000, priority=1)
    ]
    strat_heavy = get_strat(tasks_heavy)
    w_heavy = strat_heavy._compute_adaptive_weights()
    
    assert w_heavy["weight"] == 0.40
    assert w_heavy["distance"] == 0.30
    assert w_heavy["priority"] == 0.20
    assert w_heavy["urgency"] == 0.10
