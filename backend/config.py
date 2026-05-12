"""NEFT 系统全局配置。

本文件是唯一的配置入口。修改以下数字即可改变仿真行为，无需再改代码。

约定：
    - 所有"数量"都是具体整数，不再有 small/medium/large 规模选择；
      前端 UI 不提供规模切换。
    - 所有时间单位若未另注明一律为"秒"。
    - 位置坐标 (x, y) 约定为 WGS84 (x=经度, y=纬度)。

修改流程：改 -> 保存 -> 重启后端。
"""

import os
from typing import Any, Dict

class Config:
    # =========================================================================
    # 基础 / 安全相关（一般不用改）
    # =========================================================================
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./neft.db")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-here")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    CORS_ORIGINS: list = ["*"]

    WEBSOCKET_HEARTBEAT_INTERVAL: int = 30
    WEBSOCKET_MAX_CONNECTIONS: int = 100

    # =========================================================================
    # 实验标识 & 日志
    #
    # 每次启动仿真都会在 `log_dir` 下建一个子文件夹，命名：
    #     <name>_<YYYYMMDD_HHMMSS>/
    # 内含：
    #     - config.json  : 本次运行用的完整配置快照
    #     - results.json : 仿真结束时的最终指标 + 任务/车辆明细
    #
    # 修改 `name` 为一个有意义的标签（例如 "nearest-vs-mst-batch"），
    # 之后对比不同算法跑出来的结果就方便。
    # =========================================================================
    EXPERIMENT_CONFIG: Dict[str, Any] = {
        "name": os.getenv("NEFT_EXP_NAME", "default"),
        # 相对项目根目录
        "log_dir": os.getenv("NEFT_LOG_DIR", "log"),
    }

    # =========================================================================
    # 调度策略
    #
    # `strategy` 直接决定用哪一个 Scheduler 实现。候选值 == schedulers 包中所有
    # 类的 .name 字段。目前已注册（见 backend/algorithm/schedulers/__init__.py）：
    #
    #   +-----------------+--------------------------------------------------+
    #   | strategy 取值   | 说明                                             |
    #   +-----------------+--------------------------------------------------+
    #   | "nearest_task"  | 贪心：最近任务优先；最简单的基线                 |
    #   | "priority_task" | 按 priority 降序、再按距离升序                   |
    #   | "mst_batch"     | 在仓库一次装一批，用 MST+DFS 决定访问顺序        |
    #   +-----------------+--------------------------------------------------+
    #
    # 新加算法的步骤：
    #   1) backend/algorithm/schedulers/xxx.py 里写一个
    #      `class XxxScheduler(Scheduler): name = "xxx"`，实现
    #      schedule(snapshot) -> List[Command]
    #   2) 在 schedulers/__init__.py 把类加到 EXPORTED_SCHEDULERS
    #   3) 把这里的 "strategy" 改成 "xxx"，重启后端
    # 整套接口定义见 README 的"算法接口文档"章节。
    # =========================================================================
    SCHEDULING_CONFIG: Dict[str, Any] = {
        # 当前生效的算法名。必须等于上表里列出的某个取值，写错了会自动回退到
        # AlgorithmManager.DEFAULT_STRATEGY ("nearest_task")。
        "strategy": os.getenv("NEFT_STRATEGY", "nearest_task"),

        # 低电量阈值（百分比，0~100）。
        # 车辆回到仓库时，若 battery_percentage <= 该值，调度器会优先派它去充电
        # 而不是接新任务。
        # 注：如果电量真的掉到 0（算法不会调度充电 / 距离误判），车辆会在原地
        #     进入 VehicleStatus.STRANDED 状态，本次仿真中永远停在那里，
        #     身上的任务也不会被完成——用来惩罚把车开到没电的算法。
        "low_battery_pct": 20.0,

        # 充电离站阈值（百分比，0~100）。
        # 车辆在充电站充电到 >= 该值时会被自动"踢出"充电站，转为 IDLE。
        "charge_until_pct": 90.0,

        # 单趟装货任务数上限。
        #   int  : 每辆车每趟最多接这么多个任务
        #   None : 不限（只受 vehicle.max_load 上限约束）
        "max_tasks_per_trip": None,
    }

    # =========================================================================
    # 车辆参数（按车型；**不是**车辆数，数量见下面的 FLEET_CONFIG）
    #
    # 每种车型必须给全下列 5 个字段：
    #   max_battery              : 最大电池容量，单位 kWh 等效。满电初始化用。
    #   max_load                 : 最大载重，单位 kg。不能超过。
    #   unit_energy_consumption  : 单位能耗，单位 kWh / 米。
    #                              续航估算 = max_battery / unit_energy_consumption
    #   speed                    : 行驶速度，单位 m/s（"仿真秒"里的 m/s）。
    #                              UI 上看到的视觉速度还要乘 speed_factor。
    #   charging_power           : 充电功率，单位 kWh / 仿真秒。
    #
    # 新增车型：在下方字典新增一个 key；然后在 FLEET_CONFIG 里给它一个 <key>_count。
    # =========================================================================
    VEHICLE_CONFIG: Dict[str, Dict[str, Any]] = {
        "small": {
            "max_battery":             60.0,
            "max_load":                500.0,
            "unit_energy_consumption": 0.00025,   # 续航 ≈ 240 km
            "speed":                   10.0,      # ≈ 36 km/h
            "charging_power":          0.015,     # 20%→80% 约 40 分钟
        },
        "medium": {
            "max_battery":             100.0,
            "max_load":                1500.0,
            "unit_energy_consumption": 0.0003,    # 续航 ≈ 333 km
            "speed":                   10.0,      # ≈ 36 km/h
            "charging_power":          0.022,
        },
        "large": {
            "max_battery":             150.0,
            "max_load":                5000.0,
            "unit_energy_consumption": 0.0004,    # 续航 ≈ 375 km
            "speed":                   8.0,       # ≈ 29 km/h（重载慢）
            "charging_power":          0.030,
        },
    }

    # =========================================================================
    # 车队组成 & 充电站数量（具体整数）
    #
    # 这些数字直接决定仿真启动时的实体数量：
    #     small_count   : 多少辆 "small"  车型
    #     medium_count  : 多少辆 "medium" 车型
    #     large_count   : 多少辆 "large"  车型
    #     station_count : 多少座充电站
    #
    # 注：总车辆数 = small_count + medium_count + large_count。
    #     想让界面清爽就把数字调小；想做压力测试就调大。
    #     数值设为 0 表示完全不要这种资源。
    # =========================================================================
    FLEET_CONFIG: Dict[str, Any] = {
        "small_count":   2,
        "medium_count":  3,
        "large_count":   1,          # => 本例总共 6 辆车
        "station_count": 2,
    }

    # =========================================================================
    # 充电站参数（每座站的内部能力，所有站共用）
    # =========================================================================
    CHARGING_STATION_CONFIG: Dict[str, Any] = {
        # 每座站的充电桩数量（并发充电车辆上限）。车辆多于桩数时排队。
        "default_capacity": 3,

        # 最大允许排队时间，单位：仿真秒。只用于日志/告警，不影响决策逻辑。
        "max_queue_time": 600,
    }

    # =========================================================================
    # 任务参数
    #
    # 任务在运行过程中由 task_generator 持续生成，节奏如下：
    #   - 启动时一次性生成 `initial_tasks` 个任务打底。
    #   - 之后每隔
    #        random(generation_interval_sec_min, generation_interval_sec_max)
    #     墙钟秒生成一批。
    #   - 每批大小为
    #        random(generation_batch_min, generation_batch_max)。
    #   - 系统中同时存在的 PENDING 任务数永远不会超过 `max_pending_tasks`；
    #     达到上限后 task_generator 会跳过当轮生成。
    #
    # 每个任务的属性按下面的闭区间随机：
    #   weight    ∈ [min_weight, max_weight]             单位 kg
    #   priority  ∈ [min_priority, max_priority]         整数（大=优先级高）
    #   deadline  = create_time + random(min_deadline_offset, max_deadline_offset)
    #                                                    单位：秒
    # =========================================================================
    TASK_CONFIG: Dict[str, Any] = {
        # ---------- 批量生成节奏 ----------
        "initial_tasks":               5,      # 启动时先生成的任务数
        "generation_interval_sec_min": 10,     # 下一批生成间隔下限（墙钟秒）
        "generation_interval_sec_max": 30,     # 下一批生成间隔上限（墙钟秒）
        "generation_batch_min":        1,      # 每批最少生成几个
        "generation_batch_max":        3,      # 每批最多生成几个
        "max_pending_tasks":           20,     # 同时允许的 PENDING 任务上限

        # ---------- 单任务属性区间（闭区间） ----------
        "min_weight":                  10.0,   # 任务重量下限（kg）
        "max_weight":                  1500.0, # 任务重量上限（kg）
        "min_priority":                1,      # 优先级下限（1 = 最低）
        "max_priority":                5,      # 优先级上限（5 = 最高）
        "min_deadline_offset":         1800,   # 截止偏移下限（秒；30 min）
        "max_deadline_offset":         7200,   # 截止偏移上限（秒；2 h）
    }

    # =========================================================================
    # 仿真循环参数
    #
    # 时间模型：
    #   主循环每 `tick_interval` 现实秒调用一次，
    #   每次 tick 把仿真时钟推进 speed_factor × tick_interval 仿真秒。
    # 字段：
    #   speed_factor    : 每 1 现实秒推进多少"仿真秒"。
    #                     ↓  → 视觉更慢、物理更精细
    #                     ↑  → 演示更快、插值更粗糙
    #   tick_interval   : 主循环 tick 的现实秒间隔（基本不用改）。
    #   max_sim_seconds : 仿真时钟上限，单位"仿真秒"。
    #                     int  : 超过后自动停止并落盘 results.json
    #                     None : 不限，只靠人为暂停
    # =========================================================================
    SIMULATION_CONFIG: Dict[str, Any] = {
        "speed_factor":    int(os.getenv("NEFT_SIM_SPEED", "120")),  # ×120：1 秒现实 = 2 分钟仿真
        "tick_interval":   1.0,
        "max_sim_seconds": None,   # e.g. 3600 = 最多跑 1 仿真小时

        # ----- 前端视觉动画（marker 平滑移动） -----
        # 每次后端推送新位置 → 前端把车辆 marker 用 requestAnimationFrame
        # 线性插值过去，用时 = `marker_tween_ms` 毫秒。
        #
        # marker_tween_ms:
        #   建议 200~900 之间；应当 <= tick_interval * 1000 以免动画还没跑完
        #   下一个 tick 就已经到了（会被打断）。
        #   小 → 车头看起来"snap"更干脆，末段减速感弱
        #   大 → 整条轨迹更顺滑，但末段（最后一小段路）看起来更慢
        #
        # marker_tween_adaptive:
        #   True  : 末段自动按"实际移动距离 / 预期每 tick 距离"缩短 tween 时长，
        #           让车辆的**视觉速度**在全程保持均匀（接近终点不再变慢）。
        #   False : 每次都用固定的 marker_tween_ms，末段会看起来减速。
        "marker_tween_ms":       900,
        "marker_tween_adaptive": True,
    }

    # =========================================================================
    # 路网配置（OpenStreetMap via osmnx + networkx）
    #
    # 整体是一张有向 NetworkX 图：
    #   - 节点 = 路口
    #   - 边的 length = 两路口之间**真实道路长度（米）**，用作 Dijkstra 的权重
    #
    # 注意：这里的 length 是"静态"的，不会随时间变化，**也没有**拥堵 / 流量建模；
    #      车辆"感受"到的快慢只有两个来源：
    #        (a) 自己的 speed（车型决定）
    #        (b) Dijkstra 路径的绕行距离（路网越稀疏越容易绕远）
    #
    # 字段：
    #   place_name      : OSM 地名，首次启动时会被 osmnx 下载并缓存
    #   network_type    : OSM 网络类型
    #                     "drive" 机动车道 / "walk" 步行 / "bike" 自行车 / "all" 全部
    #   main_roads_only : True  只保留 primary/secondary 以上主干路（图小、加载快、易绕路、支路全没）
    #                     False 完整 OSM 路网（图大、路径贴直线、加载慢；2D Canvas 底图里能看到所有小路）
    #                     —— 默认 False，以便 2D Canvas 的 nx 底图看起来像真实城市；
    #                        若觉得启动慢、CPU 吃紧，可以把环境变量 GRAPH_MAIN_ROADS_ONLY=true。
    # =========================================================================
    ROUTING_CONFIG: Dict[str, Any] = {
        "graph": {
            "place_name":      os.getenv("GRAPH_PLACE_NAME", "Panyu District, Guangzhou, Guangdong, China"),
            "network_type":    os.getenv("GRAPH_NETWORK_TYPE", "drive"),
            "main_roads_only": os.getenv("GRAPH_MAIN_ROADS_ONLY", "false").lower() == "true",
        },
    }

    # =========================================================================
    # 综合评分权重（仅用于系统整体得分展示，不影响单任务 score 计算）
    #
    # 三个权重应加起来为 1.0；含义：
    #   completion_weight : 完成率（完成任务数 / 总任务数）
    #   time_weight       : 准时率（按时完成数 / 完成数）
    #   distance_weight   : 路径效率（越短越高）
    # =========================================================================
    PERFORMANCE_METRICS: Dict[str, float] = {
        "completion_weight": 0.5,
        "time_weight":       0.3,
        "distance_weight":   0.2,
    }

    # -------------------------------------------------------------------------
    # Getters（保持稳定接口，其他模块全部走这些方法读取配置）
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
    def snapshot(cls) -> Dict[str, Any]:
        """把目前所有会影响仿真行为的配置打包成一个 dict，方便写 log。"""
        return {
            "experiment":        cls.get_experiment_config(),
            "scheduling":        cls.get_scheduling_config(),
            "fleet":             cls.get_fleet_config(),
            "vehicle_types":     cls.VEHICLE_CONFIG,
            "charging_station":  cls.get_charging_station_config(),
            "task":              cls.get_task_config(),
            "simulation":        cls.get_simulation_config(),
            "routing":           cls.get_routing_config(),
            "performance_metrics": cls.PERFORMANCE_METRICS,
        }


config = Config()
