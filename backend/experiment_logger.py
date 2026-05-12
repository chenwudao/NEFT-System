"""实验日志：每次仿真启动建一个目录，结束时写入最终结果。

目录命名约定：
    <log_dir>/<experiment_name>/
        ├── config.json       启动时写入（本次跑用的完整配置快照）
        └── results.json      仿真结束 / 暂停 / 重置时写入最终指标

**同名实验会直接覆盖**：跑第二次同名实验时，config.json / results.json 都会被原地
替换掉。想保留历史结果请在 config.py 里换一个 EXPERIMENT_CONFIG["name"]。

写入时机：
    - start_experiment(): 启动仿真时调用（只建目录 + config.json）
    - finalize_experiment(): 手动暂停、超时自动停、reset 前调用

若同一次仿真多次调用 finalize_experiment()，只有第一次生效（防止覆盖初次结果）。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.data.data_manager import DataManager


def _project_root() -> str:
    # experiment_logger.py 放在 backend/ 下
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ExperimentLogger:
    """一次仿真 = 一个 ExperimentLogger 实例。主进程持有一个全局实例。"""

    def __init__(self) -> None:
        self.run_dir: Optional[str] = None
        self.started_at: Optional[datetime] = None
        self.started_sim_seconds: float = 0.0
        self._finalized: bool = False

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start_experiment(
        self,
        experiment_cfg: Dict[str, Any],
        full_config_snapshot: Dict[str, Any],
    ) -> str:
        """建立实验目录，写入 config.json。返回目录绝对路径。"""
        name = str(experiment_cfg.get("name") or "default")
        log_dir_rel = str(experiment_cfg.get("log_dir") or "log")

        # 把相对路径解析到项目根
        log_root = log_dir_rel if os.path.isabs(log_dir_rel) else os.path.join(_project_root(), log_dir_rel)
        os.makedirs(log_root, exist_ok=True)

        # 直接以实验名作为目录名，同名实验覆盖上一次的结果。
        # （想保留历史：改 EXPERIMENT_CONFIG["name"] 再跑）
        run_dir = os.path.join(log_root, name)
        os.makedirs(run_dir, exist_ok=True)

        # 提前把上一次的 results.json 清掉，避免"启动后但还没 finalize"时
        # 目录里残留上一次的结果造成误读。
        stale_results = os.path.join(run_dir, "results.json")
        if os.path.exists(stale_results):
            try:
                os.remove(stale_results)
            except OSError:
                pass

        config_path = os.path.join(run_dir, "config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(full_config_snapshot, f, indent=2, ensure_ascii=False)

        self.run_dir = run_dir
        self.started_at = datetime.now()
        self._finalized = False
        print(f"[Experiment] Started: {run_dir}")
        return run_dir

    def finalize_experiment(
        self,
        data_manager: "DataManager",
        sim_seconds_elapsed: float,
        stop_reason: str = "manual",
        extra: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """写入最终指标。多次调用只有第一次生效。"""
        if self._finalized or self.run_dir is None:
            return None

        results = self._collect_results(data_manager, sim_seconds_elapsed, stop_reason)
        if extra:
            results["extra"] = extra

        path = os.path.join(self.run_dir, "results.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            print(f"[Experiment] Failed to write results.json: {exc}")
            return None

        self._finalized = True
        print(f"[Experiment] Finalized ({stop_reason}): {path}")
        return path

    def is_active(self) -> bool:
        return self.run_dir is not None and not self._finalized

    # ------------------------------------------------------------------
    # 收集指标
    # ------------------------------------------------------------------
    def _collect_results(
        self,
        dm: "DataManager",
        sim_seconds_elapsed: float,
        stop_reason: str,
    ) -> Dict[str, Any]:
        # 延迟导入，避免循环引用
        from backend.data.task import TaskStatus
        from backend.data.vehicle import VehicleStatus

        tasks = dm.get_tasks()
        vehicles = dm.get_vehicles()
        stations = dm.get_charging_stations()
        stranded_vehicles = [v for v in vehicles if v.status == VehicleStatus.STRANDED]

        completed = [t for t in tasks if t.status == TaskStatus.COMPLETED]
        on_time = [t for t in completed if getattr(t, "is_on_time", False)]
        timeouts = [t for t in tasks if t.status == TaskStatus.TIMEOUT]
        pending = [t for t in tasks if t.status == TaskStatus.PENDING]

        # 每个已完成任务的得分（score）在 backend/data/path_calculator.py 的
        # `calculate_task_score()` 里计算，公式 = 任务奖励 + 优先级奖励
        # - 距离惩罚 - 能耗惩罚 - 逾期惩罚（权重在 backend/algorithm/scoring_config.py）。
        # 这里进一步汇总：
        #   total           —— 所有已完成任务的 score 之和
        #   per_task_average—— **每个已完成任务的平均分** = total / completed
        #   per_task_on_time_average —— 只对按时送达的任务再求平均（可诊断逾期对均分的影响）
        per_task_scores = [getattr(t, "score", 0.0) for t in completed]
        on_time_scores  = [getattr(t, "score", 0.0) for t in on_time]
        total_score = sum(per_task_scores)
        per_task_avg = (total_score / len(completed)) if completed else 0.0
        on_time_avg  = (sum(on_time_scores) / len(on_time)) if on_time else 0.0

        total_distance = sum(getattr(v, "total_distance_traveled", 0.0) for v in vehicles)
        avg_completed_distance = (
            sum(getattr(t, "complete_path_distance", 0.0) for t in completed) / len(completed)
            if completed
            else 0.0
        )

        summary = {
            "stop_reason":           stop_reason,
            "sim_seconds_elapsed":   float(sim_seconds_elapsed),
            "wall_seconds_elapsed":  (datetime.now() - self.started_at).total_seconds()
                                     if self.started_at
                                     else None,
            "tasks": {
                "total":     len(tasks),
                "completed": len(completed),
                "on_time":   len(on_time),
                "timeout":   len(timeouts),
                "pending":   len(pending),
                "completion_rate": len(completed) / len(tasks) if tasks else 0.0,
                "on_time_rate":    len(on_time) / len(completed) if completed else 0.0,
            },
            "scores": {
                # 所有已完成任务的 score 累加。score 的具体计算见
                # backend/data/path_calculator.py::calculate_task_score
                "total":                     total_score,
                # **重点**：每完成一个任务的平均得分 = total / completed 数
                "per_task_average":          per_task_avg,
                # 只统计按时送达（deadline 前）完成任务的平均得分
                "per_task_on_time_average":  on_time_avg,
                # 历史字段：旧代码里叫 average，保留一份向后兼容
                "average":                   per_task_avg,
            },
            "distance_meters": {
                "total_fleet_traveled":        total_distance,
                "average_completed_task_leg": avg_completed_distance,
            },
            "vehicles_summary": {
                "total":         len(vehicles),
                "stranded":      len(stranded_vehicles),
                "stranded_ids":  [v.id for v in stranded_vehicles],
            },
            "fleet": [
                {
                    "id":                      v.id,
                    "type":                    v.vehicle_type,
                    "battery_final":           v.battery,
                    "battery_percentage":      v.get_battery_percentage(),
                    "total_distance_traveled": v.total_distance_traveled,
                    "energy_consumption_trip": v.energy_consumption,
                    "final_status":            v.status.value,
                }
                for v in vehicles
            ],
            "charging_stations": [
                {
                    "id":                s.id,
                    "capacity":          s.capacity,
                    "final_load":        s.load_pressure,
                    "charging_vehicles": list(s.charging_vehicles),
                    "queue_count":       s.queue_count,
                }
                for s in stations
            ],
            "task_details": [
                {
                    "id":            t.id,
                    "status":        t.status.value,
                    "weight":        t.weight,
                    "priority":      t.priority,
                    "create_time":   t.create_time,
                    "deadline":      t.deadline,
                    "complete_time": getattr(t, "complete_time", None),
                    "is_on_time":    getattr(t, "is_on_time", False),
                    "score":         getattr(t, "score", 0.0),
                    "complete_path_distance": getattr(t, "complete_path_distance", 0.0),
                    "assigned_vehicle_id":    getattr(t, "assigned_vehicle_id", None),
                }
                for t in tasks
            ],
        }
        return summary


# 进程级单例，供 main.py 直接使用
experiment_logger = ExperimentLogger()
