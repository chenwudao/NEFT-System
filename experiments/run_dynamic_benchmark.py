#!/usr/bin/env python3
"""
动态调度算法批量对比实验。

流程（每个规模 × 每个 seed）：
  1. 用 nearest_task 无种子回放跑一次，录制 task_generation_seed.yaml
  2. 其余 dynamic 算法读取同一份 seed 回放，保证任务流一致
  3. 汇总 CSV + 柱状图（每跑完一个 seed 的全部算法即输出一次）

规模与 seed 数量：
  - small  : 2 个 seed
  - medium : 1 个 seed
  - large  : 1 个 seed

用法（在项目根目录）：
  python experiments/run_dynamic_benchmark.py
  python experiments/run_dynamic_benchmark.py --scale small --seed-index 1
  python experiments/run_dynamic_benchmark.py --dry-run

依赖：pyyaml；绘图需 matplotlib（pip install matplotlib）。
"""

from __future__ import annotations

import argparse
import copy
import csv
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

try:
    import yaml
except ImportError as exc:
    raise SystemExit("缺少 pyyaml，请先执行: pip install pyyaml") from exc

# ---------------------------------------------------------------------------
# 路径与常量
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIGS_DIR = PROJECT_ROOT / "configs" / "dynamic"
OUTPUT_ROOT = PROJECT_ROOT / "experiments" / "dynamic_benchmark"
MAIN_SCRIPT = PROJECT_ROOT / "backend" / "main.py"

SCALE_SEED_COUNTS: Dict[str, int] = {
    "small": 1,
    "medium": 1,
    "large": 1,
}

# 与 backend/algorithm/schedulers/dynamic/__init__.py 保持一致
DYNAMIC_ALGORITHMS: List[str] = [
    "nearest_task",
    "priority_task",
    "heaviest_task",
    "deadline_earliest",
    "dfs_score_search",
    "sa_score_search",
    "rl_batch",
    "regional_planning",
    "cluster_auction_mas",
    "relay_handoff",
]

SEED_GENERATOR = "nearest_task"
YAML_RESULTS_MARKER = "---- 完整结果（YAML） ----"

CSV_COLUMNS = [
    "scale",
    "seed_index",
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
    "per_task_average",
    "throughput_tasks_per_hour",
    "total_fleet_traveled_m",
    "log_dir",
    "seed_file",
    "wall_run_seconds",
]


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _load_base_config(scale: str) -> Dict[str, Any]:
    path = CONFIGS_DIR / f"{scale}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"找不到规模配置: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"配置格式错误: {path}")
    return data


def _write_temp_config(payload: Dict[str, Any]) -> Path:
    fd, raw_path = tempfile.mkstemp(
        prefix="neft_benchmark_",
        suffix=".yaml",
        dir=str(PROJECT_ROOT),
    )
    os.close(fd)
    path = Path(raw_path)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)
    return path


def _build_run_config(
    scale: str,
    seed_index: int,
    algorithm: str,
    *,
    seed_file: Optional[Path],
    runs_log_dir: Path,
) -> Dict[str, Any]:
    """基于 configs/dynamic/<scale>.yaml 构造单次 headless 运行配置。"""
    cfg = _load_base_config(scale)

    exp_name = f"{scale}-seed{seed_index}-{algorithm}"
    overrides: Dict[str, Any] = {
        "experiment": {
            "name": exp_name,
            "log_dir": str(runs_log_dir.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        },
        "optimization": {"mode": "dynamic"},
        "scheduling": {"strategy": algorithm},
    }

    task_override: Dict[str, Any] = {}
    if seed_file is not None:
        task_override["generation_seed_file"] = str(seed_file.resolve()).replace("\\", "/")
    else:
        # 强制录制新 seed：去掉 yaml 里可能残留的旧 seed 路径
        task_override["generation_seed_file"] = None

    overrides["task"] = task_override
    merged = _deep_merge(cfg, overrides)

    # None 表示不写 seed 文件字段（record 模式）
    if seed_file is None and "task" in merged:
        merged["task"].pop("generation_seed_file", None)

    return merged


def _run_headless(config_path: Path, *, dry_run: bool = False) -> Path:
    """启动 backend/main.py --headless，返回实验 log 目录。"""
    cmd = [
        sys.executable,
        str(MAIN_SCRIPT),
        "--cfg",
        str(config_path),
        "--headless",
    ]
    print(f"  [RUN] {' '.join(cmd)}")

    if dry_run:
        return PROJECT_ROOT / "log" / "dry-run-placeholder"

    started = time.time()
    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    elapsed = time.time() - started

    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError(f"headless 运行失败 (exit={proc.returncode})")

    log_dir = _extract_log_dir(proc.stdout + "\n" + proc.stderr)
    if log_dir is None:
        raise RuntimeError("无法从输出中解析 log_dir，请检查 headless 是否正常结束")
    print(f"  [DONE] log_dir={log_dir}  wall={elapsed:.1f}s")
    return log_dir


def _extract_log_dir(output: str) -> Optional[Path]:
    match = re.search(r"\[Headless\] finished\.[^\n]*log_dir=(.+)", output)
    if not match:
        return None
    raw = match.group(1).strip()
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _parse_results_from_log(log_dir: Path) -> Dict[str, Any]:
    log_path = log_dir / "log.txt"
    if not log_path.exists():
        raise FileNotFoundError(f"缺少 log.txt: {log_path}")

    text = log_path.read_text(encoding="utf-8")
    marker_idx = text.rfind(YAML_RESULTS_MARKER)
    if marker_idx < 0:
        raise ValueError(f"log.txt 中未找到结果段: {log_path}")

    yaml_text = text[marker_idx + len(YAML_RESULTS_MARKER) :].strip()
    payload = yaml.safe_load(yaml_text)
    if not isinstance(payload, dict):
        raise ValueError(f"结果 YAML 解析失败: {log_path}")
    return payload


def _flatten_result_row(
    *,
    scale: str,
    seed_index: int,
    algorithm: str,
    results: Dict[str, Any],
    log_dir: Path,
    seed_file: Optional[Path],
    wall_run_seconds: float,
) -> Dict[str, Any]:
    tasks = results.get("tasks") or {}
    scores = results.get("scores") or {}
    timing = results.get("timing") or {}
    distance = results.get("distance_meters") or {}

    return {
        "scale": scale,
        "seed_index": seed_index,
        "algorithm": algorithm,
        "experiment_name": results.get("experiment_name", ""),
        "stop_reason": results.get("stop_reason", ""),
        "sim_seconds_elapsed": results.get("sim_seconds_elapsed", 0.0),
        "wall_seconds_elapsed": results.get("wall_seconds_elapsed", 0.0),
        "tasks_total": tasks.get("total", 0),
        "tasks_completed": tasks.get("completed", 0),
        "tasks_on_time": tasks.get("on_time", 0),
        "tasks_timeout": tasks.get("timeout", 0),
        "completion_rate": tasks.get("completion_rate", 0.0),
        "on_time_rate": tasks.get("on_time_rate", 0.0),
        "timeout_rate": tasks.get("timeout_rate", 0.0),
        "total_score": scores.get("total", 0.0),
        "per_task_average": scores.get("per_task_average", 0.0),
        "throughput_tasks_per_hour": timing.get("throughput_tasks_per_hour", 0.0),
        "total_fleet_traveled_m": distance.get("total_fleet_traveled", 0.0),
        "log_dir": str(log_dir),
        "seed_file": str(seed_file) if seed_file else "",
        "wall_run_seconds": round(wall_run_seconds, 2),
    }


def _write_csv(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in CSV_COLUMNS})


def _plot_comparison(rows: Sequence[Dict[str, Any]], out_path: Path, title: str) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        print(f"  [WARN] 未安装 matplotlib，跳过绘图: {exc}")
        return

    if not rows:
        return

    # Windows 中文显示
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    algorithms = [str(r["algorithm"]) for r in rows]
    total_scores = [float(r.get("total_score") or 0.0) for r in rows]
    completion_rates = [float(r.get("completion_rate") or 0.0) * 100.0 for r in rows]
    on_time_rates = [float(r.get("on_time_rate") or 0.0) * 100.0 for r in rows]

    x = range(len(algorithms))
    width = 0.35

    fig, axes = plt.subplots(1, 2, figsize=(max(12, len(algorithms) * 1.2), 5))
    fig.suptitle(title, fontsize=13)

    ax0 = axes[0]
    bars0 = ax0.bar(x, total_scores, color="#4C72B0")
    ax0.set_title("总得分")
    ax0.set_xticks(list(x))
    ax0.set_xticklabels(algorithms, rotation=35, ha="right")
    ax0.set_ylabel("Score")
    for bar, val in zip(bars0, total_scores):
        ax0.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{val:.0f}",
                 ha="center", va="bottom", fontsize=8)

    ax1 = axes[1]
    bars1 = ax1.bar([i - width / 2 for i in x], completion_rates, width=width,
                    label="完成率 %", color="#55A868")
    bars2 = ax1.bar([i + width / 2 for i in x], on_time_rates, width=width,
                    label="按时率 %", color="#C44E52")
    ax1.set_title("完成率 / 按时率")
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(algorithms, rotation=35, ha="right")
    ax1.set_ylabel("Percent")
    ax1.set_ylim(0, 105)
    ax1.legend()

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [PLOT] {out_path}")


def _copy_seed_artifact(log_dir: Path, seed_path: Path) -> None:
    src = log_dir / "task_generation_seed.yaml"
    if not src.exists():
        raise FileNotFoundError(f"nearest_task 未生成 seed 文件: {src}")
    seed_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, seed_path)
    print(f"  [SEED] 已保存: {seed_path}")


def _run_single_algorithm(
    *,
    scale: str,
    seed_index: int,
    algorithm: str,
    seed_file: Optional[Path],
    runs_log_dir: Path,
    dry_run: bool,
) -> Dict[str, Any]:
    cfg = _build_run_config(
        scale,
        seed_index,
        algorithm,
        seed_file=seed_file,
        runs_log_dir=runs_log_dir,
    )
    temp_cfg = _write_temp_config(cfg)
    try:
        t0 = time.time()
        log_dir = _run_headless(temp_cfg, dry_run=dry_run)
        wall_run = time.time() - t0

        if dry_run:
            return {
                "scale": scale,
                "seed_index": seed_index,
                "algorithm": algorithm,
                "total_score": 0.0,
                "completion_rate": 0.0,
                "on_time_rate": 0.0,
                "log_dir": str(log_dir),
                "seed_file": str(seed_file) if seed_file else "",
                "wall_run_seconds": 0.0,
            }

        results = _parse_results_from_log(log_dir)
        return _flatten_result_row(
            scale=scale,
            seed_index=seed_index,
            algorithm=algorithm,
            results=results,
            log_dir=log_dir,
            seed_file=seed_file,
            wall_run_seconds=wall_run,
        )
    finally:
        try:
            temp_cfg.unlink(missing_ok=True)
        except OSError:
            pass


def run_seed_batch(
    scale: str,
    seed_index: int,
    *,
    algorithms: Sequence[str],
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    """跑完一个规模下的单个 seed：直接使用已有的 seed_1 种子进行回放。"""
    seed_dir = OUTPUT_ROOT / scale / f"seed_{seed_index}"
    runs_log_dir = seed_dir / "runs"
    
    # 动态算法已存的 seed_1 路径
    existing_seed_rel = f"log/benchmarks/dynamic/{scale}/seed_{seed_index}/nearest_task/task_generation_seed.yaml"
    shared_seed_path = PROJECT_ROOT / existing_seed_rel

    print(f"\n{'=' * 60}")
    print(f"规模={scale}  seed={seed_index}  算法数={len(algorithms)}")
    print(f"使用种子文件: {existing_seed_rel}")
    print(f"输出目录: {seed_dir}")
    print(f"{'=' * 60}")

    if not dry_run and not shared_seed_path.exists():
        raise FileNotFoundError(f"找不到已有的种子文件: {shared_seed_path}")

    # 把已有的种子文件拷贝到输出目录，方便查看
    if not dry_run:
        seed_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(shared_seed_path, seed_dir / "task_generation_seed.yaml")

    rows: List[Dict[str, Any]] = []

    # 所有算法，包括 nearest_task，都通过同一份已有种子回放运行
    for idx, algorithm in enumerate(algorithms, start=1):
        print(f"\n[{idx}/{len(algorithms)}] 回放 seed: {algorithm}")
        row = _run_single_algorithm(
            scale=scale,
            seed_index=seed_index,
            algorithm=algorithm,
            seed_file=shared_seed_path if not dry_run else None,
            runs_log_dir=runs_log_dir,
            dry_run=dry_run,
        )
        rows.append(row)

    # 3) 写 CSV + 柱状图
    csv_path = seed_dir / "results.csv"
    plot_path = seed_dir / "comparison.png"
    _write_csv(csv_path, rows)
    print(f"\n  [CSV] {csv_path}")

    plot_title = f"{scale} / seed_{seed_index} — 动态算法对比"
    _plot_comparison(rows, plot_path, plot_title)

    return rows


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NEFT 动态算法多规模批量实验")
    parser.add_argument(
        "--scale",
        choices=["small", "medium", "large", "all"],
        default="all",
        help="只跑指定规模（默认 all）",
    )
    parser.add_argument(
        "--seed-index",
        type=int,
        default=None,
        help="只跑指定 seed 编号（默认按规模配置全部跑）",
    )
    parser.add_argument(
        "--algorithms",
        nargs="+",
        default=None,
        help="只跑指定算法（默认全部 dynamic 算法）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要执行的命令，不真正跑仿真",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    scales = ["small", "medium", "large"] if args.scale == "all" else [args.scale]
    algorithms = list(args.algorithms or DYNAMIC_ALGORITHMS)

    if SEED_GENERATOR not in algorithms:
        algorithms.insert(0, SEED_GENERATOR)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now()
    print(f"项目根目录: {PROJECT_ROOT}")
    print(f"实验输出:   {OUTPUT_ROOT}")
    print(f"开始时间:   {started_at.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"规模:       {scales}")
    print(f"算法:       {algorithms}")

    all_rows: List[Dict[str, Any]] = []

    for scale in scales:
        seed_count = SCALE_SEED_COUNTS[scale]
        seed_indices = (
            [args.seed_index]
            if args.seed_index is not None
            else list(range(1, seed_count + 1))
        )

        scale_rows: List[Dict[str, Any]] = []
        for seed_index in seed_indices:
            if seed_index < 1 or seed_index > seed_count:
                print(f"[SKIP] {scale} 不支持 seed_{seed_index}（共 {seed_count} 个）")
                continue
            rows = run_seed_batch(
                scale,
                seed_index,
                algorithms=algorithms,
                dry_run=args.dry_run,
            )
            scale_rows.extend(rows)
            all_rows.extend(rows)

        if scale_rows and not args.dry_run:
            scale_csv = OUTPUT_ROOT / scale / "all_seeds_results.csv"
            _write_csv(scale_csv, scale_rows)
            print(f"\n[CSV] 规模汇总: {scale_csv}")

    if all_rows and not args.dry_run:
        summary_csv = OUTPUT_ROOT / "summary_all_results.csv"
        _write_csv(summary_csv, all_rows)
        print(f"\n[CSV] 全局汇总: {summary_csv}")

    elapsed = (datetime.now() - started_at).total_seconds()
    print(f"\n全部完成，耗时 {elapsed / 60:.1f} 分钟。")


if __name__ == "__main__":
    main()
