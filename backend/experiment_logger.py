"""实验日志：每次仿真启动建一个目录，结束时写入完整结果。

目录命名约定：
    <log_dir>/<experiment.name>/
        ├── config.yaml      启动时写入（本次跑用的完整配置快照，YAML 格式）
        └── log.txt          人类可读日志，含：
                              - 实验名（来自 yaml 里的 experiment.name）
                              - 启动 / 结束 / 仿真过程关键事件，每行带时间戳
                              - 最终量化指标汇总

同名实验会复用同一个目录，并覆盖上一次的 config.yaml / log.txt。

写入时机：
    - start_experiment() : 启动仿真时；写 config.yaml + log.txt 开头
    - log(msg)           : 任意时刻；追加一行带时间戳的日志
    - finalize_experiment(): 暂停 / 重置 / 自动停 / 全部任务完成时

若同一次仿真多次调用 finalize_experiment()，只有第一次生效。
"""

from __future__ import annotations

import os
import statistics
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

try:
    import yaml as _yaml  # type: ignore
except Exception:
    _yaml = None

if TYPE_CHECKING:
    from backend.data.data_manager import DataManager


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ts(now: Optional[datetime] = None) -> str:
    return (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")


def _safe_dir_name(name: str) -> str:
    """把实验名转成 Windows/Unix 都安全的目录名。"""
    cleaned = "".join(
        ch if ch not in '<>:"/\\|?*\r\n\t' else "_"
        for ch in str(name).strip()
    )
    cleaned = cleaned.strip(" .")
    return cleaned or "default"


def _to_jsonable(obj: Any) -> Any:
    """递归把对象转成 yaml/json 都能 dump 的标准 Python 类型。

    特别处理：
      - numpy 标量（np.float64 / np.int64 等）→ obj.item()
      - Enum → .value
      - dict / list / tuple 递归
      - 其他无法识别的对象 → str(obj)
    """
    if obj is None or isinstance(obj, (bool,)):
        return obj
    # numpy 标量优先（不能用 isinstance(float) 因为版本差异）
    if hasattr(obj, "item") and not isinstance(obj, (str, bytes, dict, list, tuple)):
        try:
            return obj.item()
        except Exception:
            pass
    if isinstance(obj, (int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_to_jsonable(v) for v in obj]
    if hasattr(obj, "value"):  # enum
        try:
            return obj.value
        except Exception:
            pass
    return str(obj)


def _safe_dump_yaml(obj: Any) -> str:
    """容错的 yaml.dump：先把 obj 转成标准 Python 类型，避免 numpy / Enum 报错。"""
    safe_obj = _to_jsonable(obj)
    if _yaml is None:
        import json
        return json.dumps(safe_obj, indent=2, ensure_ascii=False, default=str)
    try:
        return _yaml.safe_dump(
            safe_obj, allow_unicode=True, sort_keys=False, default_flow_style=False
        )
    except Exception as exc:
        # 双保险：还出问题就退化成 json
        import json
        return (
            f"# yaml dump failed ({exc}); fallback to JSON\n"
            + json.dumps(safe_obj, indent=2, ensure_ascii=False, default=str)
        )


class ExperimentLogger:
    """一次仿真 = 一个 ExperimentLogger 实例。主进程持有一个全局实例。"""

    def __init__(self) -> None:
        self.run_dir: Optional[str] = None
        self.exp_name: str = "default"
        self.started_at: Optional[datetime] = None
        self.started_sim_seconds: float = 0.0
        self._finalized: bool = False
        self._log_path: Optional[str] = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start_experiment(
        self,
        experiment_cfg: Dict[str, Any],
        full_config_snapshot: Dict[str, Any],
    ) -> str:
        """建立实验目录，写入 config.yaml + log.txt 开头。返回目录绝对路径。"""
        name = str(experiment_cfg.get("name") or "default")
        log_dir_rel = str(experiment_cfg.get("log_dir") or "log")

        log_root = (
            log_dir_rel
            if os.path.isabs(log_dir_rel)
            else os.path.join(_project_root(), log_dir_rel)
        )
        os.makedirs(log_root, exist_ok=True)

        started = datetime.now()
        run_dir = os.path.join(log_root, _safe_dir_name(name))
        os.makedirs(run_dir, exist_ok=True)

        # 写 config.yaml（本次配置快照）
        config_path = os.path.join(run_dir, "config.yaml")
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(_safe_dump_yaml(full_config_snapshot))
        except Exception as exc:
            print(f"[Experiment] WARN: failed to write config.yaml: {exc}")

        # 初始化 log.txt
        log_path = os.path.join(run_dir, "log.txt")
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"# NEFT 仿真实验日志\n")
                f.write(f"实验名 (experiment.name): {name}\n")
                f.write(f"启动时间:                 {_ts(started)}\n")
                f.write(f"日志目录:                 {run_dir}\n")
                f.write(f"配置文件:                 {full_config_snapshot.get('config_file') or '(默认内置)'}\n")
                f.write("\n")
                f.write("---- 事件日志 ----\n")
                f.write(f"[{_ts(started)}] [START] Experiment '{name}' started.\n")
        except Exception as exc:
            print(f"[Experiment] WARN: failed to write log.txt: {exc}")

        self.run_dir = run_dir
        self.exp_name = name
        self.started_at = started
        self._finalized = False
        self._log_path = log_path
        print(f"[Experiment] Started: {run_dir}  (name={name})")
        return run_dir

    def log(self, msg: str, level: str = "INFO") -> None:
        """追加一行带时间戳的日志。仿真中任何时候都能调。"""
        if not self._log_path:
            return
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(f"[{_ts()}] [{level}] {msg}\n")
        except Exception:
            pass

    def finalize_experiment(
        self,
        data_manager: "DataManager",
        sim_seconds_elapsed: float,
        stop_reason: str = "manual",
        extra: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """落盘最终指标（追加到 log.txt 末尾）。多次调用只有第一次生效。"""
        if self._finalized or self.run_dir is None or self._log_path is None:
            return None

        results = self._collect_results(data_manager, sim_seconds_elapsed, stop_reason)
        if extra:
            results["extra"] = extra

        # 追加可读的总结到 log.txt
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(f"\n[{_ts()}] [STOP] reason={stop_reason}\n")
                f.write("\n---- 最终结果 ----\n")
                f.write(self._format_results_human(results))
                f.write("\n---- 完整结果（YAML） ----\n")
                f.write(_safe_dump_yaml(results))
        except Exception as exc:
            print(f"[Experiment] WARN: failed to append results to log.txt: {exc}")

        self._finalized = True
        print(f"[Experiment] Finalized ({stop_reason}): {self._log_path}")
        return self._log_path

    def is_active(self) -> bool:
        return self.run_dir is not None and not self._finalized

    def write_yaml_artifact(self, filename: str, payload: Dict[str, Any]) -> Optional[str]:
        """在当前实验目录写一个 YAML 工件文件（覆盖写）。"""
        if not self.run_dir:
            return None
        try:
            path = os.path.join(self.run_dir, filename)
            with open(path, "w", encoding="utf-8") as f:
                f.write(_safe_dump_yaml(payload))
            return path
        except Exception as exc:
            print(f"[Experiment] WARN: failed to write artifact '{filename}': {exc}")
            return None

    # ------------------------------------------------------------------
    # 收集指标
    # ------------------------------------------------------------------
    def _collect_results(
        self,
        dm: "DataManager",
        sim_seconds_elapsed: float,
        stop_reason: str,
    ) -> Dict[str, Any]:
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
        in_progress_tasks = [
            t for t in tasks
            if t.status == TaskStatus.IN_PROGRESS
        ]

        per_task_scores = [getattr(t, "score", 0.0) for t in completed]
        on_time_scores = [getattr(t, "score", 0.0) for t in on_time]
        total_score = sum(per_task_scores)
        per_task_avg = (total_score / len(completed)) if completed else 0.0
        on_time_avg = (sum(on_time_scores) / len(on_time)) if on_time else 0.0

        total_distance = sum(getattr(v, "total_distance_traveled", 0.0) for v in vehicles)
        avg_completed_distance = (
            sum(getattr(t, "complete_path_distance", 0.0) for t in completed) / len(completed)
            if completed
            else 0.0
        )

        # 平均完成时长（complete_time - create_time）
        completion_durations = [
            (t.complete_time - t.create_time)
            for t in completed
            if getattr(t, "complete_time", None) and getattr(t, "create_time", None)
            and t.complete_time >= t.create_time
        ]
        avg_completion_duration = (
            sum(completion_durations) / len(completion_durations) if completion_durations else 0.0
        )

        # 平均超时分钟数（仅对逾期完成 / TIMEOUT 任务）
        overdue_minutes_list: List[float] = []
        for t in completed:
            if getattr(t, "complete_time", None) and t.complete_time > t.deadline:
                overdue_minutes_list.append((t.complete_time - t.deadline) / 60.0)
        for t in timeouts:
            # TIMEOUT 任务没 complete_time；以仿真结束时刻估算超时长度
            now_est = int(sim_seconds_elapsed)
            overdue_minutes_list.append(max(0.0, (now_est - t.deadline) / 60.0))
        avg_overdue_minutes = (
            sum(overdue_minutes_list) / len(overdue_minutes_list)
            if overdue_minutes_list else 0.0
        )

        # 每车里程的标准差（量化"负载均衡度"，越小越均衡）
        per_vehicle_distance = [
            float(getattr(v, "total_distance_traveled", 0.0)) for v in vehicles
        ]
        if len(per_vehicle_distance) >= 2:
            try:
                fleet_distance_stdev = statistics.stdev(per_vehicle_distance)
            except statistics.StatisticsError:
                fleet_distance_stdev = 0.0
        else:
            fleet_distance_stdev = 0.0

        # 每车完成任务数
        per_vehicle_completed: Dict[int, int] = {v.id: 0 for v in vehicles}
        for t in completed:
            vid = getattr(t, "assigned_vehicle_id", None)
            if vid in per_vehicle_completed:
                per_vehicle_completed[vid] += 1

        # 吞吐量（任务/小时仿真时间）
        if sim_seconds_elapsed > 0:
            throughput_per_hour = len(completed) / (sim_seconds_elapsed / 3600.0)
        else:
            throughput_per_hour = 0.0

        # 能耗 / 任务数
        total_energy = total_distance * 0.0003  # 用平均 unit_energy
        try:
            total_energy = sum(
                getattr(v, "total_distance_traveled", 0.0) * float(v.unit_energy_consumption)
                for v in vehicles
            )
        except Exception:
            pass
        energy_per_completed = (total_energy / len(completed)) if completed else 0.0

        summary: Dict[str, Any] = {
            "experiment_name":      self.exp_name,
            "stop_reason":          stop_reason,
            "sim_seconds_elapsed":  float(sim_seconds_elapsed),
            "wall_seconds_elapsed": (
                (datetime.now() - self.started_at).total_seconds()
                if self.started_at else None
            ),
            "tasks": {
                "total":           len(tasks),
                "completed":       len(completed),
                "on_time":         len(on_time),
                "timeout":         len(timeouts),
                "pending":         len(pending),
                "in_progress":     len(in_progress_tasks),
                "completion_rate": len(completed) / len(tasks) if tasks else 0.0,
                "on_time_rate":    len(on_time) / len(completed) if completed else 0.0,
                "timeout_rate":    len(timeouts) / len(tasks) if tasks else 0.0,
            },
            "scores": {
                "total":                    total_score,
                "per_task_average":         per_task_avg,
                "per_task_on_time_average": on_time_avg,
                "average":                  per_task_avg,
            },
            "timing": {
                "avg_completion_duration_sec": avg_completion_duration,
                "avg_overdue_minutes":         avg_overdue_minutes,
                "throughput_tasks_per_hour":   throughput_per_hour,
            },
            "distance_meters": {
                "total_fleet_traveled":       total_distance,
                "average_completed_task_leg": avg_completed_distance,
                "fleet_distance_stdev":       fleet_distance_stdev,
            },
            "energy": {
                "total_energy":         total_energy,
                "energy_per_completed": energy_per_completed,
            },
            "vehicles_summary": {
                "total":        len(vehicles),
                "stranded":     len(stranded_vehicles),
                "stranded_ids": [v.id for v in stranded_vehicles],
                "completed_per_vehicle": per_vehicle_completed,
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
                    "completed_tasks":         per_vehicle_completed.get(v.id, 0),
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
        }
        return summary

    def _format_results_human(self, results: Dict[str, Any]) -> str:
        """把 results 排版成短小可读的总结，便于一眼看清。"""
        tasks = results.get("tasks", {})
        scores = results.get("scores", {})
        timing = results.get("timing", {})
        distance = results.get("distance_meters", {})
        energy = results.get("energy", {})
        vsum = results.get("vehicles_summary", {})

        lines: List[str] = []
        lines.append(f"实验名: {results.get('experiment_name')}")
        lines.append(f"停止原因: {results.get('stop_reason')}")
        lines.append(
            f"仿真时长: {results.get('sim_seconds_elapsed'):.0f} 仿真秒 / "
            f"{(results.get('wall_seconds_elapsed') or 0):.1f} 现实秒"
        )
        lines.append("")
        lines.append("[ 任务 ]")
        lines.append(
            f"  总数={tasks.get('total', 0)} 完成={tasks.get('completed', 0)} "
            f"按时={tasks.get('on_time', 0)} 超时={tasks.get('timeout', 0)} "
            f"进行中={tasks.get('in_progress', 0)} 待派={tasks.get('pending', 0)}"
        )
        lines.append(
            f"  完成率={tasks.get('completion_rate', 0):.2%} "
            f"按时率={tasks.get('on_time_rate', 0):.2%} "
            f"超时率={tasks.get('timeout_rate', 0):.2%}"
        )
        lines.append("")
        lines.append("[ 得分 ]")
        lines.append(
            f"  总分={scores.get('total', 0):.1f} "
            f"每任务平均={scores.get('per_task_average', 0):.2f} "
            f"按时平均={scores.get('per_task_on_time_average', 0):.2f}"
        )
        lines.append("")
        lines.append("[ 时效 ]")
        lines.append(
            f"  平均完成时长={timing.get('avg_completion_duration_sec', 0):.1f}s "
            f"平均超时={timing.get('avg_overdue_minutes', 0):.2f}min "
            f"吞吐={timing.get('throughput_tasks_per_hour', 0):.2f} 任务/小时"
        )
        lines.append("")
        lines.append("[ 距离 / 能耗 ]")
        lines.append(
            f"  车队总里程={distance.get('total_fleet_traveled', 0):.0f}m "
            f"任务腿均长={distance.get('average_completed_task_leg', 0):.0f}m "
            f"里程方差(车均衡)={distance.get('fleet_distance_stdev', 0):.0f}"
        )
        lines.append(
            f"  总能耗={energy.get('total_energy', 0):.2f}kWh "
            f"单任务能耗={energy.get('energy_per_completed', 0):.3f}kWh"
        )
        lines.append("")
        lines.append("[ 车队 ]")
        lines.append(
            f"  总车数={vsum.get('total', 0)} 抛锚={vsum.get('stranded', 0)} "
            f"抛锚ID={vsum.get('stranded_ids', [])}"
        )

        return "\n".join(lines) + "\n"


experiment_logger = ExperimentLogger()
