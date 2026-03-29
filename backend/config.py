import os
from typing import Dict, Any

class Config:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./neft.db")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-here")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    CORS_ORIGINS: list = ["*"]

    WEBSOCKET_HEARTBEAT_INTERVAL: int = 30
    WEBSOCKET_MAX_CONNECTIONS: int = 100

    PLANNING_INTERVAL: int = 3600
    STATIC_PLANNING_ENABLED: bool = True

    # ---------------------------------------------------------------------------
    # 车辆配置（参照真实新能源物流车：宇通E6/比亚迪T3）
    # 速度单位: m/s；能耗单位: kWh等效/m；电量单位: kWh等效
    # 续航计算：max_battery / unit_energy_consumption
    #   small : 60 / 0.00025 = 240,000m ≈ 240km
    #   medium: 100 / 0.0003  = 333,333m ≈ 333km
    #   large : 150 / 0.0004  = 375,000m ≈ 375km
    # ---------------------------------------------------------------------------
    VEHICLE_CONFIG: Dict[str, Dict[str, Any]] = {
        "small": {
            "max_battery": 60.0,            # kWh等效
            "max_load": 500.0,              # kg
            "unit_energy_consumption": 0.00025,  # /m，续航≈240km
            "speed": 10.0,                  # m/s ≈ 36km/h
            "charging_power": 0.015,        # kWh/s，从20%→80%约40min
        },
        "medium": {
            "max_battery": 100.0,
            "max_load": 1500.0,             # kg
            "unit_energy_consumption": 0.0003,   # /m，续航≈333km
            "speed": 10.0,                  # m/s
            "charging_power": 0.022,        # kWh/s，从20%→80%约45min
        },
        "large": {
            "max_battery": 150.0,
            "max_load": 5000.0,             # kg
            "unit_energy_consumption": 0.0004,   # /m，续航≈375km
            "speed": 8.0,                   # m/s ≈ 29km/h（重载较慢）
            "charging_power": 0.030,        # kWh/s，从20%→80%约60min
        }
    }

    # ---------------------------------------------------------------------------
    # 充电站配置
    # capacity: 每站充电桩数量（并发充电车辆上限）
    # ---------------------------------------------------------------------------
    CHARGING_STATION_CONFIG: Dict[str, Any] = {
        "default_capacity": 3,          # 每站3个充电桩
        "max_queue_time": 600,          # 最大等待时间（秒）
    }

    # ---------------------------------------------------------------------------
    # 车队规模配置（番禺区，固定，不随任务规模变化）
    # ---------------------------------------------------------------------------
    FLEET_CONFIG: Dict[str, Any] = {
        "small_count": 8,
        "medium_count": 15,
        "large_count": 7,
        "station_count": 6,             # 充电站数量
    }

    # ---------------------------------------------------------------------------
    # 任务配置
    # weight 单位: kg，与 vehicle.max_load 一致
    # ---------------------------------------------------------------------------
    TASK_CONFIG: Dict[str, Any] = {
        "min_weight": 10.0,             # kg
        "max_weight": 1500.0,           # kg（medium车可单车装载）
        "min_priority": 1,
        "max_priority": 5,
        "default_deadline_offset": 3600,  # 秒
        "min_deadline_offset": 1800,      # 秒（最短30min截止）
        "max_deadline_offset": 7200,      # 秒（最长2h截止）
    }

    # ---------------------------------------------------------------------------
    # 静态规划任务规模（仅在 static 模式下使用）
    # ---------------------------------------------------------------------------
    TASK_SCALE_CONFIG: Dict[str, Any] = {
        "small":  {"min_tasks": 10,  "max_tasks": 20},
        "medium": {"min_tasks": 30,  "max_tasks": 60},
        "large":  {"min_tasks": 80,  "max_tasks": 150},
    }

    ALGORITHM_CONFIG: Dict[str, Any] = {
        "genetic": {
            "population_size": 100,
            "max_generations": 300,
            "mutation_rate": 0.1,
            "crossover_rate": 0.8
        },
        "clustering": {
            "k": 3,
            "max_iterations": 100
        }
    }

    STRATEGY_CONFIG: Dict[str, Any] = {
        "heavy_task_ratio": 0.8,
        "light_task_ratio": 0.2,
        "long_distance_threshold": 5000.0,  # 米（番禺区尺度）
    }

    # ---------------------------------------------------------------------------
    # 仿真速度配置
    # ---------------------------------------------------------------------------
    SIMULATION_CONFIG: Dict[str, Any] = {
        # 模拟速度倍率：1现实秒 = SIM_SPEED_FACTOR 仿真秒
        # 60 = 1秒现实时间推进1分钟仿真时间（默认）
        # 120 = 1秒现实时间推进2分钟仿真时间（快速）
        # 300 = 1秒现实时间推进5分钟仿真时间（超快，适合演示）
        "speed_factor": int(os.getenv("NEFT_SIM_SPEED", "120")),  # 默认120，提升观感
        "tick_interval": 1.0,  # 现实秒，每tick间隔
    }

    ROUTING_CONFIG: Dict[str, Any] = {
        "graph": {
            "place_name": os.getenv("GRAPH_PLACE_NAME", "Panyu District, Guangzhou, Guangdong, China"),
            "network_type": os.getenv("GRAPH_NETWORK_TYPE", "drive"),
            "main_roads_only": os.getenv("GRAPH_MAIN_ROADS_ONLY", "true").lower() == "true"  # 默认使用主干路精简版
        }
    }

    PERFORMANCE_METRICS: Dict[str, float] = {
        "completion_weight": 0.5,
        "time_weight": 0.3,
        "distance_weight": 0.2
    }

    # ---------------------------------------------------------------------------
    # 充电管理阈值（情境感知策略）
    # ---------------------------------------------------------------------------
    CHARGING_THRESHOLDS: Dict[str, Any] = {
        "normal_release": 100.0,        # 建议1：默认充满100%再离站
        "urgent_release": 60.0,         # 任务紧急时（deadline<30min）充到60%即离
        "full_release": 100.0,          # 保持（与normal_release相同，充满）
        "idle_ratio_for_full": 1.5,     # 保留字段（已并入normal_release=100%，不再需要区分）
        "urgent_deadline_window": 1800, # 截止时间窗口（秒），小于此值=紧急任务
        "interrupt_priority": 4,        # 可打断充电的最低任务优先级
        "low_battery_threshold": 20.0,  # 电量低于此%时主动触发充电管理
    }

    @classmethod
    def get_vehicle_config(cls, vehicle_type: str) -> Dict[str, Any]:
        return cls.VEHICLE_CONFIG.get(vehicle_type, cls.VEHICLE_CONFIG["medium"])

    @classmethod
    def get_charging_station_config(cls) -> Dict[str, Any]:
        return cls.CHARGING_STATION_CONFIG

    @classmethod
    def get_fleet_config(cls) -> Dict[str, Any]:
        return cls.FLEET_CONFIG

    @classmethod
    def get_task_config(cls) -> Dict[str, Any]:
        return cls.TASK_CONFIG

    @classmethod
    def get_task_scale_config(cls, scale: str = "medium") -> Dict[str, Any]:
        return cls.TASK_SCALE_CONFIG.get(scale, cls.TASK_SCALE_CONFIG["medium"])

    @classmethod
    def get_algorithm_config(cls, algorithm_type: str) -> Dict[str, Any]:
        return cls.ALGORITHM_CONFIG.get(algorithm_type, {})

    @classmethod
    def get_strategy_config(cls) -> Dict[str, Any]:
        return cls.STRATEGY_CONFIG

    @classmethod
    def get_routing_config(cls) -> Dict[str, Any]:
        return cls.ROUTING_CONFIG

    @classmethod
    def get_simulation_config(cls) -> Dict[str, Any]:
        return cls.SIMULATION_CONFIG

    @classmethod
    def get_charging_thresholds(cls) -> Dict[str, Any]:
        return cls.CHARGING_THRESHOLDS

config = Config()
