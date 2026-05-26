"""调度算法注册中心。

唯一职责：按名字分发给具体的 Scheduler 实现。对外只暴露：
    - schedule(name, snapshot) -> List[Command]
    - get_available_strategies() -> List[str]
    - register(scheduler)       运行时追加自定义算法

加新算法的流程：
    1. 在 backend/algorithm/schedulers/ 下新增一个文件，实现 Scheduler 子类；
    2. 在 schedulers/__init__.py 把它加入 EXPORTED_SCHEDULERS；
    3. 把 config.SCHEDULING_CONFIG["strategy"] 改成它的 name。

不在代码里做"auto 选择"，策略固定由 config.py 给出。
"""

import re
from typing import Dict, List, Optional

from backend.data.path_calculator import PathCalculator

from .scheduler import Command, Scheduler
from .schedulers import EXPORTED_SCHEDULERS
from .snapshot import Snapshot


class AlgorithmManager:
    """算法注册中心。"""

    #: 找不到 config 里指定的算法时的兜底
    DEFAULT_STRATEGY = "nearest_task"

    def __init__(self, path_calculator: PathCalculator):
        # path_calculator 现在由 Snapshot 携带给算法，这里保留一个引用只是
        # 兼容既有的调用方（例如 main.py）。
        self.path_calculator = path_calculator
        self._registry: Dict[str, Scheduler] = {}
        self._build_registry()

    # ------------------------------------------------------------------
    # 注册与查询
    # ------------------------------------------------------------------
    def _build_registry(self) -> None:
        for cls in EXPORTED_SCHEDULERS:
            self.register(cls())

    def register(self, scheduler: Scheduler) -> None:
        if not scheduler.name:
            raise ValueError(
                f"Scheduler {type(scheduler).__name__} 必须设置非空的 name"
            )
        self._registry[scheduler.name] = scheduler

    def get_available_strategies(self) -> List[str]:
        return list(self._registry.keys())

    def _resolve_scheduler(self, strategy: str) -> Optional[Scheduler]:
        """解析 strategy 名称，支持多种写法：

        1) 标准短名：deadline_earliest
        2) 类名：DeadlineEarliestScheduler
        3) 类名去后缀：DeadlineEarliest
        4) 大小写不敏感：DEADLINE_EARLIEST / deadlineEarliest
        """
        if not strategy:
            return None

        # 1) 直接命中（现有行为）
        direct = self._registry.get(strategy)
        if direct is not None:
            return direct

        # 2) 统一转 snake_case 再尝试命中
        norm = str(strategy).strip()
        if norm.endswith("Scheduler"):
            norm = norm[: -len("Scheduler")]
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", norm).replace("-", "_").lower()
        snake = re.sub(r"_+", "_", snake).strip("_")
        if snake:
            by_snake = self._registry.get(snake)
            if by_snake is not None:
                return by_snake

        # 3) 最后兜底：逐个比较类名（大小写不敏感）
        lower_raw = str(strategy).strip().lower()
        for sch in self._registry.values():
            cls_name = type(sch).__name__.lower()
            if lower_raw == cls_name:
                return sch
            if lower_raw.endswith("scheduler") and lower_raw == cls_name:
                return sch
            if lower_raw == cls_name[: -len("scheduler")] and cls_name.endswith("scheduler"):
                return sch
        return None

    def resolve_strategy_name(self, strategy: str) -> str:
        """把用户输入策略名解析为注册表中的规范短名。

        解析失败时回退到 DEFAULT_STRATEGY。
        """
        scheduler = self._resolve_scheduler(strategy)
        if scheduler is None:
            return self.DEFAULT_STRATEGY
        return scheduler.name

    # ------------------------------------------------------------------
    # 调度入口
    # ------------------------------------------------------------------
    def schedule(self, strategy: str, snapshot: Snapshot) -> List[Command]:
        scheduler = self._resolve_scheduler(strategy)
        if scheduler is None:
            scheduler = self._registry.get(self.DEFAULT_STRATEGY)
        if scheduler is None:
            return []
        return scheduler.schedule(snapshot)
