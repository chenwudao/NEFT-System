"""决策管理器（瘦身版）。

职责只剩两件：
    1. 读 `config.SCHEDULING_CONFIG["strategy"]`，把 Snapshot 交给算法，
       把算法返回的 Command 交给执行器落地。
    2. 对外提供系统状态 / 简单性能指标供 API 使用。

auto 自动选算法、manage_battery、离站阈值等旧逻辑已全部并入算法 / 数据层。
"""

from datetime import datetime
from typing import Dict, List, Optional

from backend.algorithm.algorithm_manager import AlgorithmManager
from backend.config import config
from backend.data.data_manager import DataManager
from backend.data.task import TaskStatus
from backend.data.vehicle import VehicleStatus

from .dynamic_scheduling_module import DynamicSchedulingModule


class DecisionManager:
    def __init__(self, data_manager: DataManager, algorithm_manager: AlgorithmManager):
        self.data_manager = data_manager
        self.algorithm_manager = algorithm_manager
        self._dynamic_scheduling = DynamicSchedulingModule(data_manager, algorithm_manager)
        self.last_selected_strategy: str = self._configured_strategy()

    # ------------------------------------------------------------------
    def _configured_strategy(self) -> str:
        opt_cfg = config.get_optimization_config()
        mode = str(opt_cfg.get("mode", "dynamic")).strip().lower()
        if mode == "static":
            static_cfg = opt_cfg.get("static") or {}
            return str(static_cfg.get("strategy", "nearest_task"))
        return str(config.get_scheduling_config().get("strategy", AlgorithmManager.DEFAULT_STRATEGY))

    # ------------------------------------------------------------------
    # 唯一调度入口
    # ------------------------------------------------------------------
    def dynamic_scheduling(self, strategy: Optional[str] = None) -> List[Dict]:
        """跑一轮调度。strategy 为 None 时使用 config 里配置的算法。"""
        chosen = strategy or self._configured_strategy()
        # 未知算法名就退回到 DEFAULT_STRATEGY，避免线上因为手滑写错而全停。
        if chosen not in self.algorithm_manager.get_available_strategies():
            opt_cfg = config.get_optimization_config()
            if str(opt_cfg.get("mode", "dynamic")).strip().lower() == "static":
                chosen = str((opt_cfg.get("static") or {}).get("strategy", "nearest_task"))
                if chosen not in self.algorithm_manager.get_available_strategies():
                    chosen = AlgorithmManager.DEFAULT_STRATEGY
            else:
                chosen = AlgorithmManager.DEFAULT_STRATEGY
        self.last_selected_strategy = chosen
        return self._dynamic_scheduling.run_once(chosen)

    # ------------------------------------------------------------------
    # 系统状态 / 性能指标
    # ------------------------------------------------------------------
    def get_system_status(self) -> Dict:
        tasks = self.data_manager.get_visible_tasks()
        vehicles = self.data_manager.get_vehicles()
        stations = self.data_manager.get_charging_stations()

        pending = [t for t in tasks if t.status == TaskStatus.PENDING]
        in_progress = [
            t for t in tasks
            if t.status == TaskStatus.IN_PROGRESS
        ]
        completed = [t for t in tasks if t.status == TaskStatus.COMPLETED]
        timeout = [t for t in tasks if t.status == TaskStatus.TIMEOUT]

        idle = [v for v in vehicles if v.status == VehicleStatus.IDLE]
        moving = [v for v in vehicles if v.is_moving()]
        charging = [
            v for v in vehicles
            if v.status in (VehicleStatus.CHARGING, VehicleStatus.WAITING_CHARGE)
        ]

        completion_rate = len(completed) / len(tasks) if tasks else 0.0
        utilization = (
            (len(vehicles) - len(idle)) / len(vehicles) if vehicles else 0.0
        )

        return {
            "timestamp": self.data_manager.get_sim_time(),
            "total_tasks": len(tasks),
            "pending_tasks": len(pending),
            "in_progress_tasks": len(in_progress),
            "completed_tasks": len(completed),
            "timeout_tasks": len(timeout),
            "total_vehicles": len(vehicles),
            "idle_vehicles": len(idle),
            "moving_vehicles": len(moving),
            "charging_vehicles": len(charging),
            "total_charging_stations": len(stations),
            "current_strategy": self.last_selected_strategy,
            "completion_rate": completion_rate,
            "vehicle_utilization": utilization,
        }

    def evaluate_system_performance(self) -> Dict:
        tasks = self.data_manager.get_tasks()
        completed = [t for t in tasks if t.status == TaskStatus.COMPLETED]
        if not completed:
            return {
                "completion_rate": 0.0,
                "avg_completion_time": 0.0,
                "total_distance": 0.0,
                "total_score": 0.0,
            }

        total_ct = 0
        total_dist = 0.0
        total_score = 0.0
        for t in completed:
            if t.complete_time and t.start_time:
                total_ct += t.complete_time - t.start_time
            total_dist += t.complete_path_distance
            total_score += t.score

        return {
            "completion_rate": len(completed) / len(tasks) if tasks else 0.0,
            "avg_completion_time": total_ct / len(completed),
            "total_distance": total_dist,
            "total_score": total_score,
        }
