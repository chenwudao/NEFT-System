# NEFT - 新能源物流车队协同调度系统

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109.0-009688.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> 一个基于图结构的新能源物流车队智能调度系统，支持实时动态调度与静态全局优化。

## 📋 项目简介

NEFT（New Energy Fleet Transportation）是一个面向新能源物流车队的协同调度系统。系统模拟中央仓库管理场景，面对城市中动态出现的配送任务，智能规划新能源车辆的路径，同时考虑电量约束、载重限制、充电站调度等多维度因素。

### 核心特性

- 🚗 **多车型支持**：小型、中型、大型新能源车，各具不同的电量、载重和能耗特性
- 🗺️ **图结构道路网络**：基于真实地图数据（OpenStreetMap）构建图结构道路网络
- ⚡ **智能充电调度**：电量不足时自动寻找最优充电站，支持排队与负荷管理
- 🎯 **多策略调度**：最近任务优先、最大载重优先、优先级调度、复合评分策略等
- 📊 **静态全局优化**：使用 OR-Tools/MIP 求解器计算全局最优方案作为对比基准
- 🌐 **实时可视化**：WebSocket 实时推送 + 高德地图可视化展示
- 📈 **统一评分机制**：静态规划、实时调度、任务完成评估使用一致的评分标准

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                           前端层                                 │
│  • Web 界面展示 (HTML/CSS/JS)                                   │
│  • 高德地图集成                                                 │
│  • WebSocket 实时数据推送                                       │
└─────────────────────────────────────────────────────────────────┘
                              ↓ WebSocket/REST API
┌─────────────────────────────────────────────────────────────────┤
│                           接口层                                 │
│  • FastAPI Web 服务                                             │
│  • WebSocket 实时通信                                           │
│  • RESTful API                                                  │
└─────────────────────────────────────────────────────────────────┤
                              ↓
┌─────────────────────────────────────────────────────────────────┤
│                        调度决策层                                │
│  • 静态规划模块（OR-Tools/MIP 全局优化）                         │
│  • 动态调度模块（实时响应）                                      │
│  • 策略选择器（自动策略切换）                                    │
└─────────────────────────────────────────────────────────────────┤
                              ↓
┌─────────────────────────────────────────────────────────────────┤
│                          算法层                                  │
│  • OR-Tools 求解器（开源免费）                                   │
│  • MIP 求解器（Gurobi）                                         │
│  • 遗传算法（启发式优化）                                        │
│  • 实时调度策略（多策略支持）                                    │
└─────────────────────────────────────────────────────────────────┤
                              ↓
┌─────────────────────────────────────────────────────────────────┤
│                          数据层                                  │
│  • 任务管理（动态生成与状态跟踪）                                │
│  • 车辆管理（位置、电量、载重）                                  │
│  • 充电站管理（排队、负荷）                                      │
│  • 路径计算（图最短路径）                                        │
└─────────────────────────────────────────────────────────────────┘
```

## 🚀 快速开始

### 环境要求

- Python 3.12+
- Conda（推荐）或 pip
- 高德地图 API Key（用于地图展示）

### 安装步骤

1. **克隆仓库**

```bash
git clone https://github.com/chenwudao/NEFT-System.git
cd NEFT-System
```

2. **创建 Conda 环境**

```bash
conda create -n neft python=3.12 -y
conda activate neft
```

3. **安装依赖**

```bash
pip install -r backend/requirements.txt
```

4. **配置高德地图 API Key**

在 `frontend/index.html` 中替换你的高德地图 API Key：

```html
<script src="https://webapi.amap.com/maps?v=2.0&key=YOUR_AMAP_KEY"></script>
```

5. **启动后端服务**

```bash
cd backend
python main.py
```

服务将在 `http://localhost:8000` 启动。

6. **打开前端页面**

直接在浏览器中打开 `frontend/index.html`，或使用 Live Server 等工具。

## 📖 使用指南

### 1. 启动模拟

1. 打开 Web 界面
2. 选择调度模式：
   - **实时调度模式**：动态响应任务，支持多种调度策略
   - **静态规划模式**：定期执行全局优化，使用 OR-Tools/MIP 求解器
3. 选择问题规模：小规模（10任务/3车）、中规模（50任务/5车）、大规模（100任务/10车）
4. 点击"启动模拟"

### 2. 调度策略

系统支持多种实时调度策略：

| 策略名称 | 描述 | 适用场景 |
|---------|------|---------|
| `shortest_task_first` | 最近任务优先 | 快速响应、短距离配送 |
| `heaviest_task_first` | 最大载重优先 | 高载重利用率 |
| `priority_based` | 优先级调度 | 紧急任务优先 |
| `deadline_earliest_first` | 最早截止时间优先 | 时间敏感任务 |
| `composite_score` | 复合评分策略 | 综合多因素决策 |

### 3. 监控面板

- **任务监控**：实时显示任务状态（待处理/进行中/已完成/超时）
- **车辆监控**：位置、电量、载重、状态实时更新
- **充电站监控**：充电桩使用情况、排队车辆
- **性能指标**：总分、完成率、车辆利用率

### 4. API 接口

系统提供完整的 RESTful API：

```bash
# 启动模拟
POST /api/simulation/start

# 停止模拟
POST /api/simulation/stop

# 重置模拟
POST /api/simulation/reset

# 获取系统状态
GET /api/state

# 执行静态规划
POST /api/scheduling/static

# 获取任务列表
GET /api/tasks

# 获取车辆列表
GET /api/vehicles
```

## 🧪 测试

运行测试套件：

```bash
cd test
pytest -v
```

运行特定测试：

```bash
pytest test_ortools_solver.py -v
pytest test_dynamic_scheduling.py -v
```

## 📊 评分机制

系统采用统一的评分机制，确保静态规划与实时调度的可比性：

```
任务得分 = 120                    # 基础分配奖励
         + 30 × priority         # 优先级奖励
         - 0.02 × 距离(米)       # 距离惩罚
         - 0.2 × 能耗            # 能耗惩罚
         - 50 × 逾期分钟         # 逾期惩罚
```

## 🛠️ 技术栈

### 后端
- **FastAPI**: 高性能 Web 框架
- **WebSocket**: 实时双向通信
- **OR-Tools**: Google 开源优化求解器
- **Gurobi**: 商业 MIP 求解器（可选）
- **NetworkX**: 图算法库
- **OSMnx**: OpenStreetMap 数据处理

### 前端
- **原生 JavaScript**: 无框架依赖
- **高德地图 API**: 地图展示与路径绘制
- **WebSocket**: 实时数据接收

### 算法
- **静态规划**: OR-Tools + CBC 求解器（开源免费）
- **动态调度**: 多策略启发式算法
- **路径规划**: Dijkstra / A* 最短路径
- **聚类分析**: K-means 任务分组

## 📁 项目结构

```
NEFT-System/
├── backend/                    # 后端代码
│   ├── algorithm/              # 算法实现
│   │   ├── ortools_solver.py   # OR-Tools 求解器
│   │   ├── mip_solver.py       # MIP 求解器
│   │   ├── genetic_algorithm.py # 遗传算法
│   │   ├── scheduling_strategy.py # 调度策略基类
│   │   ├── shortest_task_first.py # 最近任务优先
│   │   ├── composite_score_strategy.py # 复合评分策略
│   │   └── scoring_config.py   # 统一评分配置
│   ├── data/                   # 数据管理
│   │   ├── data_manager.py     # 数据管理器
│   │   ├── task.py             # 任务模型
│   │   ├── vehicle.py          # 车辆模型
│   │   ├── charging_station.py # 充电站模型
│   │   └── path_calculator.py  # 路径计算
│   ├── decision/               # 调度决策
│   │   ├── static_planning_module.py  # 静态规划
│   │   ├── dynamic_scheduling_module.py # 动态调度
│   │   └── decision_manager.py # 决策管理器
│   ├── interface/              # 接口层
│   │   ├── api_controller.py   # API 控制器
│   │   └── websocket_handler.py # WebSocket 处理器
│   ├── main.py                 # 服务入口
│   └── requirements.txt        # 依赖列表
├── frontend/                   # 前端代码
│   ├── index.html              # 主页面
│   ├── script.js               # 前端逻辑
│   └── style.css               # 样式文件
├── test/                       # 测试代码
├── docs/                       # 文档
└── README.md                   # 项目说明
```

## 🔧 配置说明

### 环境变量

| 变量名 | 描述 | 默认值 |
|-------|------|--------|
| `NEFT_ENV` | 运行环境 | `development` |
| `NEFT_LOG_LEVEL` | 日志级别 | `INFO` |
| `NEFT_STATIC_PLAN_INTERVAL_SEC` | 静态规划间隔 | `3600` |
| `NEFT_DYNAMIC_SCHEDULE_INTERVAL_SEC` | 动态调度间隔 | `5` |

### 车辆参数配置

在 `backend/config.py` 中配置车辆参数：

```python
VEHICLE_TYPES = {
    "small": {
        "max_battery": 50.0,      # kWh
        "max_load": 500.0,        # kg
        "unit_energy_consumption": 0.15,  # kWh/km
        "speed": 8.0              # m/s
    },
    "medium": { ... },
    "large": { ... }
}
```

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 打开 Pull Request

## 📝 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

## 🙏 致谢

- [FastAPI](https://fastapi.tiangolo.com/) - 高性能 Web 框架
- [OR-Tools](https://developers.google.com/optimization) - Google 优化工具
- [OSMnx](https://osmnx.readthedocs.io/) - OpenStreetMap 网络分析
- [高德地图](https://lbs.amap.com/) - 地图服务

## 📧 联系方式

如有问题或建议，欢迎通过以下方式联系：

- 提交 [GitHub Issue](https://github.com/chenwudao/NEFT-System/issues)
- 发送邮件至项目维护者

---

**NEFT - 让新能源物流更智能、更高效！** 🚛⚡

---

# 📐 算法接口文档

本节描述重构后的**统一调度算法接口**。目标：把"写一个新算法"压缩到一个文件、几十行代码；让算法与仿真主循环、数据层完全解耦。

## 0. 心智模型

整个系统被刻意收敛成一个函数：

```
schedule: Snapshot → List[Command]
```

* **Snapshot**：某一瞬间的世界状态（车辆、任务、充电站、仓库、地图、时间戳）。只读。
* **Command**：对某辆车下达的**下一步动作**（去任务点 / 去充电站 / 回仓库 / 保持空闲）。
* **单步语义**：每个 Command 只描述"下一个目标节点"。车辆到达该节点后，主循环会再次捕获 Snapshot、再次调度，得到下下步。
* **不在列表里的车 = 保持原状态**：算法可以只给需要做决策的车发指令，其他车继续执行上一轮的动作。

车辆在图上的运动使用 **Dijkstra 最短路径**（按边权）完成，算法只需要关心"下一步去哪"，不管"怎么走过去"。

### 场景约束（刻意简化）

1. 所有车从**中心仓库**出发。
2. 只有回到仓库才能**装货 / 领取新任务**。
3. 只有回到仓库才会把运输完成的任务标记为 `COMPLETED`（货物算"交付到任务点"后，载重减少，但任务要回仓之后才真正结算得分）。
4. 如果快照刚好在车辆穿越一条边的中途捕获，**视为车辆已在下一个节点**——所有决策都基于那个节点。
5. 调度策略在 `backend/config.py` 里显式配置，不做自动切换。

## 1. 目录结构

```
backend/algorithm/
├── snapshot.py            # Snapshot 数据类（算法唯一输入）
├── scheduler.py           # Scheduler 基类 + Command 数据类
├── utils.py               # 度量 / 指令构造 / 决策模板
├── algorithm_manager.py   # 注册中心：按名字分发到 Scheduler
├── scoring_config.py      # 评分常量（供 PathCalculator 用，不影响算法接口）
└── schedulers/            # 算法实现全部放这里
    ├── __init__.py        # 导出 + 注册点（EXPORTED_SCHEDULERS）
    ├── nearest_task.py    # 最近任务优先（示例）
    ├── priority_task.py   # 优先级 + 最近距离（示例）
    └── mst_batch.py       # MST 批量拼单（示例：一次带多个任务）
```

## 2. 核心数据类

### 2.1 `Snapshot`

```python
Snapshot(
    vehicles,            # List[Vehicle]        所有车辆
    tasks,               # List[Task]           所有任务
    charging_stations,   # List[ChargingStation]
    warehouse_xy,        # (x, y)               中心仓库坐标
    timestamp,           # Unix 秒
    path_calculator,     # 路径 / 距离查询入口
)
```

算法里最常用的便捷方法：

| 方法                              | 说明                                                         |
| --------------------------------- | ------------------------------------------------------------ |
| `vehicles_need_decision()`        | 需要下发新指令的车（空闲 / 刚到站 / 可以接新任务）           |
| `idle_vehicles_at_warehouse()`    | 当前在仓库、可以立即装货出发的车                             |
| `available_tasks()`               | 状态为 `PENDING` 的任务                                      |
| `distance(a_xy, b_xy)`            | 两点间路网最短距离（米，不可达 → +inf）                      |
| `path(a_xy, b_xy)`                | 最短路径节点序列                                             |

### 2.2 `Command`

```python
Command(
    vehicle_id,         # 指向哪辆车
    action,             # "deliver" | "charge" | "return" | "idle"
    target_xy,          # 下一步要去的坐标 (x, y)
    assigned_tasks=[],  # 仅 deliver 且车刚从仓库出发：这一趟要带走的所有任务 ID
    task_id=None,       # 仅 deliver：当前这一段在送的具体任务 ID
    station_id=None,    # 仅 charge：目标充电站 ID
)
```

使用者**不需要**手写 `Command(...)`，`utils.py` 里给了一整套 `make_*_command` 帮助函数。

## 3. `utils` 工具函数

| 类型       | 函数                                       | 用途                                                             |
| ---------- | ------------------------------------------ | ---------------------------------------------------------------- |
| 度量       | `distance_to(xy_a, xy_b, pc)`              | 两点路网距离（米；不可达 → +inf）                                |
| 度量       | `needs_charge(vehicle)`                    | 是否低于 `low_battery_pct` 阈值                                  |
| 度量       | `can_reach_with_battery(v, xy, pc)`        | 从车辆当前位置到 `xy` 的耗能是否小于剩余电量                     |
| 查询       | `feasible_tasks_for(v, tasks)`             | 筛选这辆车还装得下的任务                                         |
| 查询       | `nearest_task(v, tasks, pc)`               | 最近可承运任务                                                   |
| 查询       | `nearest_station(v, stations, pc)`         | 最近充电站                                                       |
| 序列化     | `greedy_chain(start_xy, tasks, pc)`        | 从起点开始的贪心链（依次挑最近的下一个任务）                     |
| 序列化     | `mst_order(start_xy, tasks, pc)`           | 按最小生成树 DFS 访问顺序排列任务                                |
| 指令构造   | `make_idle_command(v)`                     | 空闲指令                                                         |
| 指令构造   | `make_return_command(v, warehouse_xy)`     | 回仓指令                                                         |
| 指令构造   | `make_charge_command(v, station, pc)`      | 去充电站                                                         |
| 指令构造   | `make_deliver_command(v, tasks)`           | 送货：`assigned_tasks` 整串 + `task_id` 指向第一个 + `target_xy` 为第一个任务点 |
| 决策模板   | `decide_at_warehouse(v, snapshot, strategy_fn)` | 车在仓库时：先看电量是否需要充电，否则调 `strategy_fn` 选任务批次、构造 deliver Command；没任务则 idle |
| 决策模板   | `decide_en_route(v, snapshot)`             | 车不在仓库时：有已接任务就继续送下一个，否则返回仓库             |

`decide_at_warehouse` + `decide_en_route` 组合覆盖了绝大多数策略，只需要注入一个"怎么选任务"的函数即可。

## 4. 写一个新算法（3 分钟模板）

以"重任务优先"为例：

1. **新建** `backend/algorithm/schedulers/heaviest_first.py`

```python
from typing import List
from ..scheduler import Command, Scheduler
from ..snapshot import Snapshot
from ..utils import decide_at_warehouse, decide_en_route


class HeaviestFirstScheduler(Scheduler):
    """重任务优先：按重量降序挑第一个能装下的任务。"""
    name = "heaviest_first"

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        commands: List[Command] = []

        def pick_tasks(v, available):
            candidates = [t for t in available if t.weight <= v.max_load]
            if not candidates:
                return []
            candidates.sort(key=lambda t: -t.weight)
            return [candidates[0]]

        for v in snapshot.vehicles_need_decision():
            if v.position.to_tuple() == snapshot.warehouse_xy:
                commands.append(decide_at_warehouse(v, snapshot, pick_tasks))
            else:
                commands.append(decide_en_route(v, snapshot))
        return commands
```

2. **在 `schedulers/__init__.py` 导出并注册**

```python
from .heaviest_first import HeaviestFirstScheduler

EXPORTED_SCHEDULERS = [
    NearestTaskScheduler,
    PriorityTaskScheduler,
    MstBatchScheduler,
    HeaviestFirstScheduler,   # ← 新算法
]
```

`AlgorithmManager` 会在启动时自动实例化并按 `.name` 注册。

3. **在 `config.py` 切换策略**

```python
SCHEDULING_CONFIG = {
    "strategy": "heaviest_first",
    ...
}
```

完成。重启后端即可生效。

## 5. 需要更强控制时

模板 `decide_at_warehouse / decide_en_route` 覆盖的是"每车独立决策"的情况。如果要：

* **多车协同 / 分配优化**：直接在 `schedule()` 里自己遍历 `snapshot.idle_vehicles_at_warehouse()` 和 `snapshot.available_tasks()`，做匈牙利 / ILP 分配，再用 `make_deliver_command` 下发。
* **批量拼单**：参考 `mst_batch.py`：一次给 `assigned_tasks` 塞多个任务 ID，车辆会按 MST 顺序一个接一个送过去。
* **换单 / 抢占**：只要给某辆正在跑的车发新 Command，下层就会覆盖它当前路径。没给的车保持原样。
* **考虑充电站排队压力**：`ChargingStation.load_pressure` 直接可用。

## 6. 调用入口一览

* **主循环自动触发**：`backend/main.py → background_tasks` 按 `DYNAMIC_SCHEDULE_INTERVAL_SEC` 调 `decision_manager.dynamic_scheduling()`，策略从 `config.SCHEDULING_CONFIG["strategy"]` 读取。
* **HTTP 手动触发**：`POST /api/scheduling`，body 里可传 `{ "strategy": "xxx" }` 覆盖一次；不传则沿用 config。
* **可用策略列表**：`GET /api/strategies`。
* **直接调用**（脚本 / 单测）：

  ```python
  from backend.algorithm import AlgorithmManager, Snapshot
  snap = Snapshot.capture(data_manager)
  commands = algorithm_manager.schedule("nearest_task", snap)
  ```

## 7. 运行说明

1. **配置策略与参数**：编辑 `backend/config.py`

   ```python
   SCHEDULING_CONFIG = {
       "strategy": "nearest_task",   # 或 priority_task / mst_batch / 你自己的
       "low_battery_pct": 0.2,       # 低于该比例主动去充电
       "charge_until_pct": 0.9,      # 充到该比例出站
       "max_tasks_per_trip": 4,      # 一趟最多带几个任务（MST 批量用）
   }
   ```

2. **启动后端**

   ```bash
   cd backend
   python main.py
   ```

   服务监听 `http://localhost:8000`。

3. **打开前端**：浏览器打开 `frontend/index.html`。
   * 仓库 / 充电站 / 任务点 / 车辆会实时显示；
   * 每辆车的目标节点（`current_target`）会作为标记出现；
   * 连接线已移除，地图更清爽。

4. **切换策略**：改 `config.py` 的 `strategy` 后重启，或通过 `POST /api/scheduling` 临时指定。

## 8. 这次重构移除/保留的东西

移除：

* 旧的静态规划整条链（MIP / OR-Tools / GA / `StaticPlanningModule`）。
* 旧的 `SchedulingStrategy` 基类及其所有子类。
* `DecisionManager` 里的自动策略选择、主动低电量管理、充电离站情境评估等逻辑——已统一由 `config.py` 阈值 + 主循环 + 算法内部 `decide_at_warehouse` 处理。
* Task 的 `complete_path` / `estimated_completion_time`，Vehicle 的 `current_path` / `complete_path` / `path_progress` 等冗余字段（内部以 `current_route` + `_route_index` 替代；对外 `to_dict()` 仍保留旧名以兼容前端）。

保留：

* `scoring_config.py` — `PathCalculator.calculate_task_score` 仍依赖它。
* WebSocket 实时广播、前端地图可视化。
