#!/usr/bin/env python3
"""动态调度算法批量对比实验。

用法（在项目根目录）：
    python scripts/run_dynamic_benchmark.py

实验设计：
    - 三个规模：configs/dynamic/{small,medium,large}.yaml
    - 小规模 2 个 seed，中/大规模各 1 个 seed
    - 每个 seed：先用 nearest_task 生成 task_generation_seed.yaml，
      其余 dynamic 算法复用同一 seed（仅 strategy 不同，其余严格沿用 yaml）
    - 结果写入 experiments/dynamic_benchmark/
    - 每个 seed 跑完所有算法后输出 CSV + 柱状图
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("请先安装 pyyaml: pip install pyyaml") from exc

try:
    import matplotlib.pyplot as plt
except ImportError as exc:  # pragma: no cover
    raise SystemExit("请先安装 matplotlib: pip install matplotlib") from exc


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.algorithm.schedulers.dynamic import DYNAMIC_SCHEDULERS  # noqa: E402


SCALE_CONFIGS: Dict[str, Dict[str, Any]] = {
    "small": {"yaml": "configs/dynamic/small.yaml", "seed_count": 2},
    "medium": {"yaml": "configs/dynamic/medium.yaml", "seed_count": 1},
    "large": {"yaml": "configs/dynamic/large.yaml", "seed_count": 1},
}

DYNAMIC_ALGORITHMS: List[str] = [cls.name for cls in DYNAMIC_SCHEDULERS]
SEED_GENERATOR = "nearest_task"
RESULTS_YAML_MARKER = "---- 完整结果（YAML） ----"
_LOG_LINE_RE = re.compile(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]")
EXPERIMENT_ROOT = PROJECT_ROOT / "experiments" / "dynamic_benchmark"


def _load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"配置文件不是 mapping: {path}")
    return data


def _dump_yaml(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def _build_run_config(
    base_cfg: Dict[str, Any],
    *,
    scale: str,
    seed_idx: int,
    algorithm: str,
    seed_file: Optional[Path],
) -> Dict[str, Any]:
    """在规模 yaml 基础上仅覆盖实验目录、策略与种子文件。"""
    cfg = deepcopy(base_cfg)
    run_name = f"{scale}-seed{seed_idx}-{algorithm}"
    runs_rel = f"experiments/dynamic_benchmark/{scale}/seed_{seed_idx}/runs"

    cfg.setdefault("experiment", {})
    cfg["experiment"]["name"] = run_name
    cfg["experiment"]["log_dir"] = runs_rel

    cfg.setdefault("scheduling", {})
    cfg["scheduling"]["strategy"] = algorithm

    cfg.setdefault("task", {})
    if seed_file is None:
        cfg["task"]["generation_seed_file"] = None
    else:
        cfg["task"]["generation_seed_file"] = str(seed_file.resolve())

    return cfg


def _run_headless(cfg_path: Path, *, dry_run: bool = False) -> int:
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "backend" / "main.py"),
        "--cfg",
        str(cfg_path),
        "--headless",
    ]
    print(f"\n[Run] {' '.join(cmd)}")
    if dry_run:
        return 0
    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    return int(proc.returncode)


def _run_dir(scale: str, seed_idx: int, algorithm: str) -> Path:
    run_name = f"{scale}-seed{seed_idx}-{algorithm}"
    return EXPERIMENT_ROOT / scale / f"seed_{seed_idx}" / "runs" / run_name


def _extract_results_yaml_text(text: str) -> str:
    if RESULTS_YAML_MARKER not in text:
        raise ValueError("未在日志中找到结果段")
    yaml_part = text.rsplit(RESULTS_YAML_MARKER, 1)[1]
    lines: List[str] = []
    for line in yaml_part.splitlines():
        if _LOG_LINE_RE.match(line.strip()):
            break
        lines.append(line)
    yaml_text = "\n".join(lines).strip()
    if not yaml_text:
        raise ValueError("结果 YAML 段为空")
    return yaml_text


def _parse_results_from_log(log_path: Path) -> Dict[str, Any]:
    text = log_path.read_text(encoding="utf-8")
    yaml_text = _extract_results_yaml_text(text)
    try:
        data = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"结果 YAML 解析失败: {log_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"结果 YAML 解析失败: {log_path}")
    return data


def _flatten_result_row(
    *,
    scale: str,
    seed_idx: int,
    algorithm: str,
    results: Dict[str, Any],
    run_dir: Path,
) -> Dict[str, Any]:
    tasks = results.get("tasks") or {}
    scores = results.get("scores") or {}
    timing = results.get("timing") or {}
    distance = results.get("distance_meters") or {}
    energy = results.get("energy") or {}
    vehicles = results.get("vehicles_summary") or {}

    return {
        "scale": scale,
        "seed": seed_idx,
        "algorithm": algorithm,
        "experiment_name": results.get("experiment_name", ""),
        "stop_reason": results.get("stop_reason", ""),
        "sim_seconds_elapsed": results.get("sim_seconds_elapsed", ""),
        "wall_seconds_elapsed": results.get("wall_seconds_elapsed", ""),
        "tasks_total": tasks.get("total", 0),
        "tasks_completed": tasks.get("completed", 0),
        "tasks_on_time": tasks.get("on_time", 0),
        "tasks_timeout": tasks.get("timeout", 0),
        "completion_rate": tasks.get("completion_rate", 0.0),
        "on_time_rate": tasks.get("on_time_rate", 0.0),
        "timeout_rate": tasks.get("timeout_rate", 0.0),
        "total_score": scores.get("total", 0.0),
        "score_per_task_avg": scores.get("per_task_average", 0.0),
        "throughput_tasks_per_hour": timing.get("throughput_tasks_per_hour", 0.0),
        "avg_completion_duration_sec": timing.get("avg_completion_duration_sec", 0.0),
        "total_fleet_distance_m": distance.get("total_fleet_traveled", 0.0),
        "fleet_distance_stdev_m": distance.get("fleet_distance_stdev", 0.0),
        "total_energy_kwh": energy.get("total_energy", 0.0),
        "stranded_vehicles": vehicles.get("stranded", 0),
        "run_dir": str(run_dir),
    }


CSV_FIELDS = [
    "scale",
    "seed",
    "algorithm",
    "experiment_name",
    "stop_reason",
    "sim_seconds_elapsed",
    "wall_seconds_elapsed",
    "tasks_total",
    "tasks_completed",
    "tasks_on_time",
    "tasks_timeout",
    "completion_rate",
    "on_time_rate",
    "timeout_rate",
    "total_score",
    "score_per_task_avg",
    "throughput_tasks_per_hour",
    "avg_completion_duration_sec",
    "total_fleet_distance_m",
    "fleet_distance_stdev_m",
    "total_energy_kwh",
    "stranded_vehicles",
    "run_dir",
]


def _save_csv(rows: List[Dict[str, Any]], csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"[CSV] {csv_path}")


def _plot_comparison(rows: List[Dict[str, Any]], png_path: Path, *, title: str) -> None:
    if not rows:
        return

    algorithms = [r["algorithm"] for r in rows]
    scores = [float(r["total_score"]) for r in rows]
    n = len(algorithms)

    fig_w = max(11.0, n * 1.35)
    fig, ax = plt.subplots(figsize=(fig_w, 6.0))
    x = list(range(n))
    bars = ax.bar(x, scores, width=0.62, color="#4C72B0", edgecolor="white", linewidth=0.8)

    ax.set_title("Total Score", fontsize=13, pad=12)
    ax.set_ylabel("Score", fontsize=11)
    ax.set_xticks(x)
    ax.set_xticklabels(
        [name.replace("_", "\n") for name in algorithms],
        fontsize=9,
        ha="center",
        rotation=0,
    )
    ax.set_xlim(-0.6, n - 0.4)
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.set_axisbelow(True)

    ymax = max(scores) if scores else 1.0
    ax.set_ylim(0, ymax * 1.12)

    for bar, val in zip(bars, scores):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"{val:.1f}",
            ha="center",
            va="bottom",
            fontsize=8,
            rotation=0,
        )

    fig.suptitle(title, fontsize=14, y=0.98)
    fig.tight_layout(rect=(0, 0.03, 1, 0.94))
    png_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[Plot] {png_path}")


def _replot_all_seeds() -> None:
    """从已有 results.csv 重新绘制各 seed 的 comparison.png。"""
    for scale, meta in SCALE_CONFIGS.items():
        seed_count = int(meta["seed_count"])
        for seed_idx in range(1, seed_count + 1):
            csv_path = EXPERIMENT_ROOT / scale / f"seed_{seed_idx}" / "results.csv"
            if not csv_path.exists():
                continue
            with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            png_path = EXPERIMENT_ROOT / scale / f"seed_{seed_idx}" / "comparison.png"
            _plot_comparison(
                rows,
                png_path,
                title=f"{scale} / seed {seed_idx} — dynamic algorithms",
            )


def _seed_is_complete(scale: str, seed_idx: int) -> bool:
    csv_path = EXPERIMENT_ROOT / scale / f"seed_{seed_idx}" / "results.csv"
    png_path = EXPERIMENT_ROOT / scale / f"seed_{seed_idx}" / "comparison.png"
    return csv_path.exists() and png_path.exists()


def _algorithms_from(from_algorithm: Optional[str], *, reverse: bool = False) -> List[str]:
    if not from_algorithm:
        order = list(reversed(DYNAMIC_ALGORITHMS)) if reverse else list(DYNAMIC_ALGORITHMS)
        return order
    if from_algorithm not in DYNAMIC_ALGORITHMS:
        raise ValueError(
            f"未知算法: {from_algorithm}，可选: {', '.join(DYNAMIC_ALGORITHMS)}"
        )
    idx = DYNAMIC_ALGORITHMS.index(from_algorithm)
    if reverse:
        return list(reversed(DYNAMIC_ALGORITHMS[: idx + 1]))
    return DYNAMIC_ALGORITHMS[idx:]


def _seed_logs_complete(scale: str, seed_idx: int) -> bool:
    for algorithm in DYNAMIC_ALGORITHMS:
        log_path = _run_dir(scale, seed_idx, algorithm) / "log.txt"
        if not log_path.exists():
            return False
        try:
            _parse_results_from_log(log_path)
        except ValueError:
            return False
    return True


def _parse_scale_seed(value: str) -> tuple[str, int]:
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError(f"格式应为 scale:seed，例如 large:1，收到: {value}")
    scale, seed_raw = parts
    if scale not in SCALE_CONFIGS:
        raise ValueError(f"未知规模: {scale}")
    seed_idx = int(seed_raw)
    if seed_idx < 1:
        raise ValueError(f"seed 必须 >= 1，收到: {seed_raw}")
    return scale, seed_idx


def _finalize_seed_batch(*, scale: str, seed_idx: int) -> List[Dict[str, Any]]:
    if not _seed_logs_complete(scale, seed_idx):
        missing = [
            algo
            for algo in DYNAMIC_ALGORITHMS
            if not (_run_dir(scale, seed_idx, algo) / "log.txt").exists()
            or not _log_is_complete(_run_dir(scale, seed_idx, algo) / "log.txt")
        ]
        raise RuntimeError(
            f"{scale} seed {seed_idx} 尚未齐套，缺少或未完成的算法: {', '.join(missing)}"
        )
    seed_dir = EXPERIMENT_ROOT / scale / f"seed_{seed_idx}"
    rows = _collect_seed_result_rows(scale=scale, seed_idx=seed_idx)
    csv_path = seed_dir / "results.csv"
    png_path = seed_dir / "comparison.png"
    _save_csv(rows, csv_path)
    _plot_comparison(
        rows,
        png_path,
        title=f"{scale} / seed {seed_idx} — dynamic algorithms",
    )
    return rows


def _log_is_complete(log_path: Path) -> bool:
    try:
        _parse_results_from_log(log_path)
        return True
    except ValueError:
        return False


def _collect_seed_result_rows(
    *,
    scale: str,
    seed_idx: int,
    algorithms: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """从已有 log.txt 汇总一个 seed 的结果（用于续跑后生成完整 CSV）。"""
    target = algorithms or DYNAMIC_ALGORITHMS
    rows: List[Dict[str, Any]] = []
    for algorithm in target:
        log_path = _run_dir(scale, seed_idx, algorithm) / "log.txt"
        if not log_path.exists():
            raise FileNotFoundError(
                f"缺少算法结果，无法汇总 CSV: {scale} seed {seed_idx} / {algorithm}"
            )
        results = _parse_results_from_log(log_path)
        rows.append(
            _flatten_result_row(
                scale=scale,
                seed_idx=seed_idx,
                algorithm=algorithm,
                results=results,
                run_dir=_run_dir(scale, seed_idx, algorithm),
            )
        )
    return rows


def _parse_resume_from(value: str) -> tuple[str, int, str]:
    """解析 resume 参数，格式 scale:seed:algorithm，例如 medium:1:cluster_auction_mas。"""
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError(
            f"--resume-from 格式应为 scale:seed:algorithm，例如 medium:1:cluster_auction_mas，"
            f"收到: {value}"
        )
    scale, seed_raw, algorithm = parts
    if scale not in SCALE_CONFIGS:
        raise ValueError(f"未知规模: {scale}")
    seed_idx = int(seed_raw)
    if seed_idx < 1:
        raise ValueError(f"seed 必须 >= 1，收到: {seed_raw}")
    if algorithm not in DYNAMIC_ALGORITHMS:
        raise ValueError(f"未知算法: {algorithm}")
    return scale, seed_idx, algorithm


def _run_single_algorithm(
    *,
    base_cfg: Dict[str, Any],
    scale: str,
    seed_idx: int,
    algorithm: str,
    seed_file: Optional[Path],
    dry_run: bool,
    skip_existing: bool,
) -> Dict[str, Any]:
    seed_dir = EXPERIMENT_ROOT / scale / f"seed_{seed_idx}"
    cfg_dir = seed_dir / "configs"
    cfg_path = cfg_dir / f"{algorithm}.yaml"
    run_cfg = _build_run_config(
        base_cfg,
        scale=scale,
        seed_idx=seed_idx,
        algorithm=algorithm,
        seed_file=seed_file,
    )
    _dump_yaml(cfg_path, run_cfg)

    out_dir = _run_dir(scale, seed_idx, algorithm)
    log_path = out_dir / "log.txt"
    if skip_existing and log_path.exists():
        try:
            results = _parse_results_from_log(log_path)
            print(f"[Skip] 已有结果，跳过运行: {out_dir.name}")
            return _flatten_result_row(
                scale=scale,
                seed_idx=seed_idx,
                algorithm=algorithm,
                results=results,
                run_dir=out_dir,
            )
        except ValueError:
            print(f"[Warn] 日志不完整，将重新运行: {out_dir.name}")

    rc = _run_headless(cfg_path, dry_run=dry_run)
    if rc != 0:
        raise RuntimeError(f"实验失败 (exit={rc}): {algorithm} @ {scale} seed {seed_idx}")

    if dry_run:
        return _flatten_result_row(
            scale=scale,
            seed_idx=seed_idx,
            algorithm=algorithm,
            results={
                "experiment_name": run_cfg["experiment"]["name"],
                "stop_reason": "dry_run",
                "sim_seconds_elapsed": 0,
                "wall_seconds_elapsed": 0,
                "tasks": {},
                "scores": {"total": 0},
                "timing": {},
                "distance_meters": {},
                "energy": {},
                "vehicles_summary": {},
            },
            run_dir=out_dir,
        )

    if not log_path.exists():
        raise FileNotFoundError(f"缺少日志文件: {log_path}")

    results = _parse_results_from_log(log_path)
    return _flatten_result_row(
        scale=scale,
        seed_idx=seed_idx,
        algorithm=algorithm,
        results=results,
        run_dir=out_dir,
    )


def _run_seed_batch(
    *,
    scale: str,
    seed_idx: int,
    base_cfg: Dict[str, Any],
    dry_run: bool,
    skip_existing: bool,
    reuse_seed: bool = False,
    from_algorithm: Optional[str] = None,
    reverse: bool = False,
) -> List[Dict[str, Any]]:
    seed_dir = EXPERIMENT_ROOT / scale / f"seed_{seed_idx}"
    seed_dir.mkdir(parents=True, exist_ok=True)
    shared_seed_path = seed_dir / "task_generation_seed.yaml"
    algorithms_to_run = _algorithms_from(from_algorithm, reverse=reverse)

    print(f"\n{'=' * 72}")
    print(f"规模={scale}  seed={seed_idx}")
    if reverse:
        print("运行顺序: 倒序（从 relay_handoff → … → priority_task）")
    if from_algorithm:
        print(f"续跑起点: {from_algorithm}（含）")
    if reuse_seed or reverse:
        print("复用已有 task_generation_seed.yaml")
    print(f"{'=' * 72}")

    if skip_existing and _seed_is_complete(scale, seed_idx):
        print("[Skip] 该 seed 已全部完成，直接读取 CSV")
        csv_path = seed_dir / "results.csv"
        rows: List[Dict[str, Any]] = []
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        return rows

    if reverse:
        if not shared_seed_path.exists() and not dry_run:
            raise FileNotFoundError(
                f"倒序模式需要已有 seed 文件: {shared_seed_path}\n"
                "请先在另一台机器正序跑完 nearest_task，或复制 task_generation_seed.yaml 过来。"
            )
        reuse_seed = True
        algorithms_to_run = [a for a in algorithms_to_run if a != SEED_GENERATOR]
    elif reuse_seed:
        if not shared_seed_path.exists() and not dry_run:
            raise FileNotFoundError(
                f"续跑需要已有 seed 文件，但未找到: {shared_seed_path}"
            )
    else:
        # 正序：nearest_task 生成 seed
        _run_single_algorithm(
            base_cfg=base_cfg,
            scale=scale,
            seed_idx=seed_idx,
            algorithm=SEED_GENERATOR,
            seed_file=None,
            dry_run=dry_run,
            skip_existing=skip_existing,
        )

        generated_seed = _run_dir(scale, seed_idx, SEED_GENERATOR) / "task_generation_seed.yaml"
        if not dry_run:
            if not generated_seed.exists():
                raise FileNotFoundError(f"nearest_task 未生成 seed 文件: {generated_seed}")
            shutil.copy2(generated_seed, shared_seed_path)
            print(f"[Seed] 已保存共享 seed: {shared_seed_path}")

        algorithms_to_run = [a for a in algorithms_to_run if a != SEED_GENERATOR]

    print(f"本批算法 ({len(algorithms_to_run)}): {', '.join(algorithms_to_run)}")

    for algorithm in algorithms_to_run:
        seed_file = None
        if algorithm == SEED_GENERATOR and not reuse_seed:
            seed_file = None
        elif not dry_run:
            seed_file = shared_seed_path
        _run_single_algorithm(
            base_cfg=base_cfg,
            scale=scale,
            seed_idx=seed_idx,
            algorithm=algorithm,
            seed_file=seed_file,
            dry_run=dry_run,
            skip_existing=skip_existing,
        )

    if dry_run:
        return []

    if _seed_logs_complete(scale, seed_idx):
        rows = _collect_seed_result_rows(scale=scale, seed_idx=seed_idx)
        csv_path = seed_dir / "results.csv"
        png_path = seed_dir / "comparison.png"
        _save_csv(rows, csv_path)
        _plot_comparison(
            rows,
            png_path,
            title=f"{scale} / seed {seed_idx} — dynamic algorithms",
        )
        return rows

    done = sum(
        1
        for algo in DYNAMIC_ALGORITHMS
        if _log_is_complete(_run_dir(scale, seed_idx, algo) / "log.txt")
    )
    print(
        f"[Partial] 已完成 {done}/{len(DYNAMIC_ALGORITHMS)} 个算法。"
        f"两台机器都跑完后执行: python scripts/run_dynamic_benchmark.py "
        f"--finalize-seed {scale}:{seed_idx}"
    )
    return []


def run_benchmark(
    *,
    scales: List[str],
    dry_run: bool = False,
    skip_existing: bool = False,
    resume_from: Optional[tuple[str, int, str]] = None,
    reverse: bool = False,
) -> None:
    all_rows: List[Dict[str, Any]] = []
    resume_applied = False

    for scale in scales:
        if scale not in SCALE_CONFIGS:
            raise ValueError(f"未知规模: {scale}，可选: {list(SCALE_CONFIGS)}")

        cfg_path = PROJECT_ROOT / SCALE_CONFIGS[scale]["yaml"]
        base_cfg = _load_yaml(cfg_path)
        seed_count = int(SCALE_CONFIGS[scale]["seed_count"])

        print(f"\n>>> 规模 {scale}: {cfg_path}  (seeds={seed_count})")

        for seed_idx in range(1, seed_count + 1):
            reuse_seed = reverse
            from_algorithm: Optional[str] = None
            if (
                resume_from
                and not resume_applied
                and resume_from[0] == scale
                and resume_from[1] == seed_idx
            ):
                reuse_seed = True
                from_algorithm = resume_from[2]
                resume_applied = True
                print(
                    f"[Resume] 从 {scale} seed {seed_idx} / {from_algorithm} 继续，"
                    "复用已有 seed"
                )

            rows = _run_seed_batch(
                scale=scale,
                seed_idx=seed_idx,
                base_cfg=base_cfg,
                dry_run=dry_run,
                skip_existing=skip_existing,
                reuse_seed=reuse_seed,
                from_algorithm=from_algorithm,
                reverse=reverse,
            )
            all_rows.extend(rows)

    if not dry_run:
        summary_csv = EXPERIMENT_ROOT / "all_results.csv"
        merged: List[Dict[str, Any]] = []
        for scale, meta in SCALE_CONFIGS.items():
            for seed_idx in range(1, int(meta["seed_count"]) + 1):
                csv_path = EXPERIMENT_ROOT / scale / f"seed_{seed_idx}" / "results.csv"
                if csv_path.exists():
                    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
                        merged.extend(list(csv.DictReader(f)))
        if merged:
            _save_csv(merged, summary_csv)
            print(f"\n[Done] 汇总 CSV: {summary_csv}")
        elif all_rows:
            _save_csv(all_rows, summary_csv)
            print(f"\n[Done] 汇总 CSV: {summary_csv}")
        else:
            print("\n[Done] 本批为部分运行，全部完成后请 --finalize-seed")
    else:
        print("\n[Done] dry-run 完成（未写入 CSV/图表）")


def main() -> None:
    parser = argparse.ArgumentParser(description="NEFT 动态调度算法批量对比实验")
    parser.add_argument(
        "--scales",
        nargs="+",
        choices=list(SCALE_CONFIGS.keys()),
        default=list(SCALE_CONFIGS.keys()),
        help="要运行的规模（默认全部）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只生成配置并打印命令，不真正跑仿真",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="若某算法 log.txt 已有完整结果则跳过该算法；若 seed 已全部完成则整批跳过",
    )
    parser.add_argument(
        "--resume-from",
        metavar="SCALE:SEED:ALGORITHM",
        help="断点续跑，例如 medium:1:cluster_auction_mas（复用已有 seed，从该算法起跑）",
    )
    parser.add_argument(
        "--reverse",
        action="store_true",
        help="倒序跑算法（relay_handoff → … → priority_task），需已有 task_generation_seed.yaml",
    )
    parser.add_argument(
        "--finalize-seed",
        metavar="SCALE:SEED",
        help="10 个算法 log 齐套后汇总 CSV + 柱状图，例如 large:1",
    )
    parser.add_argument(
        "--replot",
        action="store_true",
        help="从已有 results.csv 重新生成所有 comparison.png（不跑仿真）",
    )
    args = parser.parse_args()

    if args.replot:
        _replot_all_seeds()
        print("[Done] 已重新绘制所有 comparison.png")
        return

    if args.finalize_seed:
        scale, seed_idx = _parse_scale_seed(args.finalize_seed)
        _finalize_seed_batch(scale=scale, seed_idx=seed_idx)
        print(f"[Done] 已汇总 {scale} seed {seed_idx}")
        return

    resume_from = None
    if args.resume_from:
        resume_from = _parse_resume_from(args.resume_from)

    print("Dynamic algorithms:", ", ".join(DYNAMIC_ALGORITHMS))
    if args.reverse:
        print("Reverse order:", ", ".join(reversed(DYNAMIC_ALGORITHMS)))
    print("Seed generator:", SEED_GENERATOR)
    print("Output root:", EXPERIMENT_ROOT)

    run_benchmark(
        scales=args.scales,
        dry_run=args.dry_run,
        skip_existing=args.skip_existing,
        resume_from=resume_from,
        reverse=args.reverse,
    )


if __name__ == "__main__":
    main()
