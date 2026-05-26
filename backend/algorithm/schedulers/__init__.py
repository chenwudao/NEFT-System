"""所有具体算法在这里统一注册。

新增算法的步骤：
    1) 在 schedulers/xxx.py 里实现 `class XxxScheduler(Scheduler): name = "xxx"`
    2) 在这里 import 并加入 `EXPORTED_SCHEDULERS`
    3) config.SCHEDULING_CONFIG["strategy"] 改成 "xxx" 即可启用
"""

from .composite_score import CompositeScoreScheduler
from .deadline_earliest import DeadlineEarliestScheduler
from .dfs_score_search import DfsScoreSearchScheduler
from .heaviest_task import HeaviestTaskScheduler
from .hyper_heuristic_eps import HyperHeuristicEpsScheduler
from .hyper_heuristic import HyperHeuristicScheduler
from .insertion_heuristic import InsertionHeuristicScheduler
from .multi_agent_contract_net import MultiAgentContractNetScheduler
from .mst_batch import MstBatchScheduler
from .multi_agent_auction import MultiAgentAuctionScheduler
from .nearest_task import NearestTaskScheduler
from .priority_task import PriorityTaskScheduler
from .q_learning import QLearningScheduler
from .random_baseline import RandomBaselineScheduler
from .simulated_annealing import SimulatedAnnealingScheduler
from .tabu_search import TabuSearchScheduler

EXPORTED_SCHEDULERS = [
    NearestTaskScheduler,
    PriorityTaskScheduler,
    HeaviestTaskScheduler,
    DeadlineEarliestScheduler,
    CompositeScoreScheduler,
    DfsScoreSearchScheduler,
    MstBatchScheduler,
    InsertionHeuristicScheduler,
    SimulatedAnnealingScheduler,
    TabuSearchScheduler,
    QLearningScheduler,
    HyperHeuristicScheduler,
    HyperHeuristicEpsScheduler,
    MultiAgentAuctionScheduler,
    MultiAgentContractNetScheduler,
    RandomBaselineScheduler,
]

__all__ = [
    "NearestTaskScheduler",
    "PriorityTaskScheduler",
    "HeaviestTaskScheduler",
    "DeadlineEarliestScheduler",
    "CompositeScoreScheduler",
    "DfsScoreSearchScheduler",
    "MstBatchScheduler",
    "InsertionHeuristicScheduler",
    "SimulatedAnnealingScheduler",
    "TabuSearchScheduler",
    "QLearningScheduler",
    "HyperHeuristicScheduler",
    "HyperHeuristicEpsScheduler",
    "MultiAgentAuctionScheduler",
    "MultiAgentContractNetScheduler",
    "RandomBaselineScheduler",
    "EXPORTED_SCHEDULERS",
]
