import pytest
from backend.config import config

def test_config_initialization():
    """测试配置初始化"""
    assert config is not None
    assert hasattr(config, 'DATABASE_URL')
    assert hasattr(config, 'SECRET_KEY')
    assert hasattr(config, 'ALGORITHM')
    assert hasattr(config, 'ACCESS_TOKEN_EXPIRE_MINUTES')
    assert hasattr(config, 'CORS_ORIGINS')
    assert hasattr(config, 'WEBSOCKET_HEARTBEAT_INTERVAL')
    assert hasattr(config, 'WEBSOCKET_MAX_CONNECTIONS')
    assert hasattr(config, 'PLANNING_INTERVAL')
    assert hasattr(config, 'STATIC_PLANNING_ENABLED')

def test_vehicle_config():
    """测试车辆配置"""
    # 测试获取小型车辆配置
    small_config = config.get_vehicle_config("small")
    assert small_config is not None
    assert "max_battery" in small_config
    assert "max_load" in small_config
    assert "unit_energy_consumption" in small_config
    assert "speed" in small_config
    assert small_config["max_battery"] == 50.0
    
    # 测试获取中型车辆配置
    medium_config = config.get_vehicle_config("medium")
    assert medium_config is not None
    assert medium_config["max_battery"] == 100.0
    
    # 测试获取大型车辆配置
    large_config = config.get_vehicle_config("large")
    assert large_config is not None
    assert large_config["max_battery"] == 200.0
    
    # 测试获取默认配置
    default_config = config.get_vehicle_config("unknown")
    assert default_config is not None
    assert default_config["max_battery"] == 100.0  # 默认应该是中型配置

def test_charging_station_config():
    """测试充电站配置"""
    station_config = config.get_charging_station_config()
    assert station_config is not None
    assert "default_capacity" in station_config
    assert "default_charging_rate" in station_config
    assert "max_queue_time" in station_config
    assert station_config["default_capacity"] == 5
    assert station_config["default_charging_rate"] == 10.0

def test_task_config():
    """测试任务配置"""
    task_config = config.get_task_config()
    assert task_config is not None
    assert "min_weight" in task_config
    assert "max_weight" in task_config
    assert "min_priority" in task_config
    assert "max_priority" in task_config
    assert "default_deadline_offset" in task_config
    assert task_config["min_weight"] == 10.0
    assert task_config["max_weight"] == 200.0
    assert task_config["min_priority"] == 1
    assert task_config["max_priority"] == 5

def test_algorithm_config():
    """测试算法配置"""
    # 测试获取遗传算法配置
    genetic_config = config.get_algorithm_config("genetic")
    assert genetic_config is not None
    assert "population_size" in genetic_config
    assert "max_generations" in genetic_config
    assert "mutation_rate" in genetic_config
    assert "crossover_rate" in genetic_config
    assert genetic_config["population_size"] == 10
    
    # 测试获取聚类算法配置
    clustering_config = config.get_algorithm_config("clustering")
    assert clustering_config is not None
    assert "k" in clustering_config
    assert "max_iterations" in clustering_config
    assert clustering_config["k"] == 3
    
    # 测试获取默认配置
    default_config = config.get_algorithm_config("unknown")
    assert default_config == {}

def test_strategy_config():
    """测试策略配置"""
    strategy_config = config.get_strategy_config()
    assert strategy_config is not None
    assert "heavy_task_ratio" in strategy_config
    assert "light_task_ratio" in strategy_config
    assert "long_distance_threshold" in strategy_config
    assert strategy_config["heavy_task_ratio"] == 0.8
    assert strategy_config["light_task_ratio"] == 0.2
    assert strategy_config["long_distance_threshold"] == 5.0

def test_performance_metrics():
    """测试性能指标配置"""
    performance_metrics = config.PERFORMANCE_METRICS
    assert performance_metrics is not None
    assert "completion_weight" in performance_metrics
    assert "time_weight" in performance_metrics
    assert "distance_weight" in performance_metrics
    assert performance_metrics["completion_weight"] == 0.5
    assert performance_metrics["time_weight"] == 0.3
    assert performance_metrics["distance_weight"] == 0.2
