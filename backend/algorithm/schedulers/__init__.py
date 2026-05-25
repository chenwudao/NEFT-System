"""所有具体算法在这里统一注册。

新增算法的步骤：
    1) 在 schedulers/xxx.py 里实现 `class XxxScheduler(Scheduler): name = "xxx"`
    2) 在这里 import 并加入 `EXPORTED_SCHEDULERS`
    3) config.SCHEDULING_CONFIG["strategy"] 改成 "xxx" 即可启用
"""

from .composite_score import CompositeScoreScheduler
from .deadline_earliest import DeadlineEarliestScheduler
from .heaviest_task import HeaviestTaskScheduler
from .insertion_heuristic import InsertionHeuristicScheduler
from .mst_batch import MstBatchScheduler
from .nearest_task import NearestTaskScheduler
from .priority_task import PriorityTaskScheduler
from .random_baseline import RandomBaselineScheduler
from .simulated_annealing import SimulatedAnnealingScheduler

EXPORTED_SCHEDULERS = [
    NearestTaskScheduler,
    PriorityTaskScheduler,
    HeaviestTaskScheduler,
    DeadlineEarliestScheduler,
    CompositeScoreScheduler,
    MstBatchScheduler,
    InsertionHeuristicScheduler,
    SimulatedAnnealingScheduler,
    RandomBaselineScheduler,
]

__all__ = [
    "NearestTaskScheduler",
    "PriorityTaskScheduler",
    "HeaviestTaskScheduler",
    "DeadlineEarliestScheduler",
    "CompositeScoreScheduler",
    "MstBatchScheduler",
    "InsertionHeuristicScheduler",
    "SimulatedAnnealingScheduler",
    "RandomBaselineScheduler",
    "EXPORTED_SCHEDULERS",
]
