"""调度算法模块统一入口。

对外导出的核心概念：
    Snapshot          - 算法输入（整个世界的只读视图）
    Scheduler         - 算法基类
    Command           - 算法输出（下一步命令）
    AlgorithmManager  - 算法注册与按名字分发

以及一个工具箱 `utils`，供新算法复用。
"""

from . import utils  # noqa: F401 —— 暴露给外部 import backend.algorithm.utils
from .algorithm_manager import AlgorithmManager
from .scheduler import (
    ACTION_CHARGE,
    ACTION_DELIVER,
    ACTION_IDLE,
    ACTION_RETURN,
    Command,
    Scheduler,
)
from .snapshot import Snapshot

__all__ = [
    "AlgorithmManager",
    "Snapshot",
    "Scheduler",
    "Command",
    "ACTION_DELIVER",
    "ACTION_CHARGE",
    "ACTION_RETURN",
    "ACTION_IDLE",
    "utils",
]
