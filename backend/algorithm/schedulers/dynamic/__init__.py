"""动态调度算法集合（贪心基线 + DFS 装批搜索）。"""

from ..deadline_earliest import DeadlineEarliestScheduler
from ..dfs_score_search import DfsScoreSearchScheduler
from ..heaviest_task import HeaviestTaskScheduler
from ..nearest_task import NearestTaskScheduler
from ..priority_task import PriorityTaskScheduler
from ..cluster_auction_mas import ClusterAuctionMasScheduler
from ..regional_planning import RegionalPlanningScheduler
from ..rl_batch import RlBatchScheduler
from ..relay_handoff import RelayHandoffScheduler
from ..sa_score_search import SaScoreSearchScheduler

DYNAMIC_SCHEDULERS = [
    NearestTaskScheduler,
    PriorityTaskScheduler,
    HeaviestTaskScheduler,
    DeadlineEarliestScheduler,
    DfsScoreSearchScheduler,
    SaScoreSearchScheduler,
    RlBatchScheduler,
    RegionalPlanningScheduler,
    ClusterAuctionMasScheduler,
    RelayHandoffScheduler,
]

__all__ = [
    "NearestTaskScheduler",
    "PriorityTaskScheduler",
    "HeaviestTaskScheduler",
    "DeadlineEarliestScheduler",
    "DfsScoreSearchScheduler",
    "SaScoreSearchScheduler",
    "RlBatchScheduler",
    "RegionalPlanningScheduler",
    "ClusterAuctionMasScheduler",
    "RelayHandoffScheduler",
    "DYNAMIC_SCHEDULERS",
]
