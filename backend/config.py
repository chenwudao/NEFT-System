"""NEFT 系统全局配置。

本文件是唯一的配置入口。两种使用模式：

  1) **直接改本文件**：编辑下方各 *_CONFIG 字典里的常量。适合"长期默认值"。

  2) **通过 YAML 覆盖**（推荐对比实验用法）：
        - 在 `configs/` 下放一个 yaml 文件（参考 configs/small.yaml）。
        - 通过环境变量 `NEFT_CONFIG_FILE=configs/medium.yaml` 启动后端，
          配置就会从该 yaml 加载并覆盖本文件里的默认值。
        - yaml 里没写到的字段自动沿用本文件的默认值。

约定：
    - 所有"数量"都是具体整数，不再有 small/medium/large 规模选择；
      规模差异由 yaml 表达。
    - 所有时间单位若未另注明一律为"秒"。
    - 位置坐标 (x, y) 约定为 WGS84 (x=经度, y=纬度)。
"""

from __future__ import annotations

import copy
import os
from typing import Any, Dict, Optional

try:
    import yaml as _yaml  # type: ignore
except Exception:  # pragma: no cover
    _yaml = None


# ----------------------------------------------------------------------
# YAML overrides
# ----------------------------------------------------------------------

def _project_root() -> str:
    # backend/config.py -> project root
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_config_file_path() -> Optional[str]:
    """允许 NEFT_CONFIG_FILE 取绝对路径或相对项目根目录的路径。"""
    raw = os.getenv("NEFT_CONFIG_FILE")
    if not raw:
        return None
    if os.path.isabs(raw):
        return raw
    return os.path.join(_project_root(), raw)


def _load_yaml_overrides() -> Dict[str, Any]:
    path = _resolve_config_file_path()
    if not path:
        return {}
    if not os.path.exists(path):
        print(f"[Config] WARNING: NEFT_CONFIG_FILE='{path}' not found, ignoring.")
        return {}
    if _yaml is None:
        print("[Config] WARNING: pyyaml not installed; NEFT_CONFIG_FILE ignored.")
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = _yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            print(f"[Config] WARNING: yaml at '{path}' is not a mapping; ignored.")
            return {}
        print(f"[Config] Loaded overrides from: {path}")
        return data
    except Exception as exc:
        print(f"[Config] ERROR: failed to read '{path}': {exc}")
        return {}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """深合并：override 覆盖 base 中的同名字段，dict 会递归合并。"""
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


_YAML_OVERRIDES: Dict[str, Any] = _load_yaml_overrides()


def _section(name: str, default: Dict[str, Any]) -> Dict[str, Any]:
    """从 yaml override 中拿一节，没拿到就用 default。"""
    if not _YAML_OVERRIDES:
        return copy.deepcopy(default)
    if name in _YAML_OVERRIDES and isinstance(_YAML_OVERRIDES[name], dict):
        return _deep_merge(default, _YAML_OVERRIDES[name])
    return copy.deepcopy(default)


# ----------------------------------------------------------------------
# 默认配置（"代码内的硬编码默认值"）
# ----------------------------------------------------------------------

_DEFAULT_EXPERIMENT: Dict[str, Any] = {
    "name": os.getenv("NEFT_EXP_NAME", "default"),
    "log_dir": os.getenv("NEFT_LOG_DIR", "log"),
}

_DEFAULT_SCHEDULING: Dict[str, Any] = {
    "strategy":              os.getenv("NEFT_STRATEGY", "nearest_task"),
    "low_battery_pct":       20.0,
    "charge_until_pct":      90.0,
    "battery_safety_margin": 1.15,
    "charge_load_weight_m":  8000.0,
    "charge_queue_weight_m": 2000.0,
    # 复合评分策略默认权重
    "composite_weights": {
        "priority":       1.0,
        "urgency":        1.5,
        "load":           0.3,
        "distance":       1.0,
        "scale_distance": 10000.0,
        "urgency_window": 7200.0,
    },
    # SA 默认参数
    "sa": {
        "iterations":   1500,
        "t_start":      1000.0,
        "t_end":        1.0,
        "alpha_reward": 2.0,
        "seed":         42,
    },
}

_DEFAULT_VEHICLE: Dict[str, Dict[str, Any]] = {
    "small": {
        "max_battery":             60.0,
        "max_load":                500.0,
        "unit_energy_consumption": 0.00025,
        "speed":                   10.0,
        "charging_power":          0.015,
    },
    "medium": {
        "max_battery":             100.0,
        "max_load":                1500.0,
        "unit_energy_consumption": 0.0003,
        "speed":                   10.0,
        "charging_power":          0.022,
    },
    "large": {
        "max_battery":             150.0,
        "max_load":                5000.0,
        "unit_energy_consumption": 0.0004,
        "speed":                   8.0,
        "charging_power":          0.030,
    },
}

_DEFAULT_FLEET: Dict[str, Any] = {
    "small_count":   2,
    "medium_count":  3,
    "large_count":   1,
    "station_count": 2,
}

_DEFAULT_CHARGING: Dict[str, Any] = {
    "default_capacity": 3,
    "max_queue_time":   600,
}

_DEFAULT_TASK: Dict[str, Any] = {
    "initial_tasks":               5,
    "generation_interval_sec_min": 10,
    "generation_interval_sec_max": 30,
    "generation_batch_min":        1,
    "generation_batch_max":        3,
    "max_pending_tasks":           20,
    "min_weight":                  10.0,
    "max_weight":                  1500.0,
    "min_priority":                1,
    "max_priority":                5,
    "min_deadline_offset":         1800,
    "max_deadline_offset":         7200,
    # 整次仿真内最多生成多少个任务，None=不限。yaml 里通常会设一个数。
    "total_task_budget":           None,
    # 可复现实验：读取任务生成种子流文件；None 表示随机生成并在日志目录落盘。
    "generation_seed_file":        None,
}

_DEFAULT_SIMULATION: Dict[str, Any] = {
    "speed_factor":           int(os.getenv("NEFT_SIM_SPEED", "120")),
    "tick_interval":          1.0,
    # 【任务生成截止时间，仿真秒】
    # 到达后停止生成新任务，但仿真继续直到所有现存任务进入终态
    # （COMPLETED / TIMEOUT）。None = 不限，只受 total_task_budget 约束。
    "max_sim_seconds":        None,
    "marker_tween_ms":        900,
    "marker_tween_adaptive":  True,
    # 全部任务结算后是否自动停止仿真
    "stop_when_all_tasks_done": True,
}

_DEFAULT_ROUTING: Dict[str, Any] = {
    "graph": {
        "place_name":      os.getenv("GRAPH_PLACE_NAME", "Panyu District, Guangzhou, Guangdong, China"),
        "network_type":    os.getenv("GRAPH_NETWORK_TYPE", "drive"),
        "main_roads_only": os.getenv("GRAPH_MAIN_ROADS_ONLY", "false").lower() == "true",
    },
}

_DEFAULT_PERF: Dict[str, float] = {
    "completion_weight": 0.5,
    "time_weight":       0.3,
    "distance_weight":   0.2,
}

_DEFAULT_SCORING: Dict[str, Any] = {
    # 任务最终得分 / 调度估分通用参数（默认值与旧实现保持一致）
    "task_assign_reward": 120.0,
    "priority_reward": 30.0,
    "distance_penalty": 0.02,
    "early_completion_reward_per_min": 2.0,
    "overdue_penalty_per_min": 50.0,
    "idle_penalty": 5.0,
    # 估算完成时间参数
    "assumed_speed_mps": 10.0,
    # 时间窗口（与部分策略估分对齐）
    "urgent_deadline_window": 1800,
    "max_deadline_window": 7200,
}

_DEFAULT_OPTIMIZATION: Dict[str, Any] = {
    # dynamic: 在线动态调度（默认）
    # static:  上帝视角静态优化（任务全集已知）
    "mode": "dynamic",
    "static": {
        "strategy": "static_exact_solver",
        # 期望求解器（可选）：gurobi / cplex
        "solver": "gurobi",
        # 精确搜索的任务上限（超过后自动降级为近似分配）
        "max_exact_tasks": 10,
        # 严格模式：必须返回全局最优(OPTIMAL, MIPGap=0)，否则失败，不做近似降级
        "strict_global_optimum": False,
        # 非严格模式下的可接受MIPGap阈值（例如 0.01/0.02）
        "mip_gap_threshold": 0.02,
        # 求解时限（秒）；None 表示不限
        "time_limit_s": 300,
    },
}


# ----------------------------------------------------------------------
# 实际配置（默认值 ⊕ yaml override）
# ----------------------------------------------------------------------

class Config:
    """系统配置访问接口。所有调用方都走类方法，不直接读类属性。"""

    # 静态成员（向后兼容已有 import 路径）
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./neft.db")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-here")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    CORS_ORIGINS: list = ["*"]

    WEBSOCKET_HEARTBEAT_INTERVAL: int = 30
    WEBSOCKET_MAX_CONNECTIONS: int = 100

    EXPERIMENT_CONFIG: Dict[str, Any]      = _section("experiment", _DEFAULT_EXPERIMENT)
    SCHEDULING_CONFIG: Dict[str, Any]      = _section("scheduling", _DEFAULT_SCHEDULING)
    VEHICLE_CONFIG: Dict[str, Dict[str, Any]] = _section("vehicle", _DEFAULT_VEHICLE)
    FLEET_CONFIG: Dict[str, Any]           = _section("fleet", _DEFAULT_FLEET)
    CHARGING_STATION_CONFIG: Dict[str, Any] = _section("charging_station", _DEFAULT_CHARGING)
    TASK_CONFIG: Dict[str, Any]            = _section("task", _DEFAULT_TASK)
    SIMULATION_CONFIG: Dict[str, Any]      = _section("simulation", _DEFAULT_SIMULATION)
    ROUTING_CONFIG: Dict[str, Any]         = _section("routing", _DEFAULT_ROUTING)
    PERFORMANCE_METRICS: Dict[str, float]  = _section("performance_metrics", _DEFAULT_PERF)
    SCORING_CONFIG: Dict[str, Any]         = _section("scoring", _DEFAULT_SCORING)
    OPTIMIZATION_CONFIG: Dict[str, Any]    = _section("optimization", _DEFAULT_OPTIMIZATION)

    # -------------------------------------------------------------------------
    # Getters（保持稳定接口）
    # -------------------------------------------------------------------------
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
    def get_routing_config(cls) -> Dict[str, Any]:
        return cls.ROUTING_CONFIG

    @classmethod
    def get_simulation_config(cls) -> Dict[str, Any]:
        return cls.SIMULATION_CONFIG

    @classmethod
    def get_scheduling_config(cls) -> Dict[str, Any]:
        return cls.SCHEDULING_CONFIG

    @classmethod
    def get_experiment_config(cls) -> Dict[str, Any]:
        return cls.EXPERIMENT_CONFIG

    @classmethod
    def get_scoring_config(cls) -> Dict[str, Any]:
        return cls.SCORING_CONFIG

    @classmethod
    def get_optimization_config(cls) -> Dict[str, Any]:
        return cls.OPTIMIZATION_CONFIG

    @classmethod
    def get_config_file_path(cls) -> Optional[str]:
        """返回当前使用的 YAML 配置文件路径（若无返回 None）。"""
        return _resolve_config_file_path()

    @classmethod
    def snapshot(cls) -> Dict[str, Any]:
        """把目前所有会影响仿真行为的配置打包成一个 dict，方便写 log。"""
        return {
            "experiment":          cls.get_experiment_config(),
            "scheduling":          cls.get_scheduling_config(),
            "fleet":               cls.get_fleet_config(),
            "vehicle":             cls.VEHICLE_CONFIG,
            "charging_station":    cls.get_charging_station_config(),
            "task":                cls.get_task_config(),
            "simulation":          cls.get_simulation_config(),
            "routing":             cls.get_routing_config(),
            "scoring":             cls.get_scoring_config(),
            "optimization":        cls.get_optimization_config(),
            "performance_metrics": cls.PERFORMANCE_METRICS,
            "config_file":         cls.get_config_file_path(),
        }


config = Config()
