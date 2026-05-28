"""统一调度算法注册入口。"""

from .dynamic import (
    DeadlineEarliestScheduler,
    DYNAMIC_SCHEDULERS,
    DfsScoreSearchScheduler,
    ClusterAuctionMasScheduler,
    RegionalPlanningScheduler,
    RelayHandoffScheduler,
    SaScoreSearchScheduler,
    HeaviestTaskScheduler,
    NearestTaskScheduler,
    PriorityTaskScheduler,
)

EXPORTED_SCHEDULERS = list(DYNAMIC_SCHEDULERS)

__all__ = [
    "NearestTaskScheduler",
    "PriorityTaskScheduler",
    "HeaviestTaskScheduler",
    "DeadlineEarliestScheduler",
    "DfsScoreSearchScheduler",
    "SaScoreSearchScheduler",
    "RegionalPlanningScheduler",
    "ClusterAuctionMasScheduler",
    "RelayHandoffScheduler",
    "DYNAMIC_SCHEDULERS",
    "EXPORTED_SCHEDULERS",
]
