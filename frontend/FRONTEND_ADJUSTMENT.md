# 前端调整说明文档

## 概述

本文档基于后端 `backend/interface` 层的实际代码编写，说明如何调整前端以适配后端API接口。后端采用FastAPI框架，提供RESTful API和WebSocket实时通信两种方式与前端交互。

**后端接口层文件结构**：
- `api_controller.py` - RESTful API 控制器
- `schemas.py` - 数据模型定义
- `websocket_handler.py` - WebSocket 处理器
- `data_transformer.py` - 数据转换器

---

## API接口说明

### 1. 任务管理接口

#### 获取所有任务
- **接口**: `GET /api/tasks`
- **响应模型**: `List[TaskModel]`
- **返回格式**:
```json
[
  {
    "id": 1,
    "position": {"x": 200.0, "y": 200.0},
    "weight": 30.0,
    "create_time": 1678888888,
    "deadline": 1678892488,
    "priority": 1,
    "status": "pending",
    "assigned_vehicle_id": null,
    "start_time": null,
    "complete_time": null
  }
]
```

#### 获取单个任务
- **接口**: `GET /api/tasks/{task_id}`
- **响应模型**: `TaskModel`
- **错误响应**: 404 - "Task not found"
- **返回格式**:
```json
{
  "id": 1,
  "position": {"x": 200.0, "y": 200.0},
  "weight": 30.0,
  "create_time": 1678888888,
  "deadline": 1678892488,
  "priority": 1,
  "status": "pending",
  "assigned_vehicle_id": null,
  "start_time": null,
  "complete_time": null
}
```

#### 创建任务
- **接口**: `POST /api/tasks`
- **请求模型**: `CreateTaskRequest`
- **响应模型**: `TaskModel`
- **请求格式**:
```json
{
  "position": {"x": 200.0, "y": 200.0},
  "weight": 30.0,
  "deadline": 1678892488,
  "priority": 1
}
```

**CreateTaskRequest 字段说明**：
| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| position | PositionModel | 是 | - | 任务位置 |
| weight | float | 是 | - | 任务重量 |
| deadline | int | 是 | - | 截止时间戳 |
| priority | int | 否 | 1 | 优先级 |

---

### 2. 车辆管理接口

#### 获取所有车辆
- **接口**: `GET /api/vehicles`
- **响应模型**: `List[VehicleModel]`
- **返回格式**:
```json
[
  {
    "id": 1,
    "position": {"x": 150.0, "y": 150.0},
    "battery": 80.0,
    "max_battery": 100.0,
    "battery_percentage": 80.0,
    "current_load": 0.0,
    "max_load": 100.0,
    "load_percentage": 0.0,
    "unit_energy_consumption": 0.1,
    "status": "idle",
    "assigned_task_ids": [],
    "current_path": [],
    "charging_station_id": null
  }
]
```

#### 获取单个车辆
- **接口**: `GET /api/vehicles/{vehicle_id}`
- **响应模型**: `VehicleModel`
- **错误响应**: 404 - "Vehicle not found"
- **返回格式**: 同上单个车辆对象

#### 创建车辆
- **接口**: `POST /api/vehicles`
- **请求模型**: `CreateVehicleRequest`
- **响应模型**: `VehicleModel`
- **请求格式**:
```json
{
  "position": {"x": 150.0, "y": 150.0},
  "battery": 80.0,
  "max_battery": 100.0,
  "current_load": 0.0,
  "max_load": 100.0,
  "unit_energy_consumption": 0.1
}
```

**CreateVehicleRequest 字段说明**：
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| position | PositionModel | 是 | 车辆位置 |
| battery | float | 是 | 当前电量 |
| max_battery | float | 是 | 最大电量 |
| current_load | float | 是 | 当前载重 |
| max_load | float | 是 | 最大载重 |
| unit_energy_consumption | float | 是 | 单位能耗 |

#### 更新车辆
- **接口**: `PUT /api/vehicles/{vehicle_id}`
- **请求模型**: `UpdateVehicleRequest`
- **响应模型**: `VehicleModel`
- **错误响应**: 404 - "Vehicle not found"
- **请求格式**:
```json
{
  "position": {"x": 160.0, "y": 160.0},
  "battery": 75.0,
  "current_load": 20.0,
  "status": "transporting"
}
```

**UpdateVehicleRequest 字段说明**（所有字段可选）：
| 字段 | 类型 | 说明 |
|------|------|------|
| position | PositionModel | 新位置 |
| battery | float | 新电量 |
| current_load | float | 新载重 |
| status | string | 新状态 (idle/transporting/charging) |

---

### 3. 充电站管理接口

#### 获取所有充电站
- **接口**: `GET /api/stations`
- **响应模型**: `List[ChargingStationModel]`
- **返回格式**:
```json
[
  {
    "id": "cs1",
    "position": {"x": 250.0, "y": 150.0},
    "capacity": 5,
    "queue_count": 0,
    "charging_vehicles": [],
    "load_pressure": 0.0,
    "charging_rate": 10.0,
    "available_capacity": 5
  }
]
```

#### 获取单个充电站
- **接口**: `GET /api/stations/{station_id}`
- **响应模型**: `ChargingStationModel`
- **错误响应**: 404 - "Charging station not found"
- **返回格式**: 同上单个充电站对象

#### 创建充电站
- **接口**: `POST /api/stations`
- **请求模型**: `CreateChargingStationRequest`
- **响应模型**: `ChargingStationModel`
- **请求格式**:
```json
{
  "id": "cs1",
  "position": {"x": 250.0, "y": 150.0},
  "capacity": 5,
  "charging_rate": 10.0
}
```

**CreateChargingStationRequest 字段说明**：
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | string | 是 | 充电站ID |
| position | PositionModel | 是 | 充电站位置 |
| capacity | int | 是 | 充电容量 |
| charging_rate | float | 是 | 充电速率 |

---

### 4. 地图数据接口

#### 获取地图数据
- **接口**: `GET /api/map`
- **返回格式**:
```json
{
  "task_positions": [...],
  "vehicle_positions": [...],
  "station_positions": [...]
}
```

---

### 5. 系统状态接口

#### 获取系统状态
- **接口**: `GET /api/system/status`
- **响应模型**: `SystemStatusResponse`
- **返回格式**:
```json
{
  "timestamp": 1678888888,
  "total_tasks": 10,
  "pending_tasks": 5,
  "completed_tasks": 4,
  "timeout_tasks": 1,
  "total_vehicles": 3,
  "idle_vehicles": 1,
  "transporting_vehicles": 2,
  "charging_vehicles": 0,
  "total_charging_stations": 2,
  "active_commands": 2,
  "current_strategy": "shortest_task_first"
}
```

**SystemStatusResponse 字段说明**：
| 字段 | 类型 | 说明 |
|------|------|------|
| timestamp | int | 时间戳 |
| total_tasks | int | 总任务数 |
| pending_tasks | int | 待处理任务数 |
| completed_tasks | int | 已完成任务数 |
| timeout_tasks | int | 超时任务数 |
| total_vehicles | int | 总车辆数 |
| idle_vehicles | int | 空闲车辆数 |
| transporting_vehicles | int | 运输中车辆数 |
| charging_vehicles | int | 充电中车辆数 |
| total_charging_stations | int | 充电站总数 |
| active_commands | int | 活动命令数 |
| current_strategy | string | 当前策略 |

#### 获取性能指标
- **接口**: `GET /api/system/performance`
- **响应模型**: `PerformanceMetricsResponse`
- **返回格式**:
```json
{
  "completion_rate": 0.8,
  "avg_completion_time": 1200.0,
  "total_distance": 5000.0,
  "total_score": 350.0
}
```

**PerformanceMetricsResponse 字段说明**：
| 字段 | 类型 | 说明 |
|------|------|------|
| completion_rate | float | 完成率 |
| avg_completion_time | float | 平均完成时间 |
| total_distance | float | 总行驶距离 |
| total_score | float | 总得分 |

#### 获取仿真状态
- **接口**: `GET /api/system/state`
- **响应模型**: `SimulationStateResponse`
- **返回格式**:
```json
{
  "timestamp": 1678888888,
  "warehouse_position": {"x": 0.0, "y": 0.0},
  "vehicles": [...],
  "tasks": [...],
  "charging_stations": [...],
  "total_score": 0.0,
  "map_nodes": [],
  "map_edges": []
}
```

---

### 6. 调度接口

#### 执行动态调度
- **接口**: `POST /api/scheduling`
- **请求模型**: `SchedulingRequest`
- **响应模型**: `List[CommandResponse]`
- **请求格式**:
```json
{
  "strategy": "auto",
  "task_ids": [1, 2, 3]
}
```

**SchedulingRequest 字段说明**：
| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| strategy | string | 否 | "auto" | 调度策略 |
| task_ids | List[int] | 否 | null | 指定任务ID列表 |

**可用策略**：
- `shortest_task_first` - 最近任务优先
- `heaviest_task_first` - 最大任务优先
- `auto` - 自动选择

#### 执行静态规划
- **接口**: `POST /api/scheduling/static`
- **返回格式**:
```json
{
  "success": true,
  "plan": {
    "vehicle_routes": {"1": [1, 2], "2": [3]},
    "task_assignments": {"1": 1, "2": 1, "3": 2},
    "charging_schedule": {"1": [], "2": []},
    "total_distance": 1500.0,
    "total_time": 2400.0,
    "objective_value": 3900.0
  }
}
```

#### 车辆充电
- **接口**: `POST /api/vehicles/{vehicle_id}/charge`
- **错误响应**: 404 - "Vehicle not found"
- **返回格式**:
```json
{
  "success": true,
  "command": {
    "vehicle_id": 1,
    "action_type": "charge",
    "assigned_tasks": [],
    "path": [[150.0, 150.0], [250.0, 150.0]],
    "charging_station_id": "cs1",
    "estimated_time": 0
  }
}
```

---

### 7. 其他接口

#### 获取可用策略
- **接口**: `GET /api/strategies`
- **返回格式**:
```json
{
  "strategies": ["shortest_task_first", "heaviest_task_first", "auto"],
  "current_strategy": "shortest_task_first"
}
```

#### 获取活动命令
- **接口**: `GET /api/commands`
- **返回格式**:
```json
{
  "commands": [
    {
      "vehicle_id": 1,
      "action_type": "transport",
      "assigned_tasks": [1],
      "path": [[150.0, 150.0], [200.0, 200.0]],
      "charging_station_id": null,
      "estimated_time": 500,
      "complete_path": [[0.0, 0.0], [150.0, 150.0], [200.0, 200.0], [150.0, 150.0], [0.0, 0.0]],
      "total_distance": 500.0,
      "energy_consumption": 50.0
    }
  ]
}
```

---

### 8. 中央仓库管理接口

#### 获取仓库位置
- **接口**: `GET /api/warehouse/position`
- **响应模型**: `WarehousePositionModel`
- **返回格式**:
```json
{
  "x": 0.0,
  "y": 0.0
}
```

#### 设置仓库位置
- **接口**: `POST /api/warehouse/position`
- **请求模型**: `WarehousePositionModel`
- **返回格式**:
```json
{
  "success": true,
  "position": {"x": 0.0, "y": 0.0}
}
```

---

### 9. 完整路径规划接口

#### 计算完整路径
- **接口**: `POST /api/paths/complete`
- **请求模型**: `CompletePathRequest`
- **响应模型**: `CompletePathResponse`
- **请求格式**:
```json
{
  "task_id": 1,
  "vehicle_id": 1
}
```

**CompletePathRequest 字段说明**：
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | int | 是 | 任务ID |
| vehicle_id | int | 是 | 车辆ID |

- **返回格式**:
```json
{
  "task_id": 1,
  "vehicle_id": 1,
  "complete_path": [
    {"x": 0.0, "y": 0.0},
    {"x": 150.0, "y": 150.0},
    {"x": 200.0, "y": 200.0},
    {"x": 150.0, "y": 150.0},
    {"x": 0.0, "y": 0.0}
  ],
  "total_distance": 500.0,
  "energy_consumption": 50.0,
  "is_feasible": true,
  "estimated_completion_time": 530.0
}
```

#### 批量计算完整路径
- **接口**: `POST /api/paths/complete/batch`
- **请求模型**: `BatchCompletePathRequest`
- **响应模型**: `List[CompletePathResponse]`
- **请求格式**:
```json
{
  "task_vehicle_pairs": [
    {"task_id": 1, "vehicle_id": 1},
    {"task_id": 2, "vehicle_id": 2}
  ]
}
```

**BatchCompletePathRequest 字段说明**：
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_vehicle_pairs | List[TaskVehiclePair] | 是 | 任务-车辆对列表 |

**TaskVehiclePair 字段说明**：
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | int | 是 | 任务ID |
| vehicle_id | int | 是 | 车辆ID |

- **返回格式**:
```json
[
  {
    "task_id": 1,
    "vehicle_id": 1,
    "complete_path": [...],
    "total_distance": 500.0,
    "energy_consumption": 50.0,
    "is_feasible": true,
    "estimated_completion_time": 530.0
  },
  {
    "task_id": 2,
    "vehicle_id": 2,
    "complete_path": [...],
    "total_distance": 600.0,
    "energy_consumption": 60.0,
    "is_feasible": true,
    "estimated_completion_time": 630.0
  }
]
```

---

### 10. 任务完成接口

#### 获取任务完成信息
- **接口**: `GET /api/tasks/{task_id}/completion`
- **响应模型**: `TaskCompletionInfo`
- **返回格式**:
```json
{
  "task_id": 1,
  "completion_time": 1678893000,
  "score": 100.0,
  "is_on_time": true,
  "total_distance": 500.0
}
```

#### 获取所有已完成任务信息
- **接口**: `GET /api/tasks/completed`
- **响应模型**: `List[TaskCompletionInfo]`
- **返回格式**:
```json
[
  {
    "task_id": 1,
    "completion_time": 1678893000,
    "score": 100.0,
    "is_on_time": true,
    "total_distance": 500.0
  },
  {
    "task_id": 2,
    "completion_time": 1678893500,
    "score": -50.0,
    "is_on_time": false,
    "total_distance": 600.0
  }
]
```

---

## 数据模型定义

### PositionModel
```json
{
  "x": 0.0,
  "y": 0.0
}
```

### TaskModel
```json
{
  "id": 0,
  "position": {"x": 0.0, "y": 0.0},
  "weight": 0.0,
  "create_time": 0,
  "deadline": 0,
  "priority": 0,
  "status": "pending",
  "assigned_vehicle_id": null,
  "start_time": null,
  "complete_time": null,
  "complete_path": [],
  "complete_path_distance": 0.0,
  "estimated_completion_time": 0.0,
  "score": 0.0
}
```

**TaskModel 字段说明**（新增字段）：
| 字段 | 类型 | 说明 |
|------|------|------|
| complete_path | List[PositionModel] | 完整路径（仓库→任务点→仓库） |
| complete_path_distance | float | 完整路径总距离 |
| estimated_completion_time | float | 预计完成时间 |
| score | float | 任务得分 |

### VehicleModel
```json
{
  "id": 0,
  "position": {"x": 0.0, "y": 0.0},
  "battery": 0.0,
  "max_battery": 0.0,
  "battery_percentage": 0.0,
  "current_load": 0.0,
  "max_load": 0.0,
  "load_percentage": 0.0,
  "unit_energy_consumption": 0.0,
  "status": "idle",
  "assigned_task_ids": [],
  "current_path": [],
  "charging_station_id": null,
  "complete_path": [],
  "path_progress": 0.0,
  "energy_consumption": 0.0
}
```

**VehicleModel 字段说明**（新增字段）：
| 字段 | 类型 | 说明 |
|------|------|------|
| complete_path | List[PositionModel] | 完整路径（仓库→任务点→仓库） |
| path_progress | float | 路径进度（0.0-1.0） |
| energy_consumption | float | 电量消耗 |

**VehicleModel 状态说明**（新增状态）：
| 状态 | 说明 |
|------|------|
| idle | 空闲，位于仓库 |
| transporting_to_task | 从仓库前往任务点 |
| delivering | 在任务点配送 |
| returning_to_warehouse | 从任务点返回仓库 |
| charging | 充电中 |

### ChargingStationModel
```json
{
  "id": "",
  "position": {"x": 0.0, "y": 0.0},
  "capacity": 0,
  "queue_count": 0,
  "charging_vehicles": [],
  "load_pressure": 0.0,
  "charging_rate": 0.0,
  "available_capacity": 0
}
```

### CommandResponse
```json
{
  "vehicle_id": 0,
  "action_type": "",
  "assigned_tasks": [],
  "path": [],
  "charging_station_id": null,
  "estimated_time": 0,
  "complete_path": [],
  "total_distance": 0.0,
  "energy_consumption": 0.0
}
```

**CommandResponse 字段说明**（新增字段）：
| 字段 | 类型 | 说明 |
|------|------|------|
| complete_path | List[PositionModel] | 完整路径（仓库→任务点→仓库） |
| total_distance | float | 总距离 |
| energy_consumption | float | 电量消耗 |

### CompletePathResponse
```json
{
  "task_id": 0,
  "vehicle_id": 0,
  "complete_path": [],
  "total_distance": 0.0,
  "energy_consumption": 0.0,
  "is_feasible": true,
  "estimated_completion_time": 0.0
}
```

**CompletePathResponse 字段说明**：
| 字段 | 类型 | 说明 |
|------|------|------|
| task_id | int | 任务ID |
| vehicle_id | int | 车辆ID |
| complete_path | List[PositionModel] | 完整路径 |
| total_distance | float | 总距离 |
| energy_consumption | float | 电量消耗 |
| is_feasible | bool | 是否可行（电量是否充足） |
| estimated_completion_time | float | 预计完成时间 |

### WarehousePositionModel
```json
{
  "x": 0.0,
  "y": 0.0
}
```

### TaskCompletionInfo
```json
{
  "task_id": 0,
  "completion_time": 0,
  "score": 0.0,
  "is_on_time": true,
  "total_distance": 0.0
}
```

**TaskCompletionInfo 字段说明**：
| 字段 | 类型 | 说明 |
|------|------|------|
| task_id | int | 任务ID |
| completion_time | int | 完成时间 |
| score | float | 任务得分 |
| is_on_time | bool | 是否按时完成 |
| total_distance | float | 总距离 |

---

## WebSocket接口说明

### 连接WebSocket
- **地址**: `ws://localhost:8000/ws`
- **连接方式**:
```javascript
const ws = new WebSocket('ws://localhost:8000/ws');

ws.onopen = () => {
  console.log('WebSocket connected');
  ws.send(JSON.stringify({
    type: 'subscribe',
    events: ['all']
  }));
};

ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  handleMessage(message);
};

ws.onerror = (error) => {
  console.error('WebSocket error:', error);
};

ws.onclose = () => {
  console.log('WebSocket closed');
};
```

### WebSocket客户端消息类型

#### 订阅事件
```json
{
  "type": "subscribe",
  "events": ["task_update", "vehicle_update", "all"]
}
```

**可用事件**：
- `all` - 订阅所有事件
- `task_update` - 任务更新
- `vehicle_update` - 车辆更新
- `station_update` - 充电站更新
- `command_update` - 命令更新
- `system_status` - 系统状态
- `performance_metrics` - 性能指标

#### 获取状态
```json
{
  "type": "get_state"
}
```

#### 心跳检测
```json
{
  "type": "ping"
}
```

### WebSocket服务端消息类型

#### 1. 状态更新 (state_update)
```json
{
  "type": "state_update",
  "data": {
    "timestamp": 1678888888,
    "warehouse_position": {"x": 0.0, "y": 0.0},
    "vehicles": [...],
    "tasks": [...],
    "charging_stations": [...],
    "total_score": 0.0
  },
  "timestamp": 1678888888
}
```

#### 2. 状态响应 (state_response)
```json
{
  "type": "state_response",
  "data": {
    "timestamp": 1678888888,
    "warehouse_position": {"x": 0.0, "y": 0.0},
    "vehicles": [...],
    "tasks": [...],
    "charging_stations": [...]
  },
  "timestamp": 1678888888
}
```

#### 3. 任务更新 (task_update)
```json
{
  "type": "task_update",
  "data": {
    "id": 1,
    "position": {"x": 200.0, "y": 200.0},
    "weight": 30.0,
    "status": "in_progress"
  },
  "timestamp": 1678888888
}
```

#### 4. 车辆更新 (vehicle_update)
```json
{
  "type": "vehicle_update",
  "data": {
    "id": 1,
    "position": {"x": 160.0, "y": 160.0},
    "battery": 75.0,
    "status": "transporting"
  },
  "timestamp": 1678888888
}
```

#### 5. 充电站更新 (station_update)
```json
{
  "type": "station_update",
  "data": {
    "id": "cs1",
    "position": {"x": 250.0, "y": 150.0},
    "queue_count": 1,
    "charging_vehicles": [1]
  },
  "timestamp": 1678888888
}
```

#### 6. 命令更新 (command_update)
```json
{
  "type": "command_update",
  "data": {
    "vehicle_id": 1,
    "action_type": "transport",
    "assigned_tasks": [1],
    "path": [[150.0, 150.0], [200.0, 200.0]],
    "charging_station_id": null,
    "estimated_time": 500
  },
  "timestamp": 1678888888
}
```

#### 7. 系统状态更新 (system_status)
```json
{
  "type": "system_status",
  "data": {
    "timestamp": 1678888888,
    "total_tasks": 10,
    "pending_tasks": 5,
    "completed_tasks": 4,
    "timeout_tasks": 1,
    "total_vehicles": 3,
    "idle_vehicles": 1,
    "transporting_vehicles": 2,
    "charging_vehicles": 0,
    "total_charging_stations": 2,
    "active_commands": 2,
    "current_strategy": "shortest_task_first"
  },
  "timestamp": 1678888888
}
```

#### 8. 性能指标更新 (performance_metrics)
```json
{
  "type": "performance_metrics",
  "data": {
    "completion_rate": 0.8,
    "avg_completion_time": 1200.0,
    "total_distance": 5000.0,
    "total_score": 350.0
  },
  "timestamp": 1678888888
}
```

#### 9. 心跳响应 (pong)
```json
{
  "type": "pong",
  "timestamp": 1678888888
}
```

#### 10. 任务完成事件 (task_completed)
```json
{
  "type": "task_completed",
  "data": {
    "task_id": 1,
    "completion_time": 1678893000,
    "score": 100.0,
    "is_on_time": true,
    "total_distance": 500.0,
    "complete_path": [
      {"x": 0.0, "y": 0.0},
      {"x": 150.0, "y": 150.0},
      {"x": 200.0, "y": 200.0},
      {"x": 150.0, "y": 150.0},
      {"x": 0.0, "y": 0.0}
    ]
  },
  "timestamp": 1678893000
}
```

#### 11. 车辆返回仓库事件 (vehicle_returned_to_warehouse)
```json
{
  "type": "vehicle_returned_to_warehouse",
  "data": {
    "vehicle_id": 1,
    "position": {"x": 0.0, "y": 0.0},
    "status": "idle",
    "completed_tasks": [1, 2],
    "battery": 75.0,
    "total_distance_traveled": 1000.0
  },
  "timestamp": 1678893000
}
```

#### 12. 完整路径更新 (complete_path_update)
```json
{
  "type": "complete_path_update",
  "data": {
    "task_id": 1,
    "vehicle_id": 1,
    "complete_path": [
      {"x": 0.0, "y": 0.0},
      {"x": 150.0, "y": 150.0},
      {"x": 200.0, "y": 200.0},
      {"x": 150.0, "y": 150.0},
      {"x": 0.0, "y": 0.0}
    ],
    "total_distance": 500.0,
    "energy_consumption": 50.0,
    "estimated_completion_time": 530.0
  },
  "timestamp": 1678888888
}
```

#### 13. 仓库位置更新 (warehouse_position_update)
```json
{
  "type": "warehouse_position_update",
  "data": {
    "position": {"x": 0.0, "y": 0.0}
  },
  "timestamp": 1678888888
}
```

---

## 前端调整建议

### 1. API调用封装

创建API服务类，封装所有API调用：

```javascript
class APIService {
  constructor(baseURL = 'http://localhost:8000/api') {
    this.baseURL = baseURL;
  }

  async request(endpoint, options = {}) {
    const response = await fetch(`${this.baseURL}${endpoint}`, {
      headers: {'Content-Type': 'application/json'},
      ...options
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Request failed');
    }
    return response.json();
  }

  // 任务管理
  async getTasks() {
    return this.request('/tasks');
  }

  async getTask(taskId) {
    return this.request(`/tasks/${taskId}`);
  }

  async createTask(taskData) {
    return this.request('/tasks', {
      method: 'POST',
      body: JSON.stringify(taskData)
    });
  }

  // 车辆管理
  async getVehicles() {
    return this.request('/vehicles');
  }

  async getVehicle(vehicleId) {
    return this.request(`/vehicles/${vehicleId}`);
  }

  async createVehicle(vehicleData) {
    return this.request('/vehicles', {
      method: 'POST',
      body: JSON.stringify(vehicleData)
    });
  }

  async updateVehicle(vehicleId, vehicleData) {
    return this.request(`/vehicles/${vehicleId}`, {
      method: 'PUT',
      body: JSON.stringify(vehicleData)
    });
  }

  async chargeVehicle(vehicleId) {
    return this.request(`/vehicles/${vehicleId}/charge`, {
      method: 'POST'
    });
  }

  // 充电站管理
  async getChargingStations() {
    return this.request('/stations');
  }

  async getChargingStation(stationId) {
    return this.request(`/stations/${stationId}`);
  }

  async createChargingStation(stationData) {
    return this.request('/stations', {
      method: 'POST',
      body: JSON.stringify(stationData)
    });
  }

  // 地图数据
  async getMapData() {
    return this.request('/map');
  }

  // 系统状态
  async getSystemStatus() {
    return this.request('/system/status');
  }

  async getPerformanceMetrics() {
    return this.request('/system/performance');
  }

  async getSimulationState() {
    return this.request('/system/state');
  }

  // 调度
  async scheduleTasks(strategy = 'auto', taskIds = null) {
    return this.request('/scheduling', {
      method: 'POST',
      body: JSON.stringify({
        strategy: strategy,
        task_ids: taskIds
      })
    });
  }

  async executeStaticPlanning() {
    return this.request('/scheduling/static', {
      method: 'POST'
    });
  }

  // 其他
  async getStrategies() {
    return this.request('/strategies');
  }

  async getActiveCommands() {
    return this.request('/commands');
  }

  // 中央仓库管理
  async getWarehousePosition() {
    return this.request('/warehouse/position');
  }

  async setWarehousePosition(position) {
    return this.request('/warehouse/position', {
      method: 'POST',
      body: JSON.stringify(position)
    });
  }

  // 完整路径规划
  async calculateCompletePath(taskId, vehicleId) {
    return this.request('/paths/complete', {
      method: 'POST',
      body: JSON.stringify({
        task_id: taskId,
        vehicle_id: vehicleId
      })
    });
  }

  async calculateBatchCompletePaths(taskVehiclePairs) {
    return this.request('/paths/complete/batch', {
      method: 'POST',
      body: JSON.stringify({
        task_vehicle_pairs: taskVehiclePairs
      })
    });
  }

  // 任务完成信息
  async getTaskCompletionInfo(taskId) {
    return this.request(`/tasks/${taskId}/completion`);
  }

  async getAllCompletedTasksInfo() {
    return this.request('/tasks/completed');
  }
}

export default new APIService();
```

### 2. WebSocket连接管理

创建WebSocket服务类：

```javascript
class WebSocketService {
  constructor(url = 'ws://localhost:8000/ws') {
    this.url = url;
    this.ws = null;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 5;
    this.reconnectInterval = 5000;
    this.messageHandlers = {};
  }

  connect() {
    this.ws = new WebSocket(this.url);

    this.ws.onopen = () => {
      console.log('WebSocket connected');
      this.reconnectAttempts = 0;
      this.subscribe(['all']);
    };

    this.ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      this.handleMessage(message);
    };

    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };

    this.ws.onclose = () => {
      console.log('WebSocket closed');
      this.reconnect();
    };
  }

  reconnect() {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++;
      console.log(`Reconnecting... Attempt ${this.reconnectAttempts}`);
      setTimeout(() => this.connect(), this.reconnectInterval);
    }
  }

  subscribe(events) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        type: 'subscribe',
        events: events
      }));
    }
  }

  getState() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        type: 'get_state'
      }));
    }
  }

  ping() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        type: 'ping'
      }));
    }
  }

  onMessage(type, handler) {
    this.messageHandlers[type] = handler;
  }

  handleMessage(message) {
    const handler = this.messageHandlers[message.type];
    if (handler) {
      handler(message.data, message.timestamp);
    }
  }

  disconnect() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}

export default new WebSocketService();
```

### 3. 车辆参数配置界面

创建车辆配置表单，支持用户自定义车辆参数：

```javascript
const VehicleConfigForm = () => {
  const [vehicleType, setVehicleType] = useState('medium');
  const [vehicleCount, setVehicleCount] = useState(1);
  const [customParams, setCustomParams] = useState({
    max_battery: 100.0,
    max_load: 100.0,
    unit_energy_consumption: 0.1
  });

  const vehicleTypePresets = {
    small: {
      max_battery: 50.0,
      max_load: 50.0,
      unit_energy_consumption: 0.15
    },
    medium: {
      max_battery: 100.0,
      max_load: 100.0,
      unit_energy_consumption: 0.1
    },
    large: {
      max_battery: 200.0,
      max_load: 200.0,
      unit_energy_consumption: 0.08
    }
  };

  const handleTypeChange = (type) => {
    setVehicleType(type);
    setCustomParams(vehicleTypePresets[type]);
  };

  const handleSubmit = async () => {
    for (let i = 0; i < vehicleCount; i++) {
      await apiService.createVehicle({
        position: {x: 100 + i * 50, y: 100 + i * 50},
        battery: customParams.max_battery * 0.8,
        max_battery: customParams.max_battery,
        current_load: 0.0,
        max_load: customParams.max_load,
        unit_energy_consumption: customParams.unit_energy_consumption
      });
    }
  };

  return (
    <div>
      <h3>车辆参数配置</h3>
      <div>
        <label>车辆类型：</label>
        <select value={vehicleType} onChange={(e) => handleTypeChange(e.target.value)}>
          <option value="small">小型电动车</option>
          <option value="medium">中型电动车</option>
          <option value="large">大型电动车</option>
        </select>
      </div>
      <div>
        <label>车辆数量：</label>
        <input 
          type="number" 
          value={vehicleCount} 
          onChange={(e) => setVehicleCount(parseInt(e.target.value))}
          min="1"
          max="50"
        />
      </div>
      <div>
        <label>电量上限 (kWh)：</label>
        <input 
          type="number" 
          value={customParams.max_battery}
          onChange={(e) => setCustomParams({...customParams, max_battery: parseFloat(e.target.value)})}
          step="1"
          min="30"
          max="250"
        />
      </div>
      <div>
        <label>载重上限 (kg)：</label>
        <input 
          type="number" 
          value={customParams.max_load}
          onChange={(e) => setCustomParams({...customParams, max_load: parseFloat(e.target.value)})}
          step="1"
          min="30"
          max="300"
        />
      </div>
      <div>
        <label>单位能耗 (kWh/km)：</label>
        <input 
          type="number" 
          value={customParams.unit_energy_consumption}
          onChange={(e) => setCustomParams({...customParams, unit_energy_consumption: parseFloat(e.target.value)})}
          step="0.01"
          min="0.06"
          max="0.18"
        />
      </div>
      <button onClick={handleSubmit}>创建车辆</button>
    </div>
  );
};
```

### 4. 调度策略选择界面

创建策略选择组件：

```javascript
const StrategySelector = () => {
  const [strategies, setStrategies] = useState([]);
  const [currentStrategy, setCurrentStrategy] = useState('auto');

  useEffect(() => {
    loadStrategies();
  }, []);

  const loadStrategies = async () => {
    const data = await apiService.getStrategies();
    setStrategies(data.strategies);
    setCurrentStrategy(data.current_strategy);
  };

  const handleStrategyChange = async (strategy) => {
    setCurrentStrategy(strategy);
    await apiService.scheduleTasks(strategy);
  };

  const strategyLabels = {
    'shortest_task_first': '最近任务优先',
    'heaviest_task_first': '最大任务优先',
    'auto': '自动选择'
  };

  return (
    <div>
      <h3>调度策略选择</h3>
      <div>
        {strategies.map(strategy => (
          <button 
            key={strategy}
            onClick={() => handleStrategyChange(strategy)}
            className={currentStrategy === strategy ? 'active' : ''}
          >
            {strategyLabels[strategy]}
          </button>
        ))}
      </div>
      <button onClick={() => apiService.executeStaticPlanning()}>执行静态规划</button>
    </div>
  );
};
```

### 5. 系统状态监控界面

创建系统状态监控组件：

```javascript
const SystemMonitor = () => {
  const [systemStatus, setSystemStatus] = useState(null);
  const [performanceMetrics, setPerformanceMetrics] = useState(null);

  useEffect(() => {
    loadSystemData();
    
    wsService.onMessage('system_status', (data) => {
      setSystemStatus(data);
    });

    wsService.onMessage('performance_metrics', (data) => {
      setPerformanceMetrics(data);
    });

    return () => {
      wsService.onMessage('system_status', null);
      wsService.onMessage('performance_metrics', null);
    };
  }, []);

  const loadSystemData = async () => {
    const [status, metrics] = await Promise.all([
      apiService.getSystemStatus(),
      apiService.getPerformanceMetrics()
    ]);
    setSystemStatus(status);
    setPerformanceMetrics(metrics);
  };

  if (!systemStatus || !performanceMetrics) {
    return <div>Loading...</div>;
  }

  return (
    <div>
      <h3>系统状态监控</h3>
      <div className="status-grid">
        <div className="status-card">
          <h4>任务统计</h4>
          <p>总任务数：{systemStatus.total_tasks}</p>
          <p>待处理：{systemStatus.pending_tasks}</p>
          <p>已完成：{systemStatus.completed_tasks}</p>
          <p>超时：{systemStatus.timeout_tasks}</p>
        </div>
        <div className="status-card">
          <h4>车辆统计</h4>
          <p>总车辆数：{systemStatus.total_vehicles}</p>
          <p>空闲：{systemStatus.idle_vehicles}</p>
          <p>运输中：{systemStatus.transporting_vehicles}</p>
          <p>充电中：{systemStatus.charging_vehicles}</p>
        </div>
        <div className="status-card">
          <h4>性能指标</h4>
          <p>完成率：{(performanceMetrics.completion_rate * 100).toFixed(1)}%</p>
          <p>平均完成时间：{performanceMetrics.avg_completion_time.toFixed(0)}秒</p>
          <p>总行驶距离：{performanceMetrics.total_distance.toFixed(0)}km</p>
          <p>总得分：{performanceMetrics.total_score.toFixed(0)}</p>
        </div>
        <div className="status-card">
          <h4>系统信息</h4>
          <p>充电站数量：{systemStatus.total_charging_stations}</p>
          <p>活动命令：{systemStatus.active_commands}</p>
          <p>当前策略：{systemStatus.current_strategy}</p>
        </div>
      </div>
    </div>
  );
};
```

### 6. 地图显示组件

创建地图显示组件，实时显示车辆、任务和充电站的位置：

```javascript
const MapDisplay = () => {
  const [mapData, setMapData] = useState(null);

  useEffect(() => {
    loadMapData();
    
    wsService.onMessage('state_update', (data) => {
      setMapData(data);
    });

    return () => {
      wsService.onMessage('state_update', null);
    };
  }, []);

  const loadMapData = async () => {
    const data = await apiService.getSimulationState();
    setMapData(data);
  };

  if (!mapData) {
    return <div>Loading map...</div>;
  }

  const getStatusColor = (status) => {
    switch (status) {
      case 'idle': return 'green';
      case 'transporting': return 'orange';
      case 'charging': return 'red';
      case 'pending': return 'yellow';
      case 'in_progress': return 'orange';
      case 'completed': return 'green';
      default: return 'gray';
    }
  };

  return (
    <div className="map-container">
      <svg width="800" height="600">
        {mapData.warehouse_position && (
          <g>
            <circle 
              cx={mapData.warehouse_position.x} 
              cy={mapData.warehouse_position.y} 
              r="10" 
              fill="blue"
            />
            <text x={mapData.warehouse_position.x} y={mapData.warehouse_position.y - 15}>
              仓库
            </text>
          </g>
        )}
        {mapData.vehicles.map(vehicle => (
          <g key={vehicle.id}>
            <circle 
              cx={vehicle.position.x} 
              cy={vehicle.position.y} 
              r="8" 
              fill={getStatusColor(vehicle.status)}
            />
            <text x={vehicle.position.x} y={vehicle.position.y - 12}>
              V{vehicle.id}
            </text>
          </g>
        ))}
        {mapData.tasks.map(task => (
          <g key={task.id}>
            <rect 
              x={task.position.x - 5} 
              y={task.position.y - 5} 
              width="10" 
              height="10" 
              fill={getStatusColor(task.status)}
            />
            <text x={task.position.x} y={task.position.y - 8}>
              T{task.id}
            </text>
          </g>
        ))}
        {mapData.charging_stations.map(station => (
          <g key={station.id}>
            <rect 
              x={station.position.x - 8} 
              y={station.position.y - 8} 
              width="16" 
              height="16" 
              fill="purple"
            />
            <text x={station.position.x} y={station.position.y - 12}>
              {station.id}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
};
```

---

## 错误处理

### HTTP错误码
- `200` - 成功
- `404` - 资源未找到 (Task not found / Vehicle not found / Charging station not found)
- `422` - 请求参数验证失败
- `500` - 服务器内部错误

### 错误响应格式
```json
{
  "detail": "错误描述信息"
}
```

---

## 注意事项

1. **时间戳格式**：所有时间戳均为 Unix 时间戳（秒级）
2. **位置坐标**：使用 `PositionModel` 格式 `{"x": float, "y": float}`
3. **路径格式**：`path` 字段为坐标数组 `[[x1, y1], [x2, y2], ...]`
4. **WebSocket重连**：建议实现自动重连机制，最大重试次数建议为5次
5. **事件订阅**：默认订阅 `all` 事件，可根据需要订阅特定事件类型

---

## 完整路径规划前端实现建议

### 1. 地图组件更新

#### 1.1 显示中央仓库
```javascript
const MapComponent = () => {
  const [warehousePosition, setWarehousePosition] = useState({x: 0, y: 0});

  useEffect(() => {
    // 获取仓库位置
    apiService.getWarehousePosition().then(pos => {
      setWarehousePosition(pos);
    });

    // 订阅仓库位置更新
    webSocketService.onMessage('warehouse_position_update', (data) => {
      setWarehousePosition(data.position);
    });
  }, []);

  return (
    <div className="map">
      {/* 仓库图标 */}
      <WarehouseIcon position={warehousePosition} />
      
      {/* 其他地图元素 */}
      <TasksLayer />
      <VehiclesLayer />
      <ChargingStationsLayer />
    </div>
  );
};
```

#### 1.2 显示完整路径
```javascript
const VehiclePath = ({vehicle}) => {
  const [completePath, setCompletePath] = useState([]);

  useEffect(() => {
    // 订阅完整路径更新
    webSocketService.onMessage('complete_path_update', (data) => {
      if (data.vehicle_id === vehicle.id) {
        setCompletePath(data.complete_path);
      }
    });
  }, [vehicle.id]);

  return (
    <g>
      {/* 绘制完整路径 */}
      <path
        d={generatePathD(completePath)}
        stroke="#4CAF50"
        strokeWidth={2}
        fill="none"
        strokeDasharray="5,5"
      />
      
      {/* 绘制方向箭头 */}
      {completePath.map((point, index) => (
        index < completePath.length - 1 && (
          <Arrow
            from={completePath[index]}
            to={completePath[index + 1]}
            key={index}
          />
        )
      ))}
      
      {/* 标记起点（仓库）和终点（仓库） */}
      <StartMarker position={completePath[0]} />
      <EndMarker position={completePath[completePath.length - 1]} />
    </g>
  );
};
```

### 2. 任务列表组件更新

#### 2.1 显示任务完整路径信息
```javascript
const TaskListItem = ({task}) => {
  return (
    <div className="task-item">
      <h3>任务 #{task.id}</h3>
      
      {/* 任务状态 */}
      <div className="task-status">
        <span className={`status-badge ${task.status}`}>
          {task.status}
        </span>
      </div>

      {/* 完整路径信息 */}
      {task.complete_path && task.complete_path.length > 0 && (
        <div className="task-path-info">
          <h4>完整路径信息</h4>
          <p>总距离: {task.complete_path_distance.toFixed(2)} 单位</p>
          <p>预计完成时间: {formatTime(task.estimated_completion_time)}</p>
          
          {/* 路径可视化 */}
          <PathVisualization path={task.complete_path} />
        </div>
      )}

      {/* 任务得分 */}
      {task.score !== undefined && (
        <div className="task-score">
          <h4>任务得分</h4>
          <p className={task.score >= 0 ? 'positive' : 'negative'}>
            {task.score >= 0 ? '+' : ''}{task.score.toFixed(1)} 分
          </p>
        </div>
      )}

      {/* 时间信息 */}
      <div className="task-time">
        <p>创建时间: {formatTime(task.create_time)}</p>
        <p>截止时间: {formatTime(task.deadline)}</p>
        {task.start_time && (
          <p>开始时间: {formatTime(task.start_time)}</p>
        )}
        {task.complete_time && (
          <p>完成时间: {formatTime(task.complete_time)}</p>
        )}
      </div>
    </div>
  );
};
```

### 3. 车辆列表组件更新

#### 3.1 显示车辆完整路径和进度
```javascript
const VehicleListItem = ({vehicle}) => {
  return (
    <div className="vehicle-item">
      <h3>车辆 #{vehicle.id}</h3>

      {/* 车辆状态 */}
      <div className="vehicle-status">
        <span className={`status-badge ${vehicle.status}`}>
          {formatVehicleStatus(vehicle.status)}
        </span>
      </div>

      {/* 完整路径进度 */}
      {vehicle.complete_path && vehicle.complete_path.length > 0 && (
        <div className="vehicle-path-progress">
          <h4>路径进度</h4>
          <ProgressBar progress={vehicle.path_progress * 100} />
          <p>已完成: {(vehicle.path_progress * 100).toFixed(1)}%</p>
          
          {/* 路径可视化 */}
          <PathVisualization path={vehicle.complete_path} />
        </div>
      )}

      {/* 电量信息 */}
      <div className="vehicle-battery">
        <h4>电量信息</h4>
        <ProgressBar 
          progress={vehicle.battery_percentage} 
          color={getBatteryColor(vehicle.battery_percentage)}
        />
        <p>当前电量: {vehicle.battery.toFixed(1)} / {vehicle.max_battery.toFixed(1)}</p>
        <p>电量消耗: {vehicle.energy_consumption.toFixed(2)}</p>
      </div>

      {/* 位置信息 */}
      <div className="vehicle-position">
        <p>当前位置: ({vehicle.position.x.toFixed(1)}, {vehicle.position.y.toFixed(1)})</p>
      </div>
    </div>
  );
};

function formatVehicleStatus(status) {
  const statusMap = {
    'idle': '空闲',
    'transporting_to_task': '前往任务点',
    'delivering': '配送中',
    'returning_to_warehouse': '返回仓库',
    'charging': '充电中'
  };
  return statusMap[status] || status;
}
```

### 4. 完整路径计算组件

```javascript
const CompletePathCalculator = () => {
  const [taskId, setTaskId] = useState('');
  const [vehicleId, setVehicleId] = useState('');
  const [result, setResult] = useState(null);

  const handleCalculate = async () => {
    try {
      const response = await apiService.calculateCompletePath(
        parseInt(taskId),
        parseInt(vehicleId)
      );
      setResult(response);
    } catch (error) {
      console.error('计算完整路径失败:', error);
    }
  };

  return (
    <div className="path-calculator">
      <h3>完整路径计算</h3>
      
      <div className="input-group">
        <label>任务ID:</label>
        <input 
          type="number" 
          value={taskId}
          onChange={(e) => setTaskId(e.target.value)}
        />
      </div>

      <div className="input-group">
        <label>车辆ID:</label>
        <input 
          type="number" 
          value={vehicleId}
          onChange={(e) => setVehicleId(e.target.value)}
        />
      </div>

      <button onClick={handleCalculate}>计算完整路径</button>

      {result && (
        <div className="path-result">
          <h4>计算结果</h4>
          <p>总距离: {result.total_distance.toFixed(2)} 单位</p>
          <p>电量消耗: {result.energy_consumption.toFixed(2)}</p>
          <p>预计完成时间: {formatTime(result.estimated_completion_time)}</p>
          <p className={result.is_feasible ? 'feasible' : 'not-feasible'}>
            {result.is_feasible ? '✓ 可行' : '✗ 不可行（电量不足）'}
          </p>

          {/* 路径可视化 */}
          <PathVisualization path={result.complete_path} />
        </div>
      )}
    </div>
  );
};
```

### 5. 任务完成信息组件

```javascript
const TaskCompletionInfo = ({taskId}) => {
  const [completionInfo, setCompletionInfo] = useState(null);

  useEffect(() => {
    // 获取任务完成信息
    apiService.getTaskCompletionInfo(taskId).then(info => {
      setCompletionInfo(info);
    });

    // 订阅任务完成事件
    webSocketService.onMessage('task_completed', (data) => {
      if (data.task_id === taskId) {
        setCompletionInfo(data);
      }
    });
  }, [taskId]);

  if (!completionInfo) {
    return <div>任务尚未完成</div>;
  }

  return (
    <div className="task-completion-info">
      <h3>任务完成信息</h3>
      
      <div className="completion-time">
        <p>完成时间: {formatTime(completionInfo.completion_time)}</p>
      </div>

      <div className="completion-score">
        <h4>任务得分</h4>
        <p className={completionInfo.score >= 0 ? 'positive' : 'negative'}>
          {completionInfo.score >= 0 ? '+' : ''}{completionInfo.score.toFixed(1)} 分
        </p>
      </div>

      <div className="completion-status">
        <h4>完成状态</h4>
        <p className={completionInfo.is_on_time ? 'on-time' : 'late'}>
          {completionInfo.is_on_time ? '✓ 按时完成' : '✗ 超时完成'}
        </p>
      </div>

      <div className="completion-distance">
        <p>总行驶距离: {completionInfo.total_distance.toFixed(2)} 单位</p>
      </div>

      {/* 完整路径可视化 */}
      {completionInfo.complete_path && (
        <PathVisualization path={completionInfo.complete_path} />
      )}
    </div>
  );
};
```

### 6. 路径可视化通用组件

```javascript
const PathVisualization = ({path}) => {
  if (!path || path.length === 0) {
    return null;
  }

  // 计算边界框以缩放路径
  const bounds = calculateBounds(path);
  const scale = Math.min(
    300 / (bounds.maxX - bounds.minX),
    300 / (bounds.maxY - bounds.minY)
  );

  return (
    <svg width="300" height="300" viewBox={`${bounds.minX} ${bounds.minY} ${bounds.maxX - bounds.minX} ${bounds.maxY - bounds.minY}`}>
      {/* 绘制路径 */}
      <path
        d={generatePathD(path)}
        stroke="#2196F3"
        strokeWidth={2}
        fill="none"
      />

      {/* 绘制路径点 */}
      {path.map((point, index) => (
        <circle
          key={index}
          cx={point.x}
          cy={point.y}
          r={4}
          fill={index === 0 || index === path.length - 1 ? '#4CAF50' : '#2196F3'}
        />
      ))}

      {/* 标记起点和终点 */}
      <text x={path[0].x} y={path[0].y - 10} textAnchor="middle">
        起点（仓库）
      </text>
      <text x={path[path.length - 1].x} y={path[path.length - 1].y - 10} textAnchor="middle">
        终点（仓库）
      </text>
    </svg>
  );
};

function generatePathD(path) {
  return path.reduce((d, point, index) => {
    return index === 0 
      ? `M ${point.x} ${point.y}`
      : `${d} L ${point.x} ${point.y}`;
  }, '');
}

function calculateBounds(path) {
  const xs = path.map(p => p.x);
  const ys = path.map(p => p.y);
  return {
    minX: Math.min(...xs),
    maxX: Math.max(...xs),
    minY: Math.min(...ys),
    maxY: Math.max(...ys)
  };
}
```

### 7. WebSocket事件处理更新

```javascript
// 在组件挂载时订阅新的事件
useEffect(() => {
  // 订阅任务完成事件
  webSocketService.onMessage('task_completed', (data) => {
    console.log('任务完成:', data);
    // 更新任务列表
    updateTaskCompletion(data);
  });

  // 订阅车辆返回仓库事件
  webSocketService.onMessage('vehicle_returned_to_warehouse', (data) => {
    console.log('车辆返回仓库:', data);
    // 更新车辆状态
    updateVehicleStatus(data);
  });

  // 订阅完整路径更新事件
  webSocketService.onMessage('complete_path_update', (data) => {
    console.log('完整路径更新:', data);
    // 更新路径显示
    updateCompletePath(data);
  });

  // 订阅仓库位置更新事件
  webSocketService.onMessage('warehouse_position_update', (data) => {
    console.log('仓库位置更新:', data);
    // 更新仓库位置
    updateWarehousePosition(data.position);
  });

  return () => {
    // 清理事件监听器
    webSocketService.onMessage('task_completed', null);
    webSocketService.onMessage('vehicle_returned_to_warehouse', null);
    webSocketService.onMessage('complete_path_update', null);
    webSocketService.onMessage('warehouse_position_update', null);
  };
}, []);
```

### 8. 性能指标展示更新

```javascript
const PerformanceMetrics = () => {
  const [metrics, setMetrics] = useState(null);

  useEffect(() => {
    // 获取性能指标
    apiService.getPerformanceMetrics().then(data => {
      setMetrics(data);
    });

    // 订阅性能指标更新
    webSocketService.onMessage('performance_metrics', (data) => {
      setMetrics(data);
    });
  }, []);

  if (!metrics) {
    return <div>加载中...</div>;
  }

  return (
    <div className="performance-metrics">
      <h3>性能指标</h3>
      
      <div className="metric-item">
        <label>任务完成率:</label>
        <span>{(metrics.completion_rate * 100).toFixed(1)}%</span>
      </div>

      <div className="metric-item">
        <label>平均完成时间:</label>
        <span>{metrics.avg_completion_time.toFixed(1)} 秒</span>
      </div>

      <div className="metric-item">
        <label>总行驶距离:</label>
        <span>{metrics.total_distance.toFixed(2)} 单位</span>
      </div>

      <div className="metric-item">
        <label>总得分:</label>
        <span className={metrics.total_score >= 0 ? 'positive' : 'negative'}>
          {metrics.total_score >= 0 ? '+' : ''}{metrics.total_score.toFixed(1)}
        </span>
      </div>
    </div>
  );
};
```

### 9. 完整路径规划功能集成

```javascript
const CompletePathPlanningIntegration = () => {
  const [tasks, setTasks] = useState([]);
  const [vehicles, setVehicles] = useState([]);
  const [selectedTask, setSelectedTask] = useState(null);
  const [selectedVehicle, setSelectedVehicle] = useState(null);
  const [pathResult, setPathResult] = useState(null);

  // 获取任务和车辆列表
  useEffect(() => {
    Promise.all([
      apiService.getTasks(),
      apiService.getVehicles()
    ]).then(([tasksData, vehiclesData]) => {
      setTasks(tasksData);
      setVehicles(vehiclesData);
    });
  }, []);

  // 计算完整路径
  const handleCalculatePath = async () => {
    if (!selectedTask || !selectedVehicle) {
      alert('请选择任务和车辆');
      return;
    }

    try {
      const result = await apiService.calculateCompletePath(
        selectedTask.id,
        selectedVehicle.id
      );
      setPathResult(result);
    } catch (error) {
      console.error('计算完整路径失败:', error);
      alert('计算完整路径失败');
    }
  };

  return (
    <div className="path-planning">
      <h3>完整路径规划</h3>

      {/* 任务选择 */}
      <div className="selection-panel">
        <label>选择任务:</label>
        <select onChange={(e) => setSelectedTask(tasks.find(t => t.id === parseInt(e.target.value)))}>
          <option value="">-- 请选择任务 --</option>
          {tasks.map(task => (
            <option key={task.id} value={task.id}>
              任务 #{task.id} - 位置({task.position.x}, {task.position.y})
            </option>
          ))}
        </select>
      </div>

      {/* 车辆选择 */}
      <div className="selection-panel">
        <label>选择车辆:</label>
        <select onChange={(e) => setSelectedVehicle(vehicles.find(v => v.id === parseInt(e.target.value)))}>
          <option value="">-- 请选择车辆 --</option>
          {vehicles.map(vehicle => (
            <option key={vehicle.id} value={vehicle.id}>
              车辆 #{vehicle.id} - 电量{vehicle.battery.toFixed(1)}/{vehicle.max_battery.toFixed(1)}
            </option>
          ))}
        </select>
      </div>

      {/* 计算按钮 */}
      <button onClick={handleCalculatePath}>计算完整路径</button>

      {/* 路径结果 */}
      {pathResult && (
        <div className="path-result">
          <h4>路径计算结果</h4>
          
          <div className="result-item">
            <label>总距离:</label>
            <span>{pathResult.total_distance.toFixed(2)} 单位</span>
          </div>

          <div className="result-item">
            <label>电量消耗:</label>
            <span>{pathResult.energy_consumption.toFixed(2)}</span>
          </div>

          <div className="result-item">
            <label>预计完成时间:</label>
            <span>{formatTime(pathResult.estimated_completion_time)}</span>
          </div>

          <div className="result-item">
            <label>可行性:</label>
            <span className={pathResult.is_feasible ? 'feasible' : 'not-feasible'}>
              {pathResult.is_feasible ? '✓ 可行' : '✗ 不可行'}
            </span>
          </div>

          {/* 路径可视化 */}
          <PathVisualization path={pathResult.complete_path} />
        </div>
      )}
    </div>
  );
};
```
