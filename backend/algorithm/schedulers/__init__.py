"""统一调度算法注册入口（按 dynamic/static 文件夹组织）。"""

from .dynamic import (
    CompositeScoreScheduler,
    DeadlineEarliestScheduler,
    DfsScoreSearchScheduler,
    DYNAMIC_SCHEDULERS,
    HeaviestTaskScheduler,
    HyperHeuristicEpsScheduler,
    InsertionHeuristicScheduler,
    MultiAgentAuctionScheduler,
    MultiAgentContractNetScheduler,
    NearestTaskScheduler,
    PriorityTaskScheduler,
    QLearningScheduler,
    RegionPartitionScheduler,
    RelayHandoffScheduler,
    SimulatedAnnealingScheduler,
    TabuSearchScheduler,
)
from .static import StaticExactSolverScheduler, STATIC_SCHEDULERS

EXPORTED_SCHEDULERS = list(DYNAMIC_SCHEDULERS) + list(STATIC_SCHEDULERS)

__all__ = [
    "NearestTaskScheduler",
    "PriorityTaskScheduler",
    "HeaviestTaskScheduler",
    "DeadlineEarliestScheduler",
    "CompositeScoreScheduler",
    "DfsScoreSearchScheduler",
    "InsertionHeuristicScheduler",
    "SimulatedAnnealingScheduler",
    "TabuSearchScheduler",
    "QLearningScheduler",
    "HyperHeuristicEpsScheduler",
    "RelayHandoffScheduler",
    "RegionPartitionScheduler",
    "MultiAgentAuctionScheduler",
    "MultiAgentContractNetScheduler",
    "StaticExactSolverScheduler",
    "DYNAMIC_SCHEDULERS",
    "STATIC_SCHEDULERS",
    "EXPORTED_SCHEDULERS",
]
