"""调度算法的统一接口。

重构后的语义（必读）：
    - 算法的输入：一张整体快照 `Snapshot`。
    - 算法的输出：对每辆"需要决策"的车给出一个 `Command`——
      即"下一步去哪个节点、去做什么"。
    - 从当前 position 到 `target_xy` 的最短路径由底层（Dijkstra）自动算出，
      算法不管具体走哪条路。
    - 到达目的地后会再次调用调度器决定下下步，因此"批量送货"天然靠
      多次调度拼起来；算法里不需要关心"车还在路上时"的事。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .snapshot import Snapshot


# ===========================================================================
# Command：算法的唯一输出
# ===========================================================================

# 合法 action 枚举值。直接用字符串以降低调用方耦合。
ACTION_DELIVER   = "deliver"     # 去送下一个任务点（可能同时在仓库装新货）
ACTION_GOTO_NODE = "goto_node"   # 去一个"特殊坐标"：MST 汇聚点 / 接力碰头点 / 任何非业务节点
ACTION_CHARGE    = "charge"      # 去充电站
ACTION_RETURN    = "return"      # 回中心仓库（卸货 / 刷新任务）
ACTION_HANDOFF   = "handoff"     # 与另一辆"同位置车"交换 / 交接货物（原地不动）
ACTION_IDLE      = "idle"        # 停在原地

VALID_ACTIONS = {
    ACTION_DELIVER, ACTION_GOTO_NODE, ACTION_CHARGE,
    ACTION_RETURN, ACTION_HANDOFF, ACTION_IDLE,
}


@dataclass
class Command:
    """一个"下一步命令"。

    字段使用速查：
        deliver    : target_xy + task_id (+ assigned_tasks 用于在仓库批量装货)
        goto_node  : target_xy   （纯粹"把车挪到这个坐标"，不涉及业务交互）
        charge     : target_xy + station_id
        return     : target_xy
        handoff    : target_vehicle_id + task_ids_to_transfer
                     （原地执行，要求两辆车已经在同一坐标）
        idle       : (无额外字段)
    """

    vehicle_id: int
    action: str                               # VALID_ACTIONS 之一
    target_xy: Optional[Tuple[float, float]] = None

    # 在仓库装新货时，`assigned_tasks` 列出要上车的任务 id；
    # 其他场景（半路跳到下一个任务点）留空。
    assigned_tasks: List[int] = field(default_factory=list)

    # action=deliver 时，当前这一跳要去送的具体是哪个 task
    task_id: Optional[int] = None
    # action=charge 时目标充电站
    station_id: Optional[str] = None

    # action=handoff 时：把货交给哪辆车 + 要转交的任务 id 列表
    target_vehicle_id: Optional[int] = None
    task_ids_to_transfer: List[int] = field(default_factory=list)

    def __post_init__(self):
        if self.action not in VALID_ACTIONS:
            raise ValueError(f"Unknown command action: {self.action}")

    def to_dict(self) -> Dict:
        return {
            "vehicle_id": self.vehicle_id,
            "action": self.action,
            "target_xy": (
                {"x": self.target_xy[0], "y": self.target_xy[1]}
                if self.target_xy is not None
                else None
            ),
            "assigned_tasks": list(self.assigned_tasks),
            "task_id": self.task_id,
            "station_id": self.station_id,
            "target_vehicle_id": self.target_vehicle_id,
            "task_ids_to_transfer": list(self.task_ids_to_transfer),
        }


# ===========================================================================
# Scheduler：所有算法的基类
# ===========================================================================


class Scheduler(ABC):
    """所有调度算法统一继承。

    实现一个新算法的 5 分钟模板（详见 README）：
        class MyScheduler(Scheduler):
            name = "my_algo"
            def schedule(self, snapshot):
                commands = []
                for vehicle in snapshot.vehicles_need_decision():
                    # ... 自己挑个任务 / 决定去充电 / 回仓库 ...
                    commands.append(utils.make_deliver_command(...))
                return commands
    """

    #: 算法名，用于在 config.SCHEDULING_CONFIG["strategy"] 里选中。
    name: str = ""

    @abstractmethod
    def schedule(self, snapshot: Snapshot) -> List[Command]:
        """根据快照产出每辆"需要决策"车辆的下一步命令。"""
        raise NotImplementedError
