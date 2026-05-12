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

from typing import Dict, List

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

    # ------------------------------------------------------------------
    # 调度入口
    # ------------------------------------------------------------------
    def schedule(self, strategy: str, snapshot: Snapshot) -> List[Command]:
        scheduler = self._registry.get(strategy)
        if scheduler is None:
            scheduler = self._registry.get(self.DEFAULT_STRATEGY)
        if scheduler is None:
            return []
        return scheduler.schedule(snapshot)
