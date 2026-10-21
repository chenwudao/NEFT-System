# NEFT - 新能源物流车队协同调度系统

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109.0-009688.svg)](https://fastapi.tiangolo.com/)
![License](https://img.shields.io/badge/license-MIT-green.svg)

面向新能源物流车队的协同调度仿真系统。车辆在 OpenStreetMap 路网上配送动态出现的任务，同时受电量、载重和充电站排队约束。系统提供多种在线调度策略，以及任务全集已知时的静态精确求解，并用 Web 地图实时展示。

## 项目简介

NEFT（New Energy Fleet Transportation）模拟中央仓库管理一支新能源车队的场景。任务在仿真过程中持续产生，调度器为每辆需要决策的车辆选择下一步：配送、充电、回仓、交接或待命。路径由路网最短路计算，算法只决定去哪里。

动态模式按时间接收新任务。静态模式在仿真开始时已知全部任务，先生成全局计划再按计划执行，便于和在线策略对比。

## 核心特性

- **多车型**：小型、中型、大型车辆具有不同的电量、载重、能耗、速度和充电功率。
- **路网图**：基于 OpenStreetMap 构建道路网络，用最短路计算行驶距离。
- **充电调度**：电量不足或后续行程不可达时，按距离、负荷和排队选择充电站。
- **多种动态策略**：贪心、评分搜索、元启发式、强化学习、超启发式与多智能体方法，共 15 种。
- **静态全局优化**：`static_exact_solver` 用 Gurobi 做全局求解；求解器不可用时回退到内置搜索。
- **实时可视化**：FastAPI 与 WebSocket 推送状态，前端用高德地图展示。
- **统一评分**：任务完成得分使用同一套奖励与惩罚，便于横向比较策略。

一次仿真使用配置或启动请求中指定的策略。

## 系统架构

```
前端层
  Web 界面（HTML / CSS / JavaScript）
  高德地图、WebSocket 状态更新
        │  REST / WebSocket
接口层
  FastAPI、仿真控制与查询接口
        │
调度决策层
  动态调度主循环
  静态模式下的一次性全局规划
        │
算法层
  Scheduler：Snapshot → Command 列表
  15 种动态策略 + static_exact_solver
        │
数据层
  任务、车辆、充电站、路网最短路
```

## 快速开始

### 环境要求

- Python 3.12+
- Conda（推荐）或 pip
- 高德地图 API Key（仅地图展示需要）
- PyYAML（读取 `configs/` 时需要）
- 静态求解可选安装 Gurobi

### 安装与启动

1. 克隆仓库

```bash
git clone https://github.com/chenwudao/NEFT-System.git
cd NEFT-System
```

2. 创建环境并安装依赖

```bash
conda create -n neft python=3.12 -y
conda activate neft
pip install -r backend/requirements.txt
pip install pyyaml
```

3. 配置高德地图 Key

在 `frontend/index.html` 中替换 Key：

```html
<script src="https://webapi.amap.com/maps?v=2.0&key=YOUR_AMAP_KEY"></script>
```

4. 启动后端

在仓库根目录执行：

```bash
python backend/main.py --cfg configs/dynamic/small.yaml
```

服务监听 `http://localhost:8000`。不传 `--cfg` 时使用 `backend/config.py` 中的默认值。

5. 打开前端

用浏览器直接打开 `frontend/index.html`，或通过本地静态服务器访问。

## 使用指南

### 启动模拟

1. 打开 Web 界面。
2. 在控制面板中选择：
   - **规模**：`small`、`medium`、`large`。后端会加载 `configs/dynamic/{scale}.yaml`。
   - **策略**：下拉列表来自 `GET /api/config/options`，对应下方 15 种动态策略。
3. 点击 **启动模拟**。请求体中的 `scale` 与 `strategy` 会在本次运行开始前生效。

静态对比请使用 `configs/static/` 下的配置，并将 `optimization.mode` 设为 `static`。静态策略默认为 `static_exact_solver`，不在动态策略下拉列表中。

### 调度策略

| 策略名 | 说明 |
| --- | --- |
| `nearest_task` | 按距离贪心组批，用作基线 |
| `priority_task` | 优先级优先，同优先级再看距离 |
| `heaviest_task` | 按货物重量从大到小装车 |
| `deadline_earliest` | 最早截止时间优先 |
| `composite_score` | 综合优先级、紧迫度、载重与距离后搜索 |
| `dfs_score_search` | 在可行任务子集上做 DFS 评分搜索 |
| `insertion_heuristic` | 按后悔值插入任务，并做轻量局部优化 |
| `simulated_annealing` | 模拟退火，用于批量重排 |
| `tabu_search` | 禁忌搜索 |
| `q_learning` | 在线表格型 Q-learning |
| `hyper_heuristic_eps` | 在基础启发式算子之间做 ε-greedy 选择 |
| `relay_handoff` | 车辆之间接力交接货物 |
| `region_partition` | 按任务区域划分车辆责任范围 |
| `multi_agent_auction` | 多车拍卖分配 |
| `multi_agent_contract_net` | 合同网协议分配 |
| `static_exact_solver` | 静态模式全局求解（优先 Gurobi，不可用时回退内置搜索） |

名称也接受类名、去掉 `Scheduler` 后缀的类名，以及大小写或连字符变体，例如 `DeadlineEarliest`、`DEADLINE-EARLIEST`。无法识别时回退到 `nearest_task`。

仓库内与途中的通用决策由 `backend/algorithm/utils.py` 的 `decide_at_warehouse` 和 `decide_en_route` 承担，包括：

- 电量低于 `low_battery_pct`（百分数，代码默认 20）时先去充电；
- 去下一目标后若无法再到达充电站，则改为充电；
- 充电站按距离、负荷压力和排队长度综合选择。

没有可用充电站时，车辆仍可能因电量耗尽而抛锚。该结果会记入实验日志。

### 监控面板

- **任务**：待处理、进行中、已完成、超时
- **车辆**：位置、电量、载重、状态
- **充电站**：桩位占用与排队
- **指标**：得分、完成率、车辆利用率

### 主要接口

```bash
# 策略与规模选项，以及当前生效值
GET /api/config/options

# 启动仿真。示例：{ "scale": "medium", "strategy": "relay_handoff" }
POST /api/simulation/start

POST /api/simulation/stop
POST /api/simulation/reset
GET  /api/simulation/status

# 当前仿真状态、任务与车辆
GET /api/system/state
GET /api/tasks
GET /api/vehicles

# 已注册策略；手动触发一轮调度（body 可带 strategy）
GET  /api/strategies
POST /api/scheduling
```

实时状态通过 WebSocket `/ws` 推送。

## 测试

```bash
cd test
pytest -v
```

## 评分机制

任务完成得分由 `backend/algorithm/scoring_config.py` 统一计算。未在 YAML 中覆盖时，默认公式为：

```
得分 = 120
     + 30 × priority
     - 0.02 × 实际路径距离（米）
     + 2 × 提前完成分钟数
     - 50 × 逾期分钟数
```

结果低于 0 时记为 0。能耗不进入该公式，单独记录在实验日志中。

## 技术栈

### 后端

- **FastAPI / WebSocket**：服务与实时推送
- **NetworkX / OSMnx**：路网与最短路
- **Gurobi**（可选）：静态 MIP。`solver: cplex` 目前只探测依赖，不会建模求解
- **PyYAML**：外部配置

### 前端

- 原生 HTML / CSS / JavaScript
- 高德地图 API

### 算法

- 动态调度：启发式、元启发式、强化学习、超启发式、多智能体
- 静态规划：Gurobi 求解带时间窗的车辆路径模型；不可用时使用内置搜索
- 路径：Dijkstra 最短路

## 项目结构

```
NEFT-System/
├── backend/
│   ├── main.py                 # 服务入口与仿真主循环
│   ├── config.py               # 默认配置，可被 YAML 覆盖
│   ├── experiment_logger.py    # 实验日志
│   ├── algorithm/              # Snapshot、Command、策略实现
│   ├── data/                   # 任务、车辆、充电站、路网
│   ├── decision/               # 调度执行
│   └── interface/              # REST 与 WebSocket
├── configs/
│   ├── dynamic/                # small、medium、large
│   └── static/
├── frontend/                   # index.html、script.js、style.css
├── docs/                       # 架构与策略说明
├── test/
└── README.md
```

## 配置说明

未出现在 YAML 中的字段沿用 `backend/config.py`。相对路径相对于仓库根目录。加载 YAML 需要已安装 PyYAML。

### 选择规模与策略

推荐在界面或启动请求里指定。`scale` 只接受 `small`、`medium`、`large`，并重新加载 `configs/dynamic/{scale}.yaml`。请求中的 `strategy` 在规模加载之后生效，因此会覆盖该 YAML 里的策略名。

```json
{
  "scale": "medium",
  "strategy": "relay_handoff"
}
```

也可以在启动进程时指定默认配置：

```bash
python backend/main.py --cfg configs/dynamic/medium.yaml
```

```bash
# Bash
NEFT_CONFIG_FILE=configs/dynamic/medium.yaml python backend/main.py
```

```powershell
# PowerShell
$env:NEFT_CONFIG_FILE = "configs\dynamic\medium.yaml"; python backend\main.py
```

`--cfg` 与 `--config` 等价。静态实验将 `--cfg` 指向 `configs/static/` 下的文件。

### 实验日志

每次 `POST /api/simulation/start` 使用 YAML 中的 `experiment.name` 建立目录：

```
log/<experiment.name>/
├── config.yaml    # 本次配置快照
└── log.txt        # 带时间戳的事件与结束指标
```

同名实验会复用该目录，并覆盖上一次的 `config.yaml` 与 `log.txt`。`experiment.log_dir` 可改日志根目录，默认是 `log`。

仿真结束的常见原因：

- `manual_stop`：调用 `/api/simulation/stop`
- `reset`：运行中调用 `/api/simulation/reset`
- `all_tasks_done`：任务生成已经停止，且现存任务均为完成或超时（需要 `stop_when_all_tasks_done: true`）
- `no_feasible_tasks_left`：连续多轮无法继续派单

`max_sim_seconds` 是任务生成截止时间（仿真秒）。到达后不再产生新任务，仿真继续，直到现存任务进入完成或超时。`total_task_budget` 同样只停止生成：累计任务数达到预算后不再新增任务。

`log.txt` 末尾的指标包括：

- **任务**：总数、完成、按时、超时、待派，以及完成率、按时率、超时率
- **得分**：总分、每任务平均、按时任务平均
- **时效**：平均完成时长、平均超时分钟、吞吐（任务/小时）
- **距离与能耗**：车队总里程、任务腿均长、里程标准差、总能耗、单任务能耗
- **车队**：抛锚数量、抛锚车辆 ID、每车完成任务数

### 环境变量

环境变量先写入代码默认值。若 YAML 包含同一字段，以 YAML 为准。仿真启动请求里的 `strategy` 最后生效。

| 变量 | 作用 | 未设置时 |
| --- | --- | --- |
| `NEFT_CONFIG_FILE` | YAML 路径（相对仓库根目录或绝对路径） | 不加载 YAML |
| `NEFT_STRATEGY` | 默认调度策略 | `nearest_task` |
| `NEFT_EXP_NAME` | 默认实验名 | `default` |
| `NEFT_LOG_DIR` | 默认日志根目录 | `log` |
| `NEFT_SIM_SPEED` | 默认仿真加速倍率 | `120` |
| `NEFT_DYNAMIC_SCHEDULE_INTERVAL_SEC` | 动态调度间隔（现实秒） | `1` |

### 车辆默认参数

可在 `backend/config.py` 或 YAML 的 `vehicle` 段修改。下表是代码默认值；能耗系数乘以行驶距离（米）后得到能耗（kWh），速度单位为米/秒。

| 车型 | 电量 (kWh) | 载重 (kg) | 能耗系数 | 速度 (m/s) |
| --- | ---: | ---: | ---: | ---: |
| small | 60 | 500 | 0.00025 | 10 |
| medium | 100 | 1500 | 0.0003 | 10 |
| large | 150 | 5000 | 0.0004 | 8 |

## 算法接口

新增动态策略时，实现一个 `Scheduler`：输入只读 `Snapshot`，输出若干 `Command`。每个 `Command` 只描述一辆车的下一步目标；到达后再调度。未出现在列表中的车辆保持原状态。车辆沿 Dijkstra 最短路移动。

主要约定：

- 车辆从中心仓库出发；常规装货在仓库完成。`relay_handoff` 可以在途中交接货物。
- 到达任务点后，该任务记为完成。
- 策略名由配置或启动参数指定。

### 目录

```
backend/algorithm/
├── snapshot.py
├── scheduler.py              # Scheduler、Command
├── utils.py
├── algorithm_manager.py      # 按名称分发
├── scoring_config.py
└── schedulers/
    ├── __init__.py           # EXPORTED_SCHEDULERS
    ├── dynamic/__init__.py   # 动态策略注册表
    ├── static/static_exact_solver.py
    └── *.py                  # 各动态策略实现
```

### Snapshot 与 Command

`Snapshot` 包含车辆、任务、充电站、仓库坐标、时间戳和路径查询。常用方法：

| 方法 | 含义 |
| --- | --- |
| `vehicles_need_decision()` | 空闲且没有目标、等待新指令的车 |
| `idle_vehicles_at_warehouse()` | 停在仓库、可以接单的车 |
| `idle_vehicles_not_at_warehouse()` | 停在仓库外、等待下一步的车 |
| `available_tasks()` | 已到释放时间的 `PENDING` 任务 |
| `distance(a, b)` | 路网距离（米）；不可达为 `+inf` |
| `path(a, b)` | 最短路节点序列；不可达为空列表 |

`Command.action` 取值为 `deliver`、`goto_node`、`charge`、`return`、`handoff`、`idle`。业务代码优先使用 `utils.py` 中的 `make_*_command`，避免手写字段。

### 常用工具

| 函数 | 用途 |
| --- | --- |
| `feasible_tasks_for(vehicle, tasks)` | 按剩余载重筛选任务 |
| `nearest_task(vehicle, tasks, snapshot)` | 最近且装得下的任务 |
| `best_charging_station(vehicle, snapshot)` | 综合距离、负荷与排队 |
| `greedy_chain(start_xy, points, snapshot)` | 贪心访问顺序 |
| `mst_order(start_xy, points, snapshot)` | 最小生成树 DFS 顺序 |
| `decide_at_warehouse(vehicle, snapshot, pick_tasks)` | 在仓：充电、接单或待命 |
| `decide_en_route(vehicle, snapshot)` | 在途：继续配送、充电或回仓 |

`pick_tasks(vehicle, tasks, snapshot)` 返回本趟要携带的任务列表。多数单车策略只需替换这个函数。

多车分配、批量拼单或接力交接可以直接在 `schedule()` 中读取 `snapshot`，再用 `make_deliver_command`、`make_goto_node_command` 或 `make_handoff_command` 下发。向正在行驶的车辆发送新命令会覆盖其当前路径。

### 新增一种策略

1. 在 `backend/algorithm/schedulers/` 新增文件：

```python
from typing import List

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.snapshot import Snapshot


class HeaviestFirstScheduler(Scheduler):
    """按重量降序挑选一件当前装得下的任务。"""

    name = "heaviest_first"

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        commands: List[Command] = []

        for vehicle in snapshot.idle_vehicles_not_at_warehouse():
            commands.append(utils.decide_en_route(vehicle, snapshot))

        def pick_tasks(vehicle, tasks, snap):
            candidates = utils.feasible_tasks_for(vehicle, tasks)
            if not candidates:
                return []
            candidates.sort(
                key=lambda task: (
                    -task.weight,
                    snap.distance(vehicle.position, task.position),
                )
            )
            return [candidates[0]]

        for vehicle in snapshot.idle_vehicles_at_warehouse():
            commands.append(
                utils.decide_at_warehouse(vehicle, snapshot, pick_tasks)
            )
        return commands
```

2. 在 `backend/algorithm/schedulers/dynamic/__init__.py` 中导入该类，并加入 `DYNAMIC_SCHEDULERS`。`EXPORTED_SCHEDULERS` 会在启动时自动注册。

3. 将 YAML 的 `scheduling.strategy` 设为 `heaviest_first`，或在启动请求里传入同名 `strategy`。

### 调用入口

- 主循环按 `NEFT_DYNAMIC_SCHEDULE_INTERVAL_SEC` 调用动态调度，策略读取当前配置。
- `POST /api/scheduling` 可在 body 中用 `strategy` 覆盖一轮；省略则沿用配置。
- `GET /api/strategies` 返回已注册名称。
- 脚本或测试中可以直接调用：

```python
from backend.algorithm import AlgorithmManager, Snapshot

snap = Snapshot.capture(data_manager)
manager = AlgorithmManager(data_manager.path_calculator)
commands = manager.schedule("nearest_task", snap)
```

## 贡献

欢迎提交 Issue 和 Pull Request。

1. Fork 本仓库。
2. 创建特性分支：`git checkout -b feature/your-feature`。
3. 提交修改并推送到该分支。
4. 打开 Pull Request。

## 许可证

本项目采用 MIT 许可证。

## 致谢

- [FastAPI](https://fastapi.tiangolo.com/)
- [OSMnx](https://osmnx.readthedocs.io/)
- [NetworkX](https://networkx.org/)
- [高德地图](https://lbs.amap.com/)
- [Gurobi](https://www.gurobi.com/)（可选求解器）

## 联系

- [GitHub Issues](https://github.com/chenwudao/NEFT-System/issues)
