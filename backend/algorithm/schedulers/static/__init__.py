"""静态（上帝视角）调度算法集合。"""

from .static_exact_solver import StaticExactSolverScheduler

STATIC_SCHEDULERS = [
    StaticExactSolverScheduler,
]

__all__ = [
    "StaticExactSolverScheduler",
    "STATIC_SCHEDULERS",
]
