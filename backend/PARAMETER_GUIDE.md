# 新能源物流车队协同调度系统 - 参数配置指南

## 车辆参数配置

### 车辆类型及参数范围

#### 1. 小型电动车（小型货车）
- **电量上限**: 30-60 kWh
  - 参考值: 50 kWh
  - 说明: 适用于城市短途配送，续航里程约150-200公里
- **载重上限**: 30-80 kg
  - 参考值: 50 kg
  - 说明: 适用于小件快递配送
- **单位能耗**: 0.12-0.18 kWh/km
  - 参考值: 0.15 kWh/km
  - 说明: 每公里消耗的电量
- **速度**: 0.08-0.12 km/时间步
  - 参考值: 0.1 km/时间步
  - 说明: 车辆行驶速度

#### 2. 中型电动车（中型货车）
- **电量上限**: 80-120 kWh
  - 参考值: 100 kWh
  - 说明: 适用于城市中长途配送，续航里程约250-350公里
- **载重上限**: 80-150 kg
  - 参考值: 100 kg
  - 说明: 适用于中等件快递配送
- **单位能耗**: 0.08-0.12 kWh/km
  - 参考值: 0.1 kWh/km
  - 说明: 每公里消耗的电量
- **速度**: 0.08-0.12 km/时间步
  - 参考值: 0.1 km/时间步
  - 说明: 车辆行驶速度

#### 3. 大型电动车（大型货车）
- **电量上限**: 150-250 kWh
  - 参考值: 200 kWh
  - 说明: 适用于城市长途配送，续航里程约400-500公里
- **载重上限**: 150-300 kg
  - 参考值: 200 kg
  - 说明: 适用于大件货物配送
- **单位能耗**: 0.06-0.10 kWh/km
  - 参考值: 0.08 kWh/km
  - 说明: 每公里消耗的电量
- **速度**: 0.06-0.10 km/时间步
  - 参考值: 0.08 km/时间步
  - 说明: 车辆行驶速度

## 充电站参数配置

### 充电站容量
- **容量范围**: 3-10 个充电位
  - 参考值: 5 个充电位
  - 说明: 充电站可同时服务的车辆数量
- **充电速率**: 8-15 kW
  - 参考值: 10 kW
  - 说明: 每个充电位的充电功率
- **最大排队时间**: 180-600 秒
  - 参考值: 300 秒
  - 说明: 车辆最大等待时间

## 任务参数配置

### 任务重量范围
- **最小重量**: 5-20 kg
  - 参考值: 10 kg
  - 说明: 最小任务重量
- **最大重量**: 150-300 kg
  - 参考值: 200 kg
  - 说明: 最大任务重量
- **平均重量**: 30-80 kg
  - 参考值: 50 kg
  - 说明: 任务平均重量

### 任务优先级
- **优先级范围**: 1-5
  - 1: 低优先级
  - 2-3: 中等优先级
  - 4-5: 高优先级

### 任务时间窗口
- **创建时间**: 当前时间戳
- **截止时间**: 创建时间 + 1800-7200 秒（30分钟-2小时）
  - 参考值: 创建时间 + 3600 秒（1小时）
  - 说明: 任务必须完成的时间

## 系统参数配置

### 调度策略参数
- **重任务比例**: 0.7-0.9
  - 参考值: 0.8
  - 说明: 判断是否为重任务的阈值（相对于车辆平均剩余载重）
- **轻任务比例**: 0.1-0.3
  - 参考值: 0.2
  - 说明: 判断是否为轻任务的阈值（相对于车辆平均剩余载重）
- **长距离阈值**: 3-8 km
  - 参考值: 5 km
  - 说明: 判断是否为长距离任务的阈值

### 算法参数
- **遗传算法**:
  - 种群大小: 50-200
  - 最大迭代次数: 200-1000
  - 变异率: 0.05-0.2
  - 交叉率: 0.7-0.9

- **聚类算法**:
  - K值: 2-6
  - 最大迭代次数: 50-200

## 不同规模问题的参数建议

### 小规模问题（1-5辆车，1-10个任务）
- 车辆类型: 中型电动车为主
- 充电站数量: 1-2个
- 任务重量: 10-50 kg
- 适合算法: MIP求解器

### 中规模问题（5-15辆车，10-30个任务）
- 车辆类型: 混合使用小型、中型电动车
- 充电站数量: 2-4个
- 任务重量: 10-100 kg
- 适合算法: 遗传算法

### 大规模问题（15-50辆车，30-100个任务）
- 车辆类型: 混合使用小型、中型、大型电动车
- 充电站数量: 4-10个
- 任务重量: 10-200 kg
- 适合算法: 聚类分区 + 遗传算法

## 参数配置示例

### 示例1: 城市快递配送
```json
{
  "vehicles": [
    {
      "type": "medium",
      "count": 10,
      "max_battery": 100.0,
      "max_load": 100.0,
      "unit_energy_consumption": 0.1
    }
  ],
  "charging_stations": [
    {
      "id": "cs1",
      "capacity": 5,
      "charging_rate": 10.0
    },
    {
      "id": "cs2",
      "capacity": 5,
      "charging_rate": 10.0
    }
  ],
  "tasks": {
    "min_weight": 10.0,
    "max_weight": 50.0,
    "avg_weight": 30.0
  }
}
```

### 示例2: 大件货物配送
```json
{
  "vehicles": [
    {
      "type": "large",
      "count": 5,
      "max_battery": 200.0,
      "max_load": 200.0,
      "unit_energy_consumption": 0.08
    }
  ],
  "charging_stations": [
    {
      "id": "cs1",
      "capacity": 3,
      "charging_rate": 15.0
    }
  ],
  "tasks": {
    "min_weight": 50.0,
    "max_weight": 200.0,
    "avg_weight": 120.0
  }
}
```

## 参数调优建议

1. **电量配置**: 根据实际配送距离调整电量上限，确保车辆能完成往返配送
2. **载重配置**: 根据实际货物重量分布调整载重上限，避免车辆超载
3. **充电站配置**: 根据车辆数量和充电需求调整充电站容量，避免排队过长
4. **任务配置**: 根据实际业务需求调整任务重量和时间窗口，提高调度效率
5. **算法参数**: 根据问题规模调整算法参数，平衡求解质量和求解时间

---

## 调试输出信息说明

### 系统启动信息

#### 1. "Starting NEFT System..."
- **含义**: 系统开始启动，初始化各个模块
- **代码位置**: `main.py` 第 37 行
- **调试建议**: 如果此信息未出现，检查是否有 Python 依赖缺失或导入错误

#### 2. "Initializing test data for {problem_scale} scale problem..."
- **含义**: 开始初始化指定规模（small/medium/large）的测试数据
- **代码位置**: `main.py` 第 151 行
- **调试建议**: 
  - 检查 `problem_scale` 参数是否正确
  - 查看 `initialize_test_data()` 函数中的参数配置

#### 3. "Scale: {problem_scale}, Vehicles: {vehicle_count}, Stations: {station_count}, Algorithm: {algorithm}"
- **含义**: 显示当前问题规模的具体配置
- **代码位置**: `main.py` 第 181 行
- **调试建议**:
  - 车辆数量：修改 `initialize_test_data()` 函数中的 `vehicle_count` 变量
  - 充电站数量：修改 `station_count` 变量
  - 算法选择：修改 `algorithm` 变量返回值

#### 4. "Test data initialized successfully for {problem_scale} scale problem"
- **含义**: 测试数据初始化完成
- **代码位置**: `main.py` 第 215 行
- **调试建议**: 如果未出现此信息，检查车辆和充电站创建过程是否有错误

#### 5. "Log created: {log_path}"
- **含义**: 日志文件创建成功
- **代码位置**: `main.py` 第 316 行
- **调试建议**: 
  - 检查日志文件路径是否正确
  - 查看 `create_log_file()` 函数中的日志生成逻辑

### 任务生成信息

#### 6. "Generated new task {task.id}: position=({task.position.x:.2f}, {task.position.y:.2f}), weight={task.weight:.2f}"
- **含义**: 新任务生成成功，显示任务ID、位置和重量
- **代码位置**: `main.py` 第 326 行
- **调试建议**:
  - 任务位置范围：修改 `generate_random_task()` 函数中的 `random.uniform(50, 200)`
  - 任务重量范围：修改 `global_task_weight_range` 全局变量
  - 任务生成频率：修改 `task_generator()` 函数中的 `await asyncio.sleep(random.randint(10, 30))`

### 后台任务信息

#### 7. "[Background Task #{iteration_count}] Vehicles: {transporting_count} transporting, {idle_count} idle | Tasks: {pending_count} pending, {in_progress_count} in_progress, {completed_count} completed"
- **含义**: 显示当前系统状态，每10次循环输出一次
- **代码位置**: `main.py` 第 385 行
- **调试建议**:
  - 车辆状态：检查 `VehicleStatus` 枚举定义
  - 任务状态：检查 `TaskStatus` 枚举定义
  - 输出频率：修改 `if iteration_count % 10 == 0` 中的数字

#### 8. "[Background Task #{iteration_count}] Generated {len(commands)} commands"
- **含义**: 动态调度生成的命令数量
- **代码位置**: `main.py` 第 404 行
- **调试建议**:
  - 如果命令数量为0，检查 `decision_manager.dynamic_scheduling()` 是否正常工作
  - 如果命令数量异常，检查调度策略配置

### 错误信息

#### 9. "Parameters unchanged, skipping log creation"
- **含义**: 系统参数未变化，跳过日志创建
- **代码位置**: `main.py` 第 292 行
- **调试建议**: 
  - 检查 `parameters_changed()` 函数中的参数比较逻辑
  - 如需强制创建日志，删除或修改此判断

#### 10. "Task generator error: {e}"
- **含义**: 任务生成器出现错误
- **代码位置**: `main.py` 第 364 行
- **调试建议**:
  - 查看完整的错误堆栈信息
  - 检查 `generate_random_task()` 函数中的参数配置
  - 检查 `data_manager.add_task()` 是否正常工作

#### 11. "Background task error at iteration {iteration_count}: {e}"
- **含义**: 后台任务执行出现错误
- **代码位置**: `main.py` 第 407 行
- **调试建议**:
  - 查看完整的错误堆栈信息
  - 检查 `decision_manager.dynamic_scheduling()` 调用是否正确
  - 检查 `websocket_handler.broadcast_*()` 方法是否正常

#### 12. "WebSocket error: {e}"
- **含义**: WebSocket 连接出现错误
- **代码位置**: `main.py` 第 133 行
- **调试建议**:
  - 检查前端是否正确连接
  - 检查 WebSocket 端点配置
  - 检查 `websocket_handler` 的连接管理逻辑

#### 13. "Shutting down NEFT System..."
- **含义**: 系统正在关闭
- **代码位置**: `main.py` 第 70 行
- **调试建议**: 正常关闭信息，无需特殊处理

### 调试技巧

1. **查看详细错误**: 错误信息后会自动输出完整的堆栈跟踪
2. **调整输出频率**: 修改 `iteration_count % 10 == 0` 中的数字来调整状态输出频率
3. **关闭特定功能**: 如需调试特定功能，可以注释掉 `asyncio.create_task()` 中的某些任务
4. **添加自定义输出**: 在关键位置添加 `print()` 语句来跟踪执行流程
5. **检查日志文件**: 查看 `test/log/` 目录下的日志文件了解详细参数和任务信息
