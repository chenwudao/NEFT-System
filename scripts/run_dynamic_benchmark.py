#!/usr/bin/env python
"""动态实验一键运行脚本。

功能：
1) 三个规模（small/medium/large）；
2) 每个规模跑 3 个种子组；
3) 每个种子组先跑基准算法生成 seed，再让其余算法复用该 seed；
4) 自动生成实验配置文件（按 scale/seed/algo 分层）；
5) 自动汇总关键指标到 CSV；
6) 使用 matplotlib 输出关键指标可视化图。

默认日志组织：
log/benchmarks/dynamic/<scale>/seed_<n>/<algorithm>/
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import matplotlib.pyplot as plt
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXE = sys.executable
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_SCALES = ["medium", "large"]


def discover_dynamic_algorithms() -> List[str]:
    """从动态调度注册表自动发现全部算法名（按注册顺序）。"""
    from backend.algorithm.schedulers.dynamic import DYNAMIC_SCHEDULERS

    excluded = {"relay_handoff", "region_partition", "random_baseline", "mst_batch"}
    names = []
    for cls in DYNAMIC_SCHEDULERS:
        name = str(getattr(cls, "name", "")).strip()
        if name and name not in excluded:
            names.append(name)
    if not names:
        raise RuntimeError("No dynamic schedulers discovered.")
    # 确保基准算法优先（用于生成 seed）
    if "nearest_task" in names:
        names = ["nearest_task"] + [n for n in names if n != "nearest_task"]
    return names


@dataclass
class RunResult:
    scale: str
    seed_idx: int
    algorithm: str
    config_path: str
    log_dir: str
    stop_reason: str
    total_tasks: int
    completed: int
    timeout: int
    completion_rate: float
    timeout_rate: float
    total_score: float
    per_task_average: float
    on_time_rate: float
    throughput_tasks_per_hour: float
    avg_overdue_minutes: float
    avg_completion_duration_sec: float


def read_yaml(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def write_yaml(path: Path, payload: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)


def run_headless(cfg_path: Path) -> None:
    cmd = [
        PYTHON_EXE,
        str(PROJECT_ROOT / "backend" / "main.py"),
        "--cfg",
        str(cfg_path),
        "-u",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Run failed: {' '.join(cmd)}\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )


def parse_final_results_from_log(log_txt: Path) -> Dict:
    if not log_txt.exists():
        raise FileNotFoundError(f"log not found: {log_txt}")
    text = log_txt.read_text(encoding="utf-8", errors="ignore")
    marker = "---- 完整结果（YAML） ----"
    idx = text.rfind(marker)
    if idx < 0:
        raise RuntimeError(f"Cannot find final YAML marker in: {log_txt}")
    yaml_text = text[idx + len(marker):].strip()
    payload = yaml.safe_load(yaml_text)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Final YAML parse failed: {log_txt}")
    return payload


def build_run_config(
    base_cfg: Dict,
    *,
    scale: str,
    seed_idx: int,
    algorithm: str,
    log_root: Path,
    generation_seed_file: Optional[str],
) -> Dict:
    cfg = yaml.safe_load(yaml.safe_dump(base_cfg, allow_unicode=True))  # deep copy
    exp = cfg.setdefault("experiment", {})
    exp["log_dir"] = str(log_root.as_posix())
    exp["name"] = algorithm
    task = cfg.setdefault("task", {})
    task["generation_seed_file"] = generation_seed_file
    sched = cfg.setdefault("scheduling", {})
    sched["strategy"] = algorithm

    # 强制动态模式（避免误触 static）
    opt = cfg.setdefault("optimization", {})
    opt["mode"] = "dynamic"
    return cfg


def summarize_rows(rows: List[RunResult], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "results.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(RunResult.__dataclass_fields__.keys()),
        )
        writer.writeheader()
        for r in rows:
            writer.writerow(r.__dict__)

    # 聚合：按 scale + algorithm 求均值
    agg: Dict[str, Dict[str, Dict[str, float]]] = {}
    cnt: Dict[str, Dict[str, int]] = {}
    for r in rows:
        agg.setdefault(r.scale, {}).setdefault(r.algorithm, {
            "total_score": 0.0,
            "completion_rate": 0.0,
            "timeout_rate": 0.0,
            "on_time_rate": 0.0,
        })
        cnt.setdefault(r.scale, {}).setdefault(r.algorithm, 0)
        agg[r.scale][r.algorithm]["total_score"] += r.total_score
        agg[r.scale][r.algorithm]["completion_rate"] += r.completion_rate
        agg[r.scale][r.algorithm]["timeout_rate"] += r.timeout_rate
        agg[r.scale][r.algorithm]["on_time_rate"] += r.on_time_rate
        cnt[r.scale][r.algorithm] += 1

    for s in agg:
        for a in agg[s]:
            c = max(1, cnt[s][a])
            for k in agg[s][a]:
                agg[s][a][k] /= c

    # 绘图1：每个规模下算法平均总分
    for scale, algo_map in agg.items():
        algos = list(algo_map.keys())
        scores = [algo_map[a]["total_score"] for a in algos]
        plt.figure(figsize=(12, 5))
        plt.bar(range(len(algos)), scores)
        plt.xticks(range(len(algos)), algos, rotation=30, ha="right")
        plt.ylabel("Avg Total Score")
        plt.title(f"{scale} - Average Total Score (3 seeds)")
        plt.tight_layout()
        plt.savefig(out_dir / f"{scale}_avg_total_score.png", dpi=160)
        plt.close()

    # 绘图2：完成率/超时率（跨规模）
    scales = sorted(agg.keys())
    # 选择共同算法集（按第一个规模）
    ref_algos = list(agg[scales[0]].keys()) if scales else []
    for metric, title, filename in [
        ("completion_rate", "Average Completion Rate", "avg_completion_rate.png"),
        ("timeout_rate", "Average Timeout Rate", "avg_timeout_rate.png"),
    ]:
        plt.figure(figsize=(14, 6))
        width = 0.25
        x = list(range(len(ref_algos)))
        for i, scale in enumerate(scales):
            vals = [agg[scale].get(a, {}).get(metric, 0.0) for a in ref_algos]
            plt.bar(
                [p + i * width for p in x],
                vals,
                width=width,
                label=scale,
            )
        plt.xticks([p + width for p in x], ref_algos, rotation=30, ha="right")
        plt.ylim(0, 1.0)
        plt.ylabel(metric)
        plt.title(title)
        plt.legend()
        plt.tight_layout()
        plt.savefig(out_dir / filename, dpi=160)
        plt.close()


def collect_result(
    *,
    scale: str,
    seed_idx: int,
    algorithm: str,
    cfg_path: Path,
    run_log_dir: Path,
) -> RunResult:
    payload = parse_final_results_from_log(run_log_dir / "log.txt")
    tasks = payload.get("tasks", {})
    scores = payload.get("scores", {})
    timing = payload.get("timing", {})
    return RunResult(
        scale=scale,
        seed_idx=seed_idx,
        algorithm=algorithm,
        config_path=str(cfg_path.as_posix()),
        log_dir=str(run_log_dir.as_posix()),
        stop_reason=str(payload.get("stop_reason", "")),
        total_tasks=int(tasks.get("total", 0)),
        completed=int(tasks.get("completed", 0)),
        timeout=int(tasks.get("timeout", 0)),
        completion_rate=float(tasks.get("completion_rate", 0.0)),
        timeout_rate=float(tasks.get("timeout_rate", 0.0)),
        total_score=float(scores.get("total", 0.0)),
        per_task_average=float(scores.get("per_task_average", 0.0)),
        on_time_rate=float(tasks.get("on_time_rate", 0.0)),
        throughput_tasks_per_hour=float(timing.get("throughput_tasks_per_hour", 0.0)),
        avg_overdue_minutes=float(timing.get("avg_overdue_minutes", 0.0)),
        avg_completion_duration_sec=float(timing.get("avg_completion_duration_sec", 0.0)),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run dynamic benchmark experiments.")
    parser.add_argument("--seeds", type=int, default=3, help="seed groups per scale")
    parser.add_argument(
        "--large-seeds",
        type=int,
        default=1,
        help="seed groups for large scale (override default seeds for large)",
    )
    parser.add_argument(
        "--scales",
        nargs="+",
        default=DEFAULT_SCALES,
        choices=["small", "medium", "large"],
    )
    parser.add_argument(
        "--algorithms",
        nargs="+",
        default=None,
        help="first algorithm is baseline seed generator",
    )
    parser.add_argument(
        "--out-dir",
        default="benchmark_results/dynamic",
        help="output directory for generated configs, csv and plots",
    )
    args = parser.parse_args()

    algorithms = args.algorithms or discover_dynamic_algorithms()
    if not algorithms:
        raise SystemExit("At least one algorithm is required.")
    print(f"[INFO] dynamic algorithms: {algorithms}")

    out_root = (PROJECT_ROOT / args.out_dir).resolve()
    generated_cfg_root = out_root / "generated_configs"
    reports_root = out_root / "reports"
    bench_log_root = PROJECT_ROOT / "log" / "benchmarks" / "dynamic"
    rows: List[RunResult] = []

    for scale in args.scales:
        base_path = PROJECT_ROOT / "configs" / "dynamic" / f"{scale}.yaml"
        base_cfg = read_yaml(base_path)
        scale_seeds = args.large_seeds if scale == "large" else args.seeds
        for seed_idx in range(1, scale_seeds + 1):
            seed_start_row_idx = len(rows)
            seed_label = f"seed_{seed_idx}"
            run_group_log_root = bench_log_root / scale / seed_label
            run_group_cfg_root = generated_cfg_root / scale / seed_label

            baseline = algorithms[0]
            baseline_cfg = build_run_config(
                base_cfg,
                scale=scale,
                seed_idx=seed_idx,
                algorithm=baseline,
                log_root=run_group_log_root,
                generation_seed_file=None,  # 先生成 seed
            )
            baseline_cfg_path = run_group_cfg_root / f"{baseline}.yaml"
            write_yaml(baseline_cfg_path, baseline_cfg)
            print(f"[RUN] scale={scale} {seed_label} algo={baseline} (seed record)")
            run_headless(baseline_cfg_path)
            baseline_log_dir = run_group_log_root / baseline
            seed_file = baseline_log_dir / "task_generation_seed.yaml"
            if not seed_file.exists():
                raise RuntimeError(f"Seed file not found: {seed_file}")
            rows.append(
                collect_result(
                    scale=scale,
                    seed_idx=seed_idx,
                    algorithm=baseline,
                    cfg_path=baseline_cfg_path,
                    run_log_dir=baseline_log_dir,
                )
            )

            # 其它算法读取同一个 seed（公平对比）
            for algo in algorithms[1:]:
                cfg = build_run_config(
                    base_cfg,
                    scale=scale,
                    seed_idx=seed_idx,
                    algorithm=algo,
                    log_root=run_group_log_root,
                    generation_seed_file=str(seed_file.as_posix()),
                )
                cfg_path = run_group_cfg_root / f"{algo}.yaml"
                write_yaml(cfg_path, cfg)
                print(f"[RUN] scale={scale} {seed_label} algo={algo} (seed replay)")
                run_headless(cfg_path)
                rows.append(
                    collect_result(
                        scale=scale,
                        seed_idx=seed_idx,
                        algorithm=algo,
                        cfg_path=cfg_path,
                        run_log_dir=run_group_log_root / algo,
                    )
                )

            # 每完成一个 seed 的全部算法后，先产出该 seed 的结果与图表
            seed_rows = rows[seed_start_row_idx:]
            seed_report_dir = reports_root / scale / seed_label
            summarize_rows(seed_rows, seed_report_dir)
            print(f"[SEED DONE] Saved seed-level report: {seed_report_dir}")

    summarize_rows(rows, reports_root)
    print(f"[DONE] Results CSV and plots saved to: {reports_root}")
    print(f"[DONE] Generated configs saved to: {generated_cfg_root}")
    print(f"[DONE] Logs saved under: {bench_log_root}")


if __name__ == "__main__":
    main()

