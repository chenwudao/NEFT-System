"""动态调度算法集合。"""

from ..composite_score import CompositeScoreScheduler
from ..deadline_earliest import DeadlineEarliestScheduler
from ..dfs_score_search import DfsScoreSearchScheduler
from ..heaviest_task import HeaviestTaskScheduler
from ..hyper_heuristic_eps import HyperHeuristicEpsScheduler
from ..insertion_heuristic import InsertionHeuristicScheduler
from ..multi_agent_contract_net import MultiAgentContractNetScheduler
from ..multi_agent_auction import MultiAgentAuctionScheduler
from ..nearest_task import NearestTaskScheduler
from ..priority_task import PriorityTaskScheduler
from ..q_learning import QLearningScheduler
from ..region_partition import RegionPartitionScheduler
from ..relay_handoff import RelayHandoffScheduler
from ..simulated_annealing import SimulatedAnnealingScheduler
from ..tabu_search import TabuSearchScheduler

DYNAMIC_SCHEDULERS = [
    NearestTaskScheduler,
    PriorityTaskScheduler,
    HeaviestTaskScheduler,
    DeadlineEarliestScheduler,
    CompositeScoreScheduler,
    DfsScoreSearchScheduler,
    InsertionHeuristicScheduler,
    SimulatedAnnealingScheduler,
    TabuSearchScheduler,
    QLearningScheduler,
    HyperHeuristicEpsScheduler,
    RelayHandoffScheduler,
    RegionPartitionScheduler,
    MultiAgentAuctionScheduler,
    MultiAgentContractNetScheduler,
]

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
    "DYNAMIC_SCHEDULERS",
]
