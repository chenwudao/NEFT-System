# 调度策略说明文档（规划增强版）

本文面向当前 `backend/algorithm` 实现，重点说明：调度闭环、通用约束、以及每个策略的可执行流程（含 DFS、元启发式、强化学习、超启发式、多智能体）。

---

## 1. 调度在系统里的位置

每一轮调度主链路：

1. `DynamicSchedulingModule.run_once(strategy)` 处理超时任务。
2. `Snapshot.capture(data_manager)` 拍快照。
3. `AlgorithmManager.schedule(strategy, snapshot)` 分发策略。
4. `Scheduler.schedule(snapshot)` 输出每车一条 `Command`。
5. `_execute()` 落地命令，推进车辆状态。
6. 主循环推进移动，到点后进入下一轮。

本系统是闭环在线决策：`state_t -> action_t -> state_(t+1)`。

---

## 2. 快照与通用模板

算法只读 `Snapshot`，常用接口：

- `idle_vehicles_at_warehouse()`：仓库内可派单车辆
- `idle_vehicles_not_at_warehouse()`：仓库外待命车辆
- `available_tasks()`：`PENDING` 任务
- `vehicle_undelivered_tasks(v)`：车上未完成任务
- `distance(a, b)`：路网最短距离

所有策略统一复用：

- `decide_at_warehouse(vehicle, snapshot, pick_tasks)`
- `decide_en_route(vehicle, snapshot)`

模板自动继承：

- 低电量先充电
- 首跳安全（到目标后还能到充电站）
- 执行层二次电量兜底（不可达则改派充电/待机）

---

## 3. 策略名映射规则

`scheduling.strategy` 支持短名、类名、去后缀类名、大小写与连字符变体，例如：

- `deadline_earliest`
- `DeadlineEarliestScheduler`
- `DeadlineEarliest`
- `DEADLINE-EARLIEST`

---

## 4. 动态/静态模式

通过 `optimization.mode` 切换：

- `dynamic`：在线动态调度（默认），任务按时间流入。
- `static`：上帝视角静态优化，任务全集在仿真开始时已知。

静态模式推荐配置：

- `optimization.static.strategy: static_exact_solver`
- `optimization.static.solver: gurobi | cplex`
- `optimization.static.max_exact_tasks: 10`（精确搜索任务上限）

---

## 5. 全部调度方法（动态 + 静态）

以下策略均已注册在 `backend/algorithm/schedulers/__init__.py`。

### 5.1 基础启发式（快速基线）

- `nearest_task`：按最近距离逐个装单，直到不可行。
- `priority_task`：按优先级降序逐个装单，直到不可行。
- `heaviest_task`：按重量降序逐个装单，直到不可行。
- `deadline_earliest`：按截止时间升序逐个装单，直到不可行。
- `random_baseline`：随机顺序基线（对照组）。

### 5.2 结构化路径策略

- `mst_batch`：MST + DFS 顺序，强调整体路网结构。

- `insertion_heuristic`（进阶插入）：
  1. 初始化路径 `start`；
  2. 对每个候选任务计算最佳/次佳插入位置；
  3. 用 regret-2（次佳代价 - 最佳代价）选“错过损失最大”的任务；
  4. 插入后做轻量 2-opt 局部优化；
  5. 每步用充电可达约束验证可行性。

### 5.3 评分规划策略

- `composite_score`（复合评分规划）：
  1. 单任务打分（优先级+紧迫度+载重-距离）；
  2. 取 top-k 候选；
  3. 在 top-k 上做 beam DFS（保留前 `beam_width` 状态）；
  4. 目标函数：`总评分 - 距离惩罚`；
  5. 输出最优集合并给出有序路径。

- `dfs_score_search`（DFS 评分搜索）：
  1. DFS 枚举候选子集（按载重剪枝）；
  2. 每个子集用 `greedy_chain` 生成访问序；
  3. 用 `estimate_chain_distance_with_recharge` 校验可行；
  4. 目标函数：`assignment_score 累计 - 距离惩罚`；
  5. 选全局最优可行子集。

### 5.4 元启发式方法（Meta-heuristics）

- `simulated_annealing`（模拟退火）：
  1. 初始解：按优先级/距离构造车辆-任务分配；
  2. 邻域：车内交换、跨车挪单、子序列反转；
  3. 目标：`总距离 - alpha * 总任务得分`；
  4. 以温度控制接受概率，允许早期“爬山下坡”；
  5. 长时间无改进触发轻微重热避免早熟。

- `tabu_search`（禁忌搜索）：
  1. 构造可行初始序列；
  2. 邻域使用交换操作；
  3. 用 tabu 表记录近期 move，抑制回退；
  4. 使用特赦准则允许“打破禁忌”的全局改进；
  5. 输出当前最优可行序列。

### 5.5 超启发式方法（Hyper-heuristics）

- `hyper_heuristic`（UCB1）：
  1. 把 `nearest/priority/deadline/heaviest` 作为低层算子；
  2. 用 UCB1 在“算子平均收益 + 探索奖励”上选算子；
  3. 执行并回写 reward；
  4. 动态偏向近期有效算子。

- `hyper_heuristic_eps`（epsilon-greedy）：
  1. 同样使用低层算子池；
  2. 以 `epsilon` 概率探索随机算子；
  3. 否则选择当前平均奖励最高算子；
  4. 在线更新算子价值。

### 5.6 强化学习方法（Reinforcement Learning）

- `q_learning`（在线表格型强化学习）：
  1. 状态离散：电量桶、载重利用率桶、候选数桶；
  2. 动作：选择下一任务加入批次；
  3. 策略：`epsilon-greedy`；
  4. 奖励：优先级收益 - 距离惩罚 - 逾期风险；
  5. 在线更新 `Q(s,a)`，逐轮自适应。

### 5.7 多智能体方法（Multi-agent）

- `multi_agent_auction`（拍卖分配）：
  1. 每车对每任务计算 bid（收益-成本）；
  2. 每个任务分配给最高 bid 车辆；
  3. 车内再做路径排序与可行性裁剪；
  4. 形成并行多车批配送方案。

- `multi_agent_contract_net`（合同网协议）：
  1. 管理者广播任务；
  2. 车辆 agent 报价；
  3. 逐轮授标给当前最高 bid agent；
  4. 每车本地排序并做可行性裁剪后下发指令。

### 5.8 静态全局优化方法（Static Oracle）

- `static_exact_solver`：
  1. 任务全集已知后一次性构建全局分配；
  2. 优先尝试调用 Gurobi/CPLEX 做任务-车辆分配；
  3. 车内路径采用精确枚举（小规模）或近似（大规模）；
  4. 生成全局计划后按序执行，并与动态策略结果对比。

---

## 6. 共同硬约束

所有策略统一受以下约束：

- 载重：`<= vehicle.max_load`
- 任务数量：不设上限，仅受载重限制
- 电量：到下一目标可达，且目标后可到充电站
- 路网：不可达边自动过滤（`distance == inf`）
- 防抢单：同轮用 `claimed` 避免重复派发

---

## 7. 推荐实验对比

建议固定同一配置（如 `configs/medium.yaml`）跑多组，比较：

- 完成率 / 按时率
- 平均任务完成时长
- 总里程与能耗效率
- 超时任务占比
- 算法运行耗时（调度开销）

建议从 `nearest_task` 和 `deadline_earliest` 作为基线，再对比 `composite_score / dfs_score_search / simulated_annealing / q_learning / multi_agent_auction`。

