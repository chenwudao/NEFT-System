import pytest
import time
from backend.decision.decision_manager import DecisionManager
from backend.data.data_manager import DataManager
from backend.data.vehicle import Vehicle, VehicleStatus
from backend.data.task import Task
from backend.config import config

from backend.algorithm.algorithm_manager import AlgorithmManager
def test_charge_release_thresholds():
    dm = DataManager()
    alg_mgr = AlgorithmManager(dm.path_calculator)
    decision_mgr = DecisionManager(dm, alg_mgr)
    
    # 构建测试用的车辆
    v1 = Vehicle(id=1, position=None, battery=20, max_battery=100.0,
                 current_load=0, max_load=1500, unit_energy_consumption=0.0003,
                 speed=500.0, vehicle_type='medium', charging_power=0.022)
    dm.vehicles[1] = v1
    
    # 情境 1：常规场景（无任务），应返回 100.0（根据 config.normal_release=100.0）
    dm.tasks = {}
    threshold_normal = decision_mgr.evaluate_charge_release_threshold(v1)
    assert threshold_normal == 100.0
    
    # 情境 2：存在紧急任务（截止时间在 30 分钟即 1800 秒内）
    now = int(time.time())
    t1 = Task(id=1, weight=100, position=None,
              create_time=now, deadline=now + 1000, priority=1)
    dm.add_task(t1)
    
    threshold_urgent = decision_mgr.evaluate_charge_release_threshold(v1)
    assert threshold_urgent == 60.0  # config.urgent_release = 60.0
    
    # 情境 3：高优任务打断条件 (priority >= 4 且无空闲车辆，车辆正在充电)
    dm.tasks = {}
    t2 = Task(id=2, weight=100, position=None,
              create_time=now, deadline=now + 1000, priority=5)
    dm.add_task(t2)
    
    # 虽然车没插，但只要存在紧急任务，也会返回 60.0
    threshold_idle = decision_mgr.evaluate_charge_release_threshold(v1)
    assert threshold_idle == 60.0
    
    # 把这辆车状态改为 CHARGING，触发高优先级任务强行唤醒
    v1.status = VehicleStatus.CHARGING
    threshold_interrupt = decision_mgr.evaluate_charge_release_threshold(v1)
    assert threshold_interrupt <= 0.0  # 返回 0.0 表示立即释出
