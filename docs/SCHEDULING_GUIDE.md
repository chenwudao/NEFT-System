# 调度策略说明文档（现状版）

本文面向当前 `backend/algorithm` 实现，目标是把“调度流程”和“每个策略在做什么”讲清楚，便于后续逐个改造。

---

## 1. 调度在系统里的位置

每一轮调度的主链路如下：

1. `DynamicSchedulingModule.run_once(strategy)` 先把超时任务标记为 `TIMEOUT`。
2. 调用 `Snapshot.capture(data_manager)` 拍一张当前状态快照。
3. `AlgorithmManager.schedule(strategy, snapshot)` 根据策略名分发到具体 `Scheduler`。
4. `Scheduler.schedule(snapshot)` 输出一组 `Command`（每辆待决策车一条）。
5. `DynamicSchedulingModule._execute()` 把命令落地到 `DataManager`（启动路径、装货、充电等）。
6. 主循环推进车辆运动，到站后下一轮继续拍快照并调度。

核心特征：这是 **闭环控制**，不是预测模型。即 `state_t -> action_t -> state_(t+1)`。

---

## 2. Snapshot 提供了什么

算法只看 `Snapshot`，不直接改底层状态。常用接口：

- `vehicles_need_decision()`：当前需要发命令的车（`IDLE` 且无 target）
- `idle_vehicles_at_warehouse()`：仓库内待命车
- `idle_vehicles_not_at_warehouse()`：仓库外待命车（通常是刚送完）
- `available_tasks()`：`PENDING` 任务
- `vehicle_undelivered_tasks(v)`：车上未送达任务
- `distance(a, b)`：路网最短距离（米，带缓存）

---

## 3. 公共决策模板（所有策略共享）

大多数策略不是“从零写完整流程”，而是复用 `backend/algorithm/utils.py` 里的模板：

- `decide_at_warehouse(vehicle, snapshot, pick_tasks)`
- `decide_en_route(vehicle, snapshot)`

### 3.1 仓库内决策 `decide_at_warehouse`

统一流程：

1. 低电阈值命中（`low_battery_pct`）则先充电。
2. 调用各策略自己的 `pick_tasks(...)` 选一批候选任务。
3. 用 `feasible_task_batch_for` 再按载重过滤（不设任务数量上限）。
4. 做电量安全预判 `_need_charge_at_warehouse`：
   - 新增了“首跳安全约束”：到下一目的地后必须还能到充电站；
   - 不再做“整条链回仓”预判，避免过度保守导致可执行单被拦截。
5. 若整批不安全，尝试缩批；缩到 1 单也不安全则先充电。

### 3.2 仓库外决策 `decide_en_route`

统一流程：

1. 若低电则优先去可达充电站。
2. 若车上还有未送任务，选下一站（默认最近），并检查“到站后还能否去充电站”。
3. 若车上已无未送任务，尝试回仓；若回仓后不能继续去充电站，则先充电。

### 3.3 落地前二次兜底（执行层）

`DynamicSchedulingModule._guard_battery_before_motion` 会在命令落地前再做一次检查：

- 如果目标点/充电站当前电量不可达，会改派到“可达充电站”；
- 若连可达充电站都没有，则 `idle`，避免硬开到抛锚。

---

## 4. 策略名如何映射

配置里 `scheduling.strategy` 最终映射到 `Scheduler.name`。

当前支持多种写法（通过 `AlgorithmManager._resolve_scheduler`）：

- 短名：`deadline_earliest`
- 类名：`DeadlineEarliestScheduler`
- 去后缀类名：`DeadlineEarliest`
- 大小写/连字符变体：`DEADLINE_EARLIEST`、`deadline-earliest`

---

## 5. 全部调度方法说明（当前 9 个）

以下策略均已注册在 `backend/algorithm/schedulers/__init__.py`。

## 5.1 `nearest_task`（最近点贪心基线）

- 仓库外：走 `decide_en_route`。
- 仓库内：反复选当前最近任务构成有序批次，再交给公共模板落地。
- 优点：快、稳定、可解释性强。
- 风险：可能牺牲截止时间和高优任务。

## 5.2 `priority_task`（优先级优先）

- 任务排序：`priority` 降序，同优先级按距离近优先。
- 批量装载只受载重限制。
- 适合“高优任务必须先处理”的场景。

## 5.3 `heaviest_task`（重货优先）

- 任务排序：`weight` 降序，同重量按距离近优先。
- 目标是提升单趟载重利用率，先清理大件。
- 可能导致远距离高重量任务占据运力。

## 5.4 `deadline_earliest`（EDF 最早截止时间优先）

- 任务排序：`deadline` 升序，同 deadline 按距离近优先。
- 核心目标是提高按时率，减少超时。
- 当路网拥堵或距离很大时，需要依赖公共电量/可达性模板兜底。

## 5.5 `composite_score`（复合评分）

- 对每个任务打综合分，默认包含：
  - 优先级收益
  - 紧迫度收益（deadline 越近越高）
  - 载重收益
  - 距离惩罚
- 权重来自 `scheduling.composite_weights`。
- 适合做“多目标折中”。

## 5.6 `mst_batch`（MST 批量）

- 仓库内：先按重量贪心装一批，再让公共模板决定首跳。
- 仓库外：对车上未送任务用 `mst_order` 计算访问顺序，首跳按 MST 顺序走。
- 特点：比纯最近邻更关注整体访问结构。

## 5.7 `insertion_heuristic`（贪心插入）

- 从 `start -> warehouse` 初始路径开始。
- 迭代尝试把任务插入路径中“边际成本最优”的位置。
- 每次插入都做载重和电量链路可行性检查。
- 适合多任务批配送，通常比简单贪心更省路程。

## 5.8 `simulated_annealing`（模拟退火）

- 对“仓库待命车辆 + 可分配任务”做一次组合优化。
- 目标函数：`总距离 - alpha * 总任务得分`（得分与系统评分函数一致）。
- 邻域操作：车内交换、跨车挪单、子序列反转。
- 约束：载重 + 电量可完成链路。
- 计算开销最高，但在复杂任务集上可能给出更优批分配。

## 5.9 `random_baseline`（随机基线）

- 随机打乱候选任务后装批。
- 主要用于对比实验下界，不建议线上策略使用。

---

## 6. 当前策略的共同约束

所有策略都会受到以下硬约束（模板或执行层）：

- 载重约束：不能超 `vehicle.max_load`
- 批量约束：只受车辆最大载重约束
- 电量约束：下一站可达、链路可达、充电站可达
- 路网约束：`snapshot.distance == inf` 的不可达点会被过滤
- 防抢单：仓库派单时用 `claimed` 避免同轮重复派同一任务

---

## 7. 后续“逐个修改”建议顺序

为了便于定位效果，建议按下面顺序迭代：

1. `deadline_earliest`（最容易验证按时率变化）
2. `composite_score`（可通过权重做可控实验）
3. `insertion_heuristic`（提升批量路径质量）
4. `mst_batch`（强化外场多点访问顺序）
5. `simulated_annealing`（最后再调，避免早期开销太大）

每次改完建议固定同一 YAML（如 `configs/medium.yaml`）跑多组，对比日志中的完成率、按时率、总里程、能耗效率。

---

## 8. 你改算法时的最小改动点

如果要新增/改造一个策略，优先只改这三处：

1. `backend/algorithm/schedulers/<your_strategy>.py`
2. `backend/algorithm/schedulers/__init__.py`（注册）
3. `configs/*.yaml` 的 `scheduling.strategy`（切换策略）

只要继续复用 `decide_at_warehouse / decide_en_route`，就能自动继承当前的充电和安全兜底规则。

