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

    VEHICLE_CONFIG: Dict[str, Dict[str, Any]] = {
        "small": {
            "max_battery": 50.0,
            "max_load": 50.0,
            "unit_energy_consumption": 0.15,
            "speed": 0.1
        },
        "medium": {
            "max_battery": 100.0,
            "max_load": 100.0,
            "unit_energy_consumption": 0.1,
            "speed": 0.1
        },
        "large": {
            "max_battery": 200.0,
            "max_load": 200.0,
            "unit_energy_consumption": 0.08,
            "speed": 0.08
        }
    }

    CHARGING_STATION_CONFIG: Dict[str, Any] = {
        "default_capacity": 5,
        "default_charging_rate": 10.0,
        "max_queue_time": 300
    }

    TASK_CONFIG: Dict[str, Any] = {
        "min_weight": 10.0,
        "max_weight": 200.0,
        "min_priority": 1,
        "max_priority": 5,
        "default_deadline_offset": 3600
    }

    ALGORITHM_CONFIG: Dict[str, Any] = {
        "genetic": {
            "population_size": 10,      # 从 100 改为 10
            "max_generations": 10,      # 从 500 改为 10
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
        "long_distance_threshold": 5.0
    }

    PERFORMANCE_METRICS: Dict[str, float] = {
        "completion_weight": 0.5,
        "time_weight": 0.3,
        "distance_weight": 0.2
    }

    @classmethod
    def get_vehicle_config(cls, vehicle_type: str) -> Dict[str, Any]:
        return cls.VEHICLE_CONFIG.get(vehicle_type, cls.VEHICLE_CONFIG["medium"])

    @classmethod
    def get_charging_station_config(cls) -> Dict[str, Any]:
        return cls.CHARGING_STATION_CONFIG

    @classmethod
    def get_task_config(cls) -> Dict[str, Any]:
        return cls.TASK_CONFIG

    @classmethod
    def get_algorithm_config(cls, algorithm_type: str) -> Dict[str, Any]:
        return cls.ALGORITHM_CONFIG.get(algorithm_type, {})

    @classmethod
    def get_strategy_config(cls) -> Dict[str, Any]:
        return cls.STRATEGY_CONFIG

config = Config()
