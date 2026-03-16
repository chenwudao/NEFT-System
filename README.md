# 新能源物流车队协同调度系统 (NEFT System)

## 项目简介

新能源物流车队协同调度系统是一个基于 FastAPI 和 WebSocket 的车辆调度算法仿真可视化平台。系统实现了车辆、任务、充电站的协同调度，支持多种调度策略，并提供实时可视化界面。

## 项目结构

```
1NEFT(Updating)/
├── backend/              # 后端服务
│   ├── algorithm/        # 调度算法模块
│   ├── data/            # 数据模型和管理
│   ├── decision/        # 决策管理模块
│   ├── interface/       # API 接口和 WebSocket 处理
│   ├── config.py        # 配置文件
│   ├── main.py          # 主程序入口
│   └── requirements.txt # 后端依赖
├── frontend/            # 前端界面
│   ├── index.html       # 主页面
│   ├── script.js        # 前端逻辑
│   └── style.css        # 样式文件
└── test/                # 测试文件
```

## 快速开始

### 1. 环境要求

- Python 3.8+
- pip (Python 包管理器)
- 现代浏览器 (Chrome, Firefox, Edge 等)

### 2. 安装依赖

#### 安装后端依赖

```bash
cd backend
pip install -r requirements.txt
cd ..
```

#### 安装测试依赖 (可选)

```bash
cd test
pip install -r requirements.txt
cd ..
```

### 3. 启动后端服务

在项目根目录执行以下命令启动后端服务：

```bash
python backend/main.py
```

后端服务启动后，您将看到以下输出：

```
INFO:     Started server process
INFO:     Waiting for application startup.
Starting NEFT System...
Initializing test data...
Test data initialized successfully
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 4. 打开前端页面

后端服务启动成功后，在浏览器中打开前端页面：

**方式一：直接打开 HTML 文件**

在浏览器中打开 `frontend/index.html` 文件：
- Windows: 双击 `frontend/index.html` 文件
- 或在浏览器地址栏输入：`file:///d:/Environment/homework/DaStProj/1NEFT(Updating)/frontend/index.html`

**方式二：使用本地服务器 (推荐)**

如果您安装了 Python，可以使用以下命令启动简单的 HTTP 服务器：

```bash
cd frontend
python -m http.server 8080
```

然后在浏览器中访问：`http://localhost:8080`

### 5. 使用系统

1. 在前端页面点击 **"启动模拟"** 按钮连接到后端服务
2. 系统会自动生成任务并开始仿真
3. 使用 **"慢速"、"正常"、"快速"** 按钮调整仿真速度
4. 点击 **"停止模拟"** 按钮断开连接

## 功能特性

### 后端功能

- **任务管理**: 自动生成随机任务，支持任务分配和调度
- **车辆管理**: 管理车辆状态、电量、载重等信息
- **充电站管理**: 管理充电站容量、排队情况
- **调度算法**: 支持多种调度策略 (遗传算法、最短任务优先等)
- **WebSocket 通信**: 实时推送仿真状态更新
- **RESTful API**: 提供完整的 API 接口

### 前端功能

- **实时可视化**: 使用 Canvas 绘制地图、车辆、任务、充电站
- **状态监控**: 实时显示车辆、任务、充电站状态
- **核心指标**: 显示时间戳、总得分、任务完成率、车辆利用率
- **交互控制**: 支持启动/停止仿真、调整仿真速度

## API 文档

后端服务启动后，可以通过以下地址访问 API 文档：

- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc

### 主要 API 端点

- `GET /` - 系统信息
- `GET /health` - 健康检查
- `GET /api/tasks` - 获取所有任务
- `GET /api/tasks/{task_id}` - 获取单个任务
- `GET /api/vehicles` - 获取所有车辆
- `GET /api/vehicles/{vehicle_id}` - 获取单个车辆
- `GET /api/stations` - 获取所有充电站
- `GET /api/stations/{station_id}` - 获取单个充电站
- `GET /api/map` - 获取地图数据
- `GET /api/system/status` - 获取系统状态
- `GET /api/performance/metrics` - 获取性能指标
- `WebSocket /ws` - 实时数据推送

## WebSocket 连接

前端通过 WebSocket 连接到后端服务：

```
ws://127.0.0.1:8000/ws
```

WebSocket 消息格式：

```json
{
  "status": "success",
  "data": {
    "timestamp": 1234567890,
    "total_score": 100.5,
    "tasks": [...],
    "vehicles": [...],
    "stations": [...],
    "map_nodes": [...],
    "map_edges": [...],
    "warehouse_pos": {"x": 0, "y": 0}
  }
}
```

## 配置说明

系统配置文件位于 `backend/config.py`，主要配置项包括：

- **车辆配置**: 最大电量、最大载重、单位能耗
- **充电站配置**: 默认容量、充电速率
- **任务配置**: 最小/最大重量、优先级范围
- **调度配置**: 调度策略、时间间隔

详细的配置说明请参考 `backend/PARAMETER_GUIDE.md`。

## 测试

运行测试套件：

```bash
cd test
pytest
```

运行特定测试：

```bash
pytest test_api.py
pytest test_data_manager.py
pytest test_decision_manager.py
pytest test_path_calculator.py
```

## 故障排除

### 问题 1: 后端服务无法启动

**解决方案**:
- 确认已安装所有依赖: `pip install -r backend/requirements.txt`
- 检查端口 8000 是否被占用
- 查看错误日志，根据错误信息调整配置

### 问题 2: 前端无法连接到后端

**解决方案**:
- 确认后端服务已启动并运行在 http://127.0.0.1:8000
- 检查浏览器控制台是否有 WebSocket 连接错误
- 确认防火墙未阻止本地连接

### 问题 3: 页面显示异常

**解决方案**:
- 确认浏览器支持 Canvas API
- 清除浏览器缓存并刷新页面
- 检查浏览器控制台是否有 JavaScript 错误

## 技术栈

### 后端
- FastAPI - Web 框架
- Uvicorn - ASGI 服务器
- WebSocket - 实时通信
- Pydantic - 数据验证

### 前端
- HTML5 - 页面结构
- CSS3 - 样式设计
- JavaScript - 交互逻辑
- Canvas API - 图形绘制

### 算法
- 遗传算法 (Genetic Algorithm)
- 最短任务优先 (Shortest Task First)
- 最重任务优先 (Heaviest Task First)
- 聚类算法 (Clustering Algorithm)
- 混合整数规划 (MIP Solver)

## 开发指南

### 前端开发

前端代码位于 `frontend/` 目录：

- `index.html` - 页面结构
- `script.js` - 业务逻辑和 WebSocket 通信
- `style.css` - 样式定义

详细的开发指南请参考 `frontend/FRONTEND_ADJUSTMENT.md`。

### 后端开发

后端代码采用模块化设计：

- `algorithm/` - 调度算法实现
- `data/` - 数据模型定义
- `decision/` - 决策逻辑
- `interface/` - API 和 WebSocket 处理

## 许可证

本项目为学术研究项目，仅供学习和研究使用。

## 联系方式

如有问题或建议，请联系项目维护者。

---

**注意**: 本系统为仿真演示系统，实际应用中需要根据具体需求进行调整和优化。
