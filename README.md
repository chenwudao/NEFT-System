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
