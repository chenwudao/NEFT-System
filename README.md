# NEFT - 新能源物流车队协同调度系统

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109.0-009688.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> 基于 OpenStreetMap 路网图的新能源物流车队仿真与调度系统，支持多种动态调度策略、Web 实时可视化与 YAML 可复现实验配置。

## 项目简介

NEFT（New Energy Fleet Transportation）模拟**中央仓库 + 动态任务流 + 新能源车队**的城配场景。系统从真实地图（默认广州番禺区）构建道路网络图，车辆在 Dijkstra 最短路径上移动，调度算法每轮输出"下一步去哪"（送货 / 充电 / 回仓 / 空闲 / 接力交接），并统一处理电量预判与充电站排队。

### 核心特性

- **多车型车队**：小型 / 中型 / 大型车，各自不同的电量、载重、能耗与充电功率
- **图结构路网**：基于 OSMnx + NetworkX，从 OpenStreetMap 拉取并缓存道路网络
- **10 种动态调度策略**：从最近任务贪心到区域规划、拍卖协同、DFS/SA 装批搜索、RL 装批、协同接力等
- **统一评分机制**：任务结算与装批估分共用 `scoring_config.py` 中的公式
- **YAML 配置驱动**：车队规模、任务流量、策略、仿真时长等均可通过 yaml 覆盖，无需改代码
- **任务种子复现**：支持 record / replay 任务生成流，便于公平对比不同算法
- **Web 实时可视化**：FastAPI + WebSocket + 高德地图 / 2D Canvas 双模式
- **实验日志**：每次仿真自动写入 `log/<experiment.name>/` 目录

---

## 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│  前端 frontend/                                               │
│  index.html + script.js — 高德地图 / Canvas、WebSocket 订阅   │
└───────────────────────────────┬──────────────────────────────┘
                                │ REST / WebSocket
┌───────────────────────────────▼──────────────────────────────┐
│  接口层 backend/interface/                                    │
│  api_controller.py — REST API                                 │
│  websocket_handler.py — 实时推送                                │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│  仿真主循环 backend/main.py                                   │
│  任务生成 → 车辆运动/充电 → 周期性调度 → 终止判定 → 写日志      │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│  决策层 backend/decision/                                     │
│  DecisionManager → DynamicSchedulingModule                    │
│  Snapshot.capture → AlgorithmManager.schedule → 执行 Command  │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│  算法层 backend/algorithm/                                    │
│  schedulers/* — 各策略实现；utils.py — 电量预判 / 指令构造     │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│  数据层 backend/data/                                         │
│  DataManager / Task / Vehicle / ChargingStation / PathCalculator│
└──────────────────────────────────────────────────────────────┘
```

**调度心智模型**：`schedule: Snapshot → List[Command]`

- **Snapshot**：某一瞬间的只读世界状态（车辆、任务、充电站、仓库、路网、仿真时间）
- **Command**：对某辆车下达的**下一步动作**（只描述下一个目标节点）
- 车辆沿 Dijkstra 最短路径移动；到达节点后再次调度
- 未出现在 Command 列表中的车辆保持原状态

---

## 快速开始

### 环境要求

- Python 3.12+
- pip 或 Conda
- 高德地图 API Key（使用真实地图模式时需要；2D Canvas 模式可不需要）

### 安装

```bash
git clone https://github.com/chenwudao/NEFT-System.git
cd NEFT-System

conda create -n neft python=3.12 -y   # 可选
conda activate neft

pip install -r backend/requirements.txt
```

首次启动会从 OpenStreetMap 下载番禺区路网并缓存，可能需要几分钟。

### 配置高德地图 Key（可选）

编辑 `frontend/index.html`，替换高德 JS API Key 与安全密钥：

```html
<script>
  window._AMapSecurityConfig = { securityJsCode: 'YOUR_SECURITY_CODE' };
</script>
<script src="https://webapi.amap.com/maps?v=2.0&key=YOUR_AMAP_KEY"></script>
```

---

## 使用方式

### 1. 通过 YAML 启动（推荐）

所有仿真参数由 `backend/config.py` 提供默认值，YAML 文件按节覆盖。项目内置配置位于 `configs/`：

| 配置文件 | 模式 | 说明 |
|---------|------|------|
| `configs/dynamic/small.yaml` | 动态 | 3 车 / 1 站 / 约 20 任务 |
| `configs/dynamic/medium.yaml` | 动态 | 6 车 / 2 站 / 约 80 任务 |
| `configs/dynamic/large.yaml` | 动态 | 12 车 / 4 站 / 约 200 任务 |
| `configs/static/small.yaml` | 静态 | 上帝视角预加载全部任务 |
| `configs/static/medium.yaml` | 静态 | 中规模静态模式 |

**在项目根目录启动**（推荐写法）：

```powershell
# Windows PowerShell
python backend\main.py --cfg configs\dynamic\medium.yaml
```

```bash
# Linux / macOS
python backend/main.py --cfg configs/dynamic/medium.yaml
```

也支持 `--config` 别名与绝对路径：

```powershell
python backend\main.py --cfg "F:\Data Structure\NEFT-System-main\NEFT-System\configs\dynamic\large.yaml"
```

**等价的环境变量方式**：

```powershell
# PowerShell
$env:NEFT_CONFIG_FILE = "configs\dynamic\medium.yaml"
python backend\main.py
```

```bash
# Bash
NEFT_CONFIG_FILE=configs/dynamic/medium.yaml python backend/main.py
```

启动成功后后端监听 `http://localhost:8000`，Swagger 文档在 `http://localhost:8000/docs`。

> **说明**：`--cfg` 必须在 import `backend.config` 之前生效，`main.py` 会在启动最早阶段将其转为 `NEFT_CONFIG_FILE` 环境变量。

### 2. 无前端 Headless 模式

不启动 Web 服务，直接在终端跑完整次仿真并自动写日志，适合批量跑实验：

```powershell
python backend\main.py --cfg configs\dynamic\small.yaml --headless
```

简写：

```powershell
python backend\main.py --cfg configs\dynamic\small.yaml -u
```

Headless 与 Web 模式共用同一套仿真逻辑、终止条件与日志格式，结束后在控制台打印 `log_dir` 路径。

### 3. 使用默认内置配置启动

不传 `--cfg` 时，完全使用 `backend/config.py` 中的默认值：

```powershell
python backend\main.py
```

默认约 6 辆车、2 个充电站、策略 `nearest_task`、实验名 `default`。

### 4. Web 前端可视化

1. 先按上述方式启动后端
2. 用浏览器打开 `frontend/index.html`（或 Live Server 等静态服务）
3. 前端默认连接 `http://localhost:8000/api` 与 `ws://localhost:8000/ws`

**前端操作**：

| 按钮 | 作用 |
|------|------|
| 启动模拟 | `POST /api/simulation/start`，初始化车队/充电站/任务并开始推进 |
| 暂停模拟 | `POST /api/simulation/stop`，暂停并落盘实验结果 |
| 重置仿真 | `POST /api/simulation/reset`，清空状态；若正在运行则先写日志 |
| 切换地图模式 | 高德地图 ↔ 2D Canvas（Canvas 模式会拉取 `/api/graph` 绘制路网） |

**监控面板**显示：仿真状态、策略名、仿真时长、总分、完成率、车辆利用率、任务/车辆/充电站列表等。WebSocket 实时推送状态，无需手动刷新。

> 规模、策略、任务预算等**不再由前端选择**，全部在启动后端时通过 YAML / `config.py` 决定。前端只负责启停与可视化。

### 5. REST API 完整列表

#### 仿真控制（定义在 `main.py`）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/simulation/start` | 开始仿真，创建实验日志目录 |
| POST | `/api/simulation/stop` | 暂停仿真并写入最终结果 |
| POST | `/api/simulation/reset` | 重置到未启动状态 |
| GET | `/api/simulation/status` | 运行状态、策略、仿真时长、渲染参数 |

#### 调度

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/scheduling` | 手动触发一轮调度；body 可选 `{"strategy": "xxx"}` |
| GET | `/api/strategies` | 可用策略列表与当前策略 |
| GET | `/api/commands` | 最近一次调度产生的 Command |

#### 实体查询

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tasks` | 可见任务列表 |
| GET | `/api/tasks/{id}` | 单个任务 |
| POST | `/api/tasks` | 手动创建任务 |
| GET | `/api/vehicles` | 车辆列表 |
| GET | `/api/vehicles/{id}` | 单个车辆 |
| POST | `/api/vehicles` | 创建车辆 |
| PUT | `/api/vehicles/{id}` | 更新车辆 |
| GET | `/api/stations` | 充电站列表 |
| GET | `/api/stations/{id}` | 单个充电站 |
| POST | `/api/stations` | 创建充电站 |

#### 系统 / 地图

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/system/status` | 任务/车辆汇总统计 |
| GET | `/api/system/performance` | 性能指标 |
| GET | `/api/system/state` | 完整仿真快照（含地图节点边） |
| GET | `/api/map` | 地图数据 |
| GET | `/api/graph` | NetworkX 路网导出（Canvas 底图用） |
| GET | `/api/warehouse/position` | 仓库坐标 |
| POST | `/api/warehouse/position` | 设置仓库坐标 |
| GET | `/api/simulation/speed` | 当前仿真加速倍率 |
| POST | `/api/simulation/speed` | 设置倍率（需重启后端生效） |
| GET | `/` | API 基本信息 |
| GET | `/health` | 健康检查 |

**示例**：

```bash
# 启动仿真
curl -X POST http://localhost:8000/api/simulation/start

# 手动用 sa_score_search 调度一轮
curl -X POST http://localhost:8000/api/scheduling \
  -H "Content-Type: application/json" \
  -d '{"strategy": "sa_score_search"}'

# 查看可用策略
curl http://localhost:8000/api/strategies
```

### 6. WebSocket

连接地址：`ws://localhost:8000/ws`

主要推送消息类型：

| type | 内容 |
|------|------|
| `state_update` | 完整系统状态（每 tick 广播） |
| `task_update` | 单个任务变更 |
| `vehicle_update` | 单个车辆变更 |
| `station_update` | 充电站变更 |
| `command_update` | 调度指令 |
| `system_status` | 汇总统计 |
| `performance_metrics` | 性能指标 |
| `simulation_finished` | 仿真结束（含 stop_reason） |

客户端可发送订阅消息过滤事件类型；默认订阅 `all`。

### 7. Python 代码内直接调用

```python
from backend.data.data_manager import DataManager
from backend.algorithm.algorithm_manager import AlgorithmManager
from backend.algorithm.snapshot import Snapshot

dm = DataManager()
am = AlgorithmManager(dm.path_calculator)

snap = Snapshot.capture(dm)
commands = am.schedule("nearest_task", snap)
print(commands)
```

实际仿真中由 `DecisionManager.dynamic_scheduling()` 负责 Snapshot → Command → 状态落地。

---

## 配置说明

配置分两层：

1. **`backend/config.py`**：所有默认值与 getter 接口
2. **`configs/**/*.yaml`**：按节深合并覆盖默认值

### YAML 配置节一览

| 节名 | 作用 |
|------|------|
| `experiment` | 实验名 `name`、日志根目录 `log_dir` |
| `optimization` | `mode`: `dynamic` / `static`；静态模式下读 `static.strategy` |
| `scheduling` | 策略名、低电量阈值、充电目标、各策略专属参数 |
| `fleet` | 各车型数量、`station_count` 充电站数 |
| `vehicle` | 小/中/大型车参数（可局部覆盖） |
| `charging_station` | 默认容量、最大排队时间 |
| `task` | 初始任务数、生成间隔/批量、任务预算、种子文件 |
| `simulation` | 加速倍率、tick 间隔、任务生成截止时间、自动停止开关 |
| `routing` | OSM 地名、网络类型、是否仅主干路 |
| `scoring` | 评分公式各系数 |
| `performance_metrics` | 性能评估权重 |

### 示例：动态中规模配置

```yaml
experiment:
  name: "medium-scale-relay_handoff"
  log_dir: "log"

optimization:
  mode: "dynamic"

fleet:
  small_count:   2
  medium_count:  3
  large_count:   1
  station_count: 2

task:
  initial_tasks:               5
  generation_interval_sec_min: 5
  generation_interval_sec_max: 15
  generation_batch_min:        5
  generation_batch_max:        10
  max_pending_tasks:           20
  total_task_budget:           80
  generation_seed_file: null   # 或指向已有 seed yaml 做 replay

scheduling:
  strategy: "relay_handoff"
  relay_handoff:
    proximity_threshold_m: 1500

simulation:
  max_sim_seconds: 7200
```

### 优化模式：dynamic vs static

| 模式 | 行为 |
|------|------|
| `dynamic` | 启动时生成初始任务，运行中按间隔持续生成；调度器在线决策 |
| `static` | 启动时**预加载全部已知任务**（含未来释放时间），运行期不再生成；任务到 `create_time` 才在前端可见；仍使用同一套动态调度器执行 |

静态 yaml 中 `optimization.static` 下的 solver / gurobi 等字段为预留配置，当前版本调度执行仍走 `schedulers/` 中的动态算法。

### 任务生成与复现

- **`total_task_budget`**：累计任务数上限，达到后停止生成
- **`max_sim_seconds`**：任务生成截止时间（仿真秒）；到达后不再生成新任务，但仿真继续直到现有任务全部结算
- **`generation_seed_file`**：
  - `null`：随机种子，本次运行的任务流写入 `log/<name>/task_generation_seed.yaml`
  - 指向已有 seed 文件：replay 模式，按相同时间线注入任务，便于算法公平对比

### 环境变量速查

| 变量 | 说明 | 默认 |
|------|------|------|
| `NEFT_CONFIG_FILE` | YAML 配置路径 | 无 |
| `NEFT_STRATEGY` | 覆盖调度策略 | 见 yaml/config |
| `NEFT_EXP_NAME` | 覆盖实验名 | `default` |
| `NEFT_LOG_DIR` | 覆盖日志根目录 | `log` |
| `NEFT_SIM_SPEED` | 覆盖仿真加速倍率 | `120` |
| `NEFT_DYNAMIC_SCHEDULE_INTERVAL_SEC` | 调度触发间隔（现实秒） | `1` |
| `NEFT_MAX_STUCK_SCHED_CYCLES` | 连续无法派单多少次后自动结束 | `5` |
| `GRAPH_PLACE_NAME` | OSM 地名 | 广州番禺区 |
| `GRAPH_NETWORK_TYPE` | 路网类型 | `drive` |
| `GRAPH_MAIN_ROADS_ONLY` | 是否仅主干路 | `false` |

---

## 调度策略

所有策略注册于 `backend/algorithm/schedulers/`，通过 `scheduling.strategy` 或 API 指定。

| 策略名 | 说明 | 适用场景 |
|--------|------|---------|
| `nearest_task` | 最近任务贪心装批（基线） | 快速响应、短距离 |
| `priority_task` | 优先级 + 距离 | 紧急任务优先 |
| `heaviest_task` | 最大载重优先 | 提高载重利用率 |
| `deadline_earliest` | 最早截止时间（EDF） | 时间敏感任务 |
| `dfs_score_search` | DFS 枚举最大可行装批，取得分最高 | 待派任务较少、追求装批质量 |
| `sa_score_search` | 模拟退火搜索装批 | 任务较多时比 DFS 更快 |
| `rl_batch` | nearest 定候选池 + DFS 选批 + Q 表学习 | 在线学习装批策略 |
| `regional_planning` | K-means 分包裹 + 多车认领 | 大规模、区域化派单 |
| `cluster_auction_mas` | 聚类包裹 + 顺序拍卖多智能体 | 多车竞争、协同分配 |
| `relay_handoff` | 路网上近距离车辆协商交换货物 | 多车协同、接力配送 |

**统一电量安全网**（`algorithm/utils.py`）：

- 低于 `low_battery_pct` 主动充电
- 路径电量预判：若剩余电量不足以完成"下一站 → 其余未送 → 回仓"，自动改派最优充电站（综合距离 + 负荷 + 排队）

不论选择哪种策略，车辆通常不会因电量耗尽抛锚（除非完全没有可用充电站）。

切换策略示例：

```yaml
scheduling:
  strategy: "sa_score_search"
  sa:
    iterations: 1500
    t_start: 1000.0
    seed: 42
```

或运行时临时覆盖：

```bash
curl -X POST http://localhost:8000/api/scheduling \
  -H "Content-Type: application/json" \
  -d '{"strategy": "regional_planning"}'
```

---

## 仿真生命周期与终止

1. **启动** `POST /api/simulation/start`（或 Headless 自动开始）
   - 初始化仓库、车队、充电站、初始任务
   - 创建 `log/<experiment.name>/`，写入 `config.yaml`
2. **运行** 主循环每 `tick_interval` 现实秒推进 `speed_factor` 仿真秒
   - 车辆移动 / 充电
   - 任务生成器按配置注入新任务
   - 每 `NEFT_DYNAMIC_SCHEDULE_INTERVAL_SEC` 秒触发调度
3. **终止**（任一触发即停）
   - 手动 `POST /api/simulation/stop` → `stop_reason=manual_stop`
   - 重置 `POST /api/simulation/reset` → `stop_reason=reset`
   - 任务生成已停且全部任务 COMPLETED/TIMEOUT → `all_tasks_done`
   - 任务生成已停、全车回仓空闲、连续多轮无法派单 → `no_feasible_tasks_left`

---

## 实验日志

每次 `simulation/start` 写入目录：

```
log/<experiment.name>/
├── config.yaml              # 本次完整配置快照
├── task_generation_seed.yaml # 任务生成种子流（record 或 replay 来源）
└── log.txt                  # 人类可读事件日志 + 最终量化指标
```

`log.txt` 末尾包含：完成率、按时率、总分、吞吐、里程、能耗、车队均衡度等；完整结构化结果以 YAML 块追加在文件末尾。

---

## 评分机制

任务最终得分与装批估分共用 `backend/algorithm/scoring_config.py`：

```
任务得分 = 120                          # 基础分配奖励
         + 30 × priority               # 优先级奖励
         - 0.02 × 往返距离(米)         # 距离惩罚
         + 2.0 × 提前完成分钟数        # 提前奖励
         - 50 × 逾期分钟数             # 逾期惩罚
```

可在 yaml 的 `scoring` 节或 `config.py` 的 `_DEFAULT_SCORING` 中调整系数。

---

## 项目结构

```
NEFT-System/
├── backend/
│   ├── main.py                 # 服务入口、仿真主循环、Headless 模式
│   ├── config.py               # 全局配置 + YAML 加载
│   ├── experiment_logger.py    # 实验日志
│   ├── algorithm/
│   │   ├── snapshot.py         # 算法输入 Snapshot
│   │   ├── scheduler.py        # Command / Scheduler 基类
│   │   ├── algorithm_manager.py# 策略注册与分发
│   │   ├── scoring_config.py   # 统一评分
│   │   ├── utils.py            # 度量、指令构造、电量决策模板
│   │   └── schedulers/         # 各调度策略实现
│   ├── data/                   # 任务、车辆、充电站、路网、路径计算
│   ├── decision/               # DecisionManager、DynamicSchedulingModule
│   ├── interface/              # REST API、WebSocket、Schema
│   └── requirements.txt
├── configs/
│   ├── dynamic/                # 小/中/大规模动态配置
│   └── static/                 # 静态上帝视角配置
├── frontend/                   # Web 可视化
├── log/                        # 运行时实验日志（自动生成）
├── data/                       # RL 策略等运行时数据
├── test/                       # pytest 测试
└── README.md
```

---

## 扩展：编写新调度算法

### 1. 新建 Scheduler

在 `backend/algorithm/schedulers/` 下创建文件，继承 `Scheduler`：

```python
from typing import List
from ..scheduler import Command, Scheduler
from ..snapshot import Snapshot
from ..utils import decide_at_warehouse, decide_en_route


class MyScheduler(Scheduler):
    name = "my_strategy"

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        commands: List[Command] = []

        def pick_tasks(v, available):
            # 自定义选任务逻辑
            return available[:1] if available else []

        for v in snapshot.vehicles_need_decision():
            if v.position.to_tuple() == snapshot.warehouse_xy:
                commands.append(decide_at_warehouse(v, snapshot, pick_tasks))
            else:
                commands.append(decide_en_route(v, snapshot))
        return commands
```

### 2. 注册

在 `backend/algorithm/schedulers/dynamic/__init__.py` 的 `DYNAMIC_SCHEDULERS` 列表中加入新类。

### 3. 启用

```yaml
scheduling:
  strategy: "my_strategy"
```

重启后端，或通过 `POST /api/scheduling` 临时指定。

### 核心数据类

**Snapshot** 常用方法：

| 方法 | 说明 |
|------|------|
| `vehicles_need_decision()` | 需要新指令的车辆 |
| `idle_vehicles_at_warehouse()` | 仓库空闲可装货车 |
| `available_tasks()` | PENDING 任务 |
| `distance(a_xy, b_xy)` | 路网最短距离（米） |

**Command** 动作类型：`deliver` / `charge` / `return` / `idle` / `handoff` / `goto_node`

推荐使用 `utils.make_*_command` 构造，无需手写 Command 字段。

---

## 测试

```bash
cd test
pytest -v
```

运行单个测试文件：

```bash
pytest test_dynamic_scheduling.py -v
pytest test_api.py -v
pytest test_config.py -v
```

---

## 技术栈

| 层次 | 技术 |
|------|------|
| Web 框架 | FastAPI + Uvicorn |
| 实时通信 | WebSocket |
| 图算法 | NetworkX、OSMnx |
| 前端 | 原生 JavaScript、高德地图 API、Chart.js |
| 配置 | PyYAML |
| 测试 | pytest |

---

## 常见问题

**Q: 改了 yaml 但策略没变？**  
A: 必须重启后端进程；yaml 在 import 时一次性加载。

**Q: 前端连不上后端？**  
A: 确认后端已启动且 `frontend/script.js` 中 `API_BASE` / `WS_URL` 指向 `localhost:8000`。

**Q: 如何让两次实验任务完全相同？**  
A: 第一次 run 后复制 `log/<name>/task_generation_seed.yaml`，在 yaml 中设置 `task.generation_seed_file` 指向该文件再跑。

**Q: `max_sim_seconds` 到了为什么还在跑？**  
A: 该字段表示**任务生成截止时间**，不是仿真总时长。生成停止后仿真会继续直到所有任务结算。

---

## 贡献与许可

欢迎提交 Issue 和 Pull Request。本项目采用 MIT 许可证，详见 [LICENSE](LICENSE)。

## 致谢

- [FastAPI](https://fastapi.tiangolo.com/)
- [OSMnx](https://osmnx.readthedocs.io/)
- [NetworkX](https://networkx.org/)
- [高德地图](https://lbs.amap.com/)

---

**NEFT — 让新能源物流调度可仿真、可对比、可扩展。**
