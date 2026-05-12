import pytest
import time
from backend.data.path_calculator import PathCalculator
from backend.data.task import Task
from backend.config import config

def test_task_score_calculation():
    calculator = PathCalculator(grid_unit=1.0)
    now = int(time.time())
    
    # 模拟一个普通任务
    t1 = Task(id=1, weight=100, position=None,
              create_time=now, deadline=now + 5000, priority=3)
              
    # 参数
    dynamic_avg_distance = 1500.0
    actual_distance = 1000.0
    
    # 计算得分（按时完成）
    # path_length_bonus = (1500 / max(1, 1000)) * 10 = 15.0
    # priority_bonus = 3 * 5 = 15
    # score = 100 + 15 + 15 = 130
    
    score = calculator.calculate_task_score(
        task=t1,
        completion_time=now + 1000,
        complete_path_distance=actual_distance,
        avg_path_length=dynamic_avg_distance
    )
    
    assert score >= 100.0
    assert abs(score - 130.0) < 0.1
    
    # 计算得分（超时完成）
    # 超时惩罚基础分是 -50
    # score = -50 + 15 + 15 = -20
    
    score_late = calculator.calculate_task_score(
        task=t1,
        completion_time=now + 6000,   # > deadline
        complete_path_distance=actual_distance,
        avg_path_length=dynamic_avg_distance
    )
    
    assert score_late < 0
    assert abs(score_late + 20.0) < 0.1
