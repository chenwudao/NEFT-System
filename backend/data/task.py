from typing import List, Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from .position import Position

class TaskStatus(Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    TIMEOUT = "timeout"

@dataclass
class Task:
    id: int
    position: Position
    weight: float
    create_time: int
    deadline: int
    priority: int
    status: TaskStatus = TaskStatus.PENDING
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
            "start_time": self.start_time,
            "complete_time": self.complete_time,
            "complete_path": [{"x": p.x, "y": p.y} for p in self.complete_path],
            "complete_path_distance": self.complete_path_distance,
            "estimated_completion_time": self.estimated_completion_time,
            "score": self.score,
            "is_on_time": self.is_on_time
        }
