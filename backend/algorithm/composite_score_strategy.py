from typing import List, Dict
from .scheduling_strategy import SchedulingStrategy
from backend.data.task import Task, TaskStatus
from backend.data.vehicle import Vehicle


class CompositeScoreStrategy(SchedulingStrategy):
    """
    多参数综合评分策略（Composite Score，用户定制方案）。
    对每个（车辆, 任务）对计算综合评分，评分越高越优先处理。

    评分维度（自适应权重）：
      - weight    任务重量（重货优先，充分利用车辆载重）
      - distance  到任务距离（近的优先，减少空驶）
      - priority  任务优先级（高优先级优先）
      - urgency   紧迫程度（deadline 越近越优先）

    自适应逻辑：
      - urgent_ratio > 0.3  → 紧急模式（urgency/priority 权重提升）
      - heavy_ratio > 0.5   → 重载模式（weight/distance 权重提升）
      - 否则                → 均衡模式（默认）
    """

    # 均衡模式（默认）
    DEFAULT_WEIGHTS = {"weight": 0.30, "distance": 0.30, "priority": 0.25, "urgency": 0.15}
    # 紧急任务较多时
    URGENT_WEIGHTS  = {"weight": 0.15, "distance": 0.15, "priority": 0.30, "urgency": 0.40}
    # 重载任务较多时
    HEAVY_WEIGHTS   = {"weight": 0.40, "distance": 0.30, "priority": 0.20, "urgency": 0.10}

    URGENT_DEADLINE_WINDOW = 1800   # 30min 内视为紧急
    MAX_DEADLINE_WINDOW    = 7200   # 2h 内的任务，超出视为充裕

    def _compute_adaptive_weights(self) -> dict:
        """根据当前任务结构动态选择权重组合"""
        pending_only = [t for t in self.pending_tasks if t.status == TaskStatus.PENDING]
        if not pending_only:
            return self.DEFAULT_WEIGHTS

        current_timestamp = self.global_params.get("timestamp", 0)
        total = len(pending_only)

        urgent_count = sum(
            1 for t in pending_only
            if (t.deadline - current_timestamp) < self.URGENT_DEADLINE_WINDOW
        )
        urgent_ratio = urgent_count / total

        weights = [t.weight for t in pending_only]
        avg_weight = sum(weights) / len(weights)
        heavy_count = sum(1 for w in weights if w > avg_weight * 0.8)
        heavy_ratio = heavy_count / total

        if urgent_ratio > 0.3:
            return self.URGENT_WEIGHTS
        elif heavy_ratio > 0.5:
            return self.HEAVY_WEIGHTS
        else:
            return self.DEFAULT_WEIGHTS

    def sort_tasks(self, vehicle: Vehicle, feasible_tasks: List[Task]) -> List[Task]:
        if not feasible_tasks:
            return []

        w = self._compute_adaptive_weights()
        current_timestamp = self.global_params.get("timestamp", 0)

        # 归一化分母
        max_weight = max(t.weight for t in feasible_tasks) or 1.0
        distances = []
        for t in feasible_tasks:
            try:
                dist = self.path_calculator.calculate_distance_from_positions(
                    [vehicle.position, t.position]
                )
                distances.append(dist)
            except Exception:
                # 路径不可达，使用无穷大距离（排在最后）
                distances.append(float('inf'))
        max_dist = max(d for d in distances if d < float('inf')) or 1.0

        def composite_score(task: Task, dist: float) -> float:
            norm_weight   = task.weight / max_weight
            norm_distance = 1.0 - (dist / max_dist)  # 距离越近 → 得分越高
            norm_priority = task.priority / 5.0
            remaining     = max(0, task.deadline - current_timestamp)
            norm_urgency  = 1.0 - min(1.0, remaining / self.MAX_DEADLINE_WINDOW)  # 越急 → 越高

            return (
                w["weight"]   * norm_weight
              + w["distance"] * norm_distance
              + w["priority"] * norm_priority
              + w["urgency"]  * norm_urgency
            )

        scored = [
            (task, composite_score(task, dist))
            for task, dist in zip(feasible_tasks, distances)
        ]
        scored.sort(key=lambda x: x[1], reverse=True)  # 得分越高越优先
        return [task for task, _ in scored]

    def execute(self) -> List[Dict]:
        for vehicle in self.idle_vehicles:
            if vehicle.id in self.assigned_vehicle_ids:
                continue
            self.generate_vehicle_command(vehicle)
            self.assigned_vehicle_ids.add(vehicle.id)

        return self.commands
