# 仓库装批：最大可行解与电量判定

本文档定义动态调度中**仓库装货（装批）**阶段共用的可行性标准，适用于：

- 四个贪心基线（`nearest_task` / `priority_task` / `heaviest_task` / `deadline_earliest`）的贪心装批
- `dfs_score_search`（DFS 枚举最大可行装批）
- `sa_score_search`（SA 在最大可行装批空间内搜最高分）

实现参考：`backend/algorithm/utils.py`、`backend/algorithm/schedulers/dfs_score_search.py`、`backend/algorithm/schedulers/sa_score_search.py`。

---

## 1. 装批在说什么

某辆车在**仓库**、准备接新任务时，从当前 `PENDING` 且未被其他车认领的任务池中，选一组任务装上车。

一组任务称为一个**装批方案**（batch）。  
DFS / SA 只在**最大可行装批**中比较得分；贪心算法按各自排序规则构造**最大可行前缀**（与最大可行定义兼容，但不一定枚举所有最大可行解）。

---

## 2. 可行解（Feasible Batch）

一批任务 `{t1, t2, …}` 称为**可行**，当且仅当同时满足：

### 2.1 载重约束

```
Σ task.weight ≤ vehicle.get_remaining_load()
```

单件装不下的任务在进入装批搜索前即被 `feasible_tasks_for` 过滤。

### 2.2 电量约束（任务链）

1. 用 `greedy_chain` 从仓库位置出发，对批内任务点做贪心 TSP 排序，得到访问顺序。
2. 用 `estimate_chain_distance_with_recharge` 模拟整链是否可完成（**允许中途去充电站**，见第 3 节）。
3. 若返回 `float("inf")`，则该装批**不可行**。

相关函数：

- `utils.greedy_chain(start_xy, points, snapshot)`
- `utils.estimate_chain_distance_with_recharge(vehicle, waypoints, snapshot, require_final_station_buffer=True)`

---

## 3. 电量判定的两个条件（每一段 / 每一跳）

装批与派单共用同一套电量语义。对「当前位置 → 下一任务点」的**每一段**（或派单时的**首跳**），按以下顺序判断。

安全系数：`battery_safety_margin`，默认 **1.15**（15% 余量）。  
充电目标电量：`charge_until_pct`，默认 **90%**（满电为 `max_battery` 的 90%）。

### 条件 A — 直达（优先）

当前电量是否满足：

```
当前电量 ≥ energy(当前位置 → 下一任务点 + 下一任务点 → 最近充电站) × 1.15
```

说明：

- 「下一任务点 → 最近充电站」是 **buffer**，避免送到任务点后无法去充电。
- 中间每个任务点都要留 buffer；**最后一个任务点**在装批模拟中也留 buffer（`require_final_station_buffer=True`）。
- 实现：`utils._energy_to_target_with_buffer(..., require_station_buffer=True)` / `can_reach_target(..., require_station_buffer=True)`。

若条件 A 成立 → 该段视为可达，扣减本段路程能耗，继续下一段。

### 条件 B — 过渡充电（A 不成立时）

若直达不够，再判断是否存在某充电站 `S`，使得：

```
(1) 当前电量 ≥ energy(当前位置 → S) × 1.15
(2) 充到 90% 后电量 ≥ energy(S → 下一任务点 + 下一任务点 → 最近充电站) × 1.15
```

说明：

- 装批模拟（`estimate_chain_distance_with_recharge`）：选中转站后，电量设为 **90%**，再重试同一段；整链逐段模拟，可多段多次过渡。
- 派单决策（`best_transit_station_for_target`）：同样逻辑，用于决定「是否先 `charge` 再送」。
- 若 **90% 仍无法满足 (2)** → 该段 / 该装批判为不可行。

### 决策流程（单段）

```
尝试条件 A（直达 + buffer）
    ├─ 成立 → 走到下一任务点，继续
    └─ 不成立 → 尝试条件 B（经充电站 S 过渡，充到 90%）
            ├─ 成立 → 先到 S 充电，再重试该段
            └─ 不成立 → 不可行
```

---

## 4. 最大可行解（Maximal Feasible Batch）

在候选任务池 `pool`（当前车能单件装下的未认领 `PENDING` 任务）中，一个装批方案 `B` 称为**最大可行**，当且仅当：

1. **`B` 本身是可行解**（满足第 2 节载重 + 电量）。
2. **极大性**：对 `pool` 中任意任务 `t`，若 `t ∉ B` 且 `t` 单件载重可加入，则 `B ∪ {t}` **不可行**（载重或电量任一不满足）。

换句话说：

> 已经装上的货之后，**再也装不进候选池里任何其他单件任务**，且当前方案电量/载重合法。

形式化：

```
∀ t ∈ pool \ B:
    若 weight(t) ≤ remaining_load(B):
        则 B ∪ {t} 不是可行解
```

DFS / SA 的搜索目标：在**所有最大可行装批**中，取得分（`calculate_batch_chain_score`）最高者。

---

## 5. 与派单阶段的关系

| 阶段 | 作用 | 电量检查范围 |
|------|------|----------------|
| **装批** | 决定装哪些任务上车 | 整链 `estimate_chain_distance_with_recharge`（含多段 A/B） |
| **派单** | `decide_at_warehouse` 发出第一条 `deliver` | 仅再检查**首跳**（条件 A，不行则条件 B 改去充电） |
| **路上** | `decide_en_route` | 每一跳同样用条件 A / B |

装批已判定整链可行时，车应**带货出发**；路上电不够时由 `decide_en_route` 自动去充电，无需在仓库空车先充电（`nearest_task` 在仓库 additionally 只在低电量阈值时充电）。

---

## 6. 得分（DFS / SA 优化目标）

在最大可行装批中，用 `calculate_batch_chain_score` 对 `greedy_chain` 排序后的任务链估分，与最终任务结算公式一致：

```
单任务得分 = 120（分配奖励）
           + 30 × priority
           - 0.02 × 到该任务的累计路径
           + 2 × 提前完成分钟
           - 50 × 逾期分钟
```

批得分 = 批内各任务得分之和。DFS 枚举取最高；SA 模拟退火近似取最高。

---

## 7. 配置项速查

```yaml
scheduling:
  low_battery_pct: 20.0          # 低于此百分比认为需要充电（needs_charge）
  charge_until_pct: 90.0         # 过渡充电/充电完成目标（90% max_battery）
  battery_safety_margin: 1.15    # 电量安全系数
```

---

## 8. 下一对话可引用的摘要

**最大可行装批** = 载重可行 + 整链电量可行（含 90% 过渡充电模拟）+ 候选池中无法再装入任何其他单件任务。

**电量两条件**（每一段）：

1. **直达**：当前电量够「到任务点 + 任务点到最近充电站」（×1.15）。
2. **过渡**：否则，当前够到某充电站（×1.15），且充到 **90%** 后够「充电站 → 任务点 → 最近充电站」（×1.15）。
