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
from .static import StaticExactSolverScheduler, STATIC_SCHEDULERS

EXPORTED_SCHEDULERS = list(DYNAMIC_SCHEDULERS) + list(STATIC_SCHEDULERS)

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
    "StaticExactSolverScheduler",
    "DYNAMIC_SCHEDULERS",
    "STATIC_SCHEDULERS",
    "EXPORTED_SCHEDULERS",
]
