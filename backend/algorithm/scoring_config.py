"""
统一的评分配置

所有调度算法（实时调度、静态规划）使用相同的评分参数，
确保评估标准一致性。

参考：meta_strategy_selector.py 的评分公式
"""

from backend.config import config

# 从 YAML/config 读取评分参数；未配置时沿用默认值。
_SCORING = config.get_scoring_config()

# 任务分配评分参数
TASK_ASSIGN_REWARD = float(_SCORING.get("task_assign_reward", 120.0))  # 分配一个任务的奖励
PRIORITY_REWARD = float(_SCORING.get("priority_reward", 30.0))  # 每点优先级的奖励
DISTANCE_PENALTY = float(_SCORING.get("distance_penalty", 0.02))  # 每米距离的惩罚
EARLY_COMPLETION_REWARD_PER_MIN = float(
    _SCORING.get("early_completion_reward_per_min", 2.0)
)  # 每分钟提前完成奖励（弱于逾期惩罚）
OVERDUE_PENALTY_PER_MIN = float(
    _SCORING.get("overdue_penalty_per_min", 50.0)
)  # 每分钟逾期的惩罚
IDLE_PENALTY = float(_SCORING.get("idle_penalty", 5.0))  # 车辆空闲的惩罚

# 速度假设（用于估算完成时间）
ASSUMED_SPEED_MPS = float(_SCORING.get("assumed_speed_mps", 10.0))  # 假设平均速度 10m/s

# 时间窗口配置（与 CompositeScoreStrategy 对齐）
URGENT_DEADLINE_WINDOW = int(_SCORING.get("urgent_deadline_window", 1800))  # 30分钟内视为紧急
MAX_DEADLINE_WINDOW = int(_SCORING.get("max_deadline_window", 7200))  # 2小时内的任务


def calculate_assignment_score(
    task,
    vehicle,
    distance: float,
    current_timestamp: int
) -> float:
    """
    计算任务分配的得分（与实时调度统一的评分公式）
    
    Args:
        task: 任务对象
        vehicle: 车辆对象
        distance: 单程距离（米）
        current_timestamp: 当前仿真时刻（秒）
    
    Returns:
        综合评分（越高越好）
    """
    # 往返距离
    round_trip_dist = 2 * distance
    
    # 1. 任务分配奖励
    task_reward = TASK_ASSIGN_REWARD
    
    # 2. 优先级奖励
    priority_reward = task.priority * PRIORITY_REWARD
    
    # 3. 距离惩罚
    distance_cost = round_trip_dist * DISTANCE_PENALTY
    
    # 4. 提前完成奖励 + 逾期惩罚
    estimated_time = round_trip_dist / ASSUMED_SPEED_MPS
    expected_finish = current_timestamp + estimated_time
    early_minutes = max(0, task.deadline - expected_finish) / 60.0
    early_reward = early_minutes * EARLY_COMPLETION_REWARD_PER_MIN
    overdue_minutes = max(0, expected_finish - task.deadline) / 60.0
    overdue_cost = overdue_minutes * OVERDUE_PENALTY_PER_MIN
    
    # 综合得分
    score = task_reward + priority_reward - distance_cost + early_reward - overdue_cost
    return max(0.0, float(score))


def calculate_batch_chain_score(
    ordered_tasks,
    vehicle,
    snapshot,
    current_timestamp: int,
) -> float:
    """按访问顺序估算一批任务的累计得分（与 calculate_task_score 公式一致）。

    对每个任务依次估算：
      - 到达时刻 = 当前时刻 + 路段耗时（距离 / assumed_speed）
      - 距离惩罚基于从起点到该任务点的累计路径长度
    """
    if not ordered_tasks:
        return 0.0

    cur_ts = float(current_timestamp)
    cur_xy = (float(vehicle.position.x), float(vehicle.position.y))
    cumulative_dist = 0.0
    total_score = 0.0

    for task in ordered_tasks:
        leg = snapshot.distance(cur_xy, task.position)
        if leg == float("inf"):
            return float("-inf")

        cumulative_dist += float(leg)
        travel_time = float(leg) / ASSUMED_SPEED_MPS if ASSUMED_SPEED_MPS > 0 else float("inf")
        completion_time = cur_ts + travel_time

        task_reward = TASK_ASSIGN_REWARD
        priority_reward = float(getattr(task, "priority", 1)) * PRIORITY_REWARD
        distance_cost = cumulative_dist * DISTANCE_PENALTY
        early_minutes = max(0.0, float(task.deadline) - completion_time) / 60.0
        early_reward = early_minutes * EARLY_COMPLETION_REWARD_PER_MIN
        overdue_minutes = max(0.0, completion_time - float(task.deadline)) / 60.0
        overdue_cost = overdue_minutes * OVERDUE_PENALTY_PER_MIN

        total_score += max(
            0.0,
            task_reward + priority_reward - distance_cost + early_reward - overdue_cost,
        )

        cur_ts = completion_time
        cur_xy = (float(task.position.x), float(task.position.y))

    return total_score


def calculate_plan_score(
    assignments: dict,
    task_by_id: dict,
    vehicle_by_id: dict,
    distance_matrix: dict,
    current_timestamp: int
) -> dict:
    """
    计算整个规划方案的得分（用于静态规划评估）
    
    Args:
        assignments: {vehicle_id: [task_id, ...]}
        task_by_id: {task_id: task_object}
        vehicle_by_id: {vehicle_id: vehicle_object}
        distance_matrix: {(vehicle_id, task_id): distance}
        current_timestamp: 当前仿真时刻（秒）
    
    Returns:
        包含各项评分的字典
    """
    assigned_tasks = 0
    total_priority = 0.0
    total_distance = 0.0
    total_energy = 0.0
    overdue_penalty = 0.0
    total_score = 0.0
    
    for v_id, task_ids in assignments.items():
        vehicle = vehicle_by_id.get(v_id)
        if not vehicle:
            continue
            
        for task_id in task_ids:
            task = task_by_id.get(task_id)
            if not task:
                continue
                
            assigned_tasks += 1
            total_priority += task.priority
            
            dist = distance_matrix.get((v_id, task_id), 0)
            total_distance += dist
            total_energy += dist * vehicle.unit_energy_consumption
            
            # 计算该分配的得分
            score = calculate_assignment_score(task, vehicle, dist, current_timestamp)
            total_score += score
            
            # 逾期惩罚
            round_trip_dist = 2 * dist
            estimated_time = round_trip_dist / ASSUMED_SPEED_MPS
            expected_finish = current_timestamp + estimated_time
            if expected_finish > task.deadline:
                overdue_minutes = (expected_finish - task.deadline) / 60.0
                overdue_penalty += overdue_minutes
    
    return {
        "assigned_tasks": assigned_tasks,
        "total_priority": total_priority,
        "total_distance": total_distance,
        "total_energy": total_energy,
        "overdue_penalty": overdue_penalty,
        "total_score": total_score,
        "raw_score": (
            assigned_tasks * TASK_ASSIGN_REWARD
            + total_priority * PRIORITY_REWARD
            - total_distance * DISTANCE_PENALTY
            - overdue_penalty * OVERDUE_PENALTY_PER_MIN
        )
    }
