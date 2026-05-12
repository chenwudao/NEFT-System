"""
统一的评分配置

所有调度算法（实时调度、静态规划）使用相同的评分参数，
确保评估标准一致性。

参考：meta_strategy_selector.py 的评分公式
"""

# 任务分配评分参数
TASK_ASSIGN_REWARD = 120.0          # 分配一个任务的奖励
PRIORITY_REWARD = 30.0              # 每点优先级的奖励
DISTANCE_PENALTY = 0.02             # 每米距离的惩罚
ENERGY_PENALTY = 0.2                # 每单位能耗的惩罚
OVERDUE_PENALTY_PER_MIN = 50.0      # 每分钟逾期的惩罚
IDLE_PENALTY = 5.0                  # 车辆空闲的惩罚

# 速度假设（用于估算完成时间）
ASSUMED_SPEED_MPS = 10.0            # 假设平均速度 10m/s

# 时间窗口配置（与 CompositeScoreStrategy 对齐）
URGENT_DEADLINE_WINDOW = 1800       # 30分钟内视为紧急
MAX_DEADLINE_WINDOW = 7200          # 2小时内的任务


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
        current_timestamp: 当前时间戳
    
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
    
    # 4. 能耗惩罚
    energy_cost = round_trip_dist * vehicle.unit_energy_consumption * ENERGY_PENALTY
    
    # 5. 逾期惩罚
    estimated_time = round_trip_dist / ASSUMED_SPEED_MPS
    expected_finish = current_timestamp + estimated_time
    overdue_minutes = max(0, expected_finish - task.deadline) / 60.0
    overdue_cost = overdue_minutes * OVERDUE_PENALTY_PER_MIN
    
    # 综合得分
    score = task_reward + priority_reward - distance_cost - energy_cost - overdue_cost
    
    return score


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
        current_timestamp: 当前时间戳
    
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
            - total_energy * ENERGY_PENALTY
            - overdue_penalty * OVERDUE_PENALTY_PER_MIN
        )
    }
