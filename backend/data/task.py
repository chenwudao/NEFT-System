from typing import List, Dict, Optional, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from .position import Position

class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    TIMEOUT = "timeout"

@dataclass
class Task:
    """一件"货物"。
    重构后的模型：车和货是两个东西，车是货的"载体"。
      - Task 描述的是货物本身：它要去哪（position）、多重、什么时候必须送到。
      - Task.status 描述的是"货"的状态：还在仓库待分配(PENDING)、
        运输中(IN_PROGRESS)、已送达任务点(COMPLETED)、还是过期作废(TIMEOUT)。
      - `assigned_vehicle_id` 表示"当前背着这个货的车"——接力场景下这个值会变化。
        这个字段在 to_dict 里也同时以 `carrier_vehicle_id` 导出，语义等价。
    """
    id: int
    position: Position
    weight: float
    create_time: int
    deadline: int
    priority: int
    status: TaskStatus = TaskStatus.PENDING
    # 当前持有该货物的车辆；None 表示"还在仓库 / 已经卸在目的地 / 已完结"。
    # 接力时这个字段会从"原承运车"被改为"接力车"。
    assigned_vehicle_id: Optional[int] = None
    start_time: Optional[int] = None
    complete_time: Optional[int] = None
    # 完整路径相关字段
    complete_path: List[Position] = field(default_factory=list)
    complete_path_distance: float = 0.0
    estimated_completion_time: float = 0.0
    score: float = 0.0
    is_on_time: bool = True

    def get_position(self) -> Position:
        return self.position

    def get_weight(self) -> float:
        return self.weight

    def get_deadline(self) -> int:
        return self.deadline

    def update_status(self, status: TaskStatus):
        self.status = status
        if status == TaskStatus.IN_PROGRESS and self.start_time is None:
            self.start_time = int(datetime.now().timestamp())
        elif status == TaskStatus.COMPLETED and self.complete_time is None:
            self.complete_time = int(datetime.now().timestamp())

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "position": {"x": self.position.x, "y": self.position.y},
            "weight": self.weight,
            "create_time": self.create_time,
            "deadline": self.deadline,
            "priority": self.priority,
            "status": self.status.value,
            "assigned_vehicle_id": self.assigned_vehicle_id,
            "carrier_vehicle_id":  self.assigned_vehicle_id,  # 语义别名：当前承运车
            "start_time": self.start_time,
            "complete_time": self.complete_time,
            "complete_path": [{"x": p.x, "y": p.y} for p in self.complete_path],
            "complete_path_distance": self.complete_path_distance,
            "estimated_completion_time": self.estimated_completion_time,
            "score": self.score,
            "is_on_time": self.is_on_time
        }


def apply_deadline_timeouts(tasks: Iterable[Task], current_timestamp: int) -> None:
    """Mark overdue PENDING tasks as TIMEOUT (single place for realtime + meta evaluation)."""
    for task in tasks:
        if task.status == TaskStatus.PENDING and task.deadline < current_timestamp:
            task.update_status(TaskStatus.TIMEOUT)
