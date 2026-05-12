"""所有具体算法在这里统一注册。

新增算法的步骤：
    1) 在 schedulers/xxx.py 里实现 `class XxxScheduler(Scheduler): name = "xxx"`
    2) 在这里 import 并加入 `EXPORTED_SCHEDULERS`
    3) config.SCHEDULING_CONFIG["strategy"] 改成 "xxx" 即可启用
"""

from .mst_batch import MstBatchScheduler
from .nearest_task import NearestTaskScheduler
from .priority_task import PriorityTaskScheduler

EXPORTED_SCHEDULERS = [
    NearestTaskScheduler,
    PriorityTaskScheduler,
    MstBatchScheduler,
]

__all__ = [
    "NearestTaskScheduler",
    "PriorityTaskScheduler",
    "MstBatchScheduler",
    "EXPORTED_SCHEDULERS",
]
