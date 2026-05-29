#!/usr/bin/env python
"""静态求解器种子评测脚本。

通过复用指定的动态实验种子 (seed_1)，运行上帝视角的静态求解器 (StaticExactSolver)
计算在小、中、大三种规模下的全局优化/最优得分。
"""

import argparse
import subprocess
import sys
from pathlib import Path
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXE = sys.executable

def read_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)

def parse_final_results_from_log(log_txt: Path) -> dict:
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

def main():
    parser = argparse.ArgumentParser(description="Run static solver benchmarks on seed_1.")
    parser.add_argument(
        "--solver",
        default="gurobi",
        choices=["gurobi", "or-tools", "ortools"],
        help="MIP solver to use (default: gurobi)"
    )
    parser.add_argument(
        "--time-limit-s",
        type=int,
        default=None,
        help="Gurobi time limit in seconds (default: None, representing unlimited)"
    )
    parser.add_argument(
        "--no-strict",
        action="store_false",
        dest="strict",
        help="Disable strict mathematical optimality (allow default gap)"
    )
    parser.set_defaults(strict=True)
    args = parser.parse_args()
    
    # 标准的 seed_1 种子路径
    seeds = {
        "small": "log/benchmarks/dynamic/small/seed_1/nearest_task/task_generation_seed.yaml",
        "medium": "log/benchmarks/dynamic/medium/seed_1/nearest_task/task_generation_seed.yaml",
        "large": "log/benchmarks/dynamic/large/seed_1/nearest_task/task_generation_seed.yaml",
    }
    
    results = []
    
    print("=" * 60)
    print(f"开始运行静态求解器进行评测，选择求解器: {args.solver}")
    print("=" * 60)
    
    for scale, seed_rel_path in seeds.items():
        seed_path = PROJECT_ROOT / seed_rel_path
        if not seed_path.exists():
            print(f"[跳过] 找不到种子文件: {seed_rel_path}")
            continue
            
        print(f"\n[运行] 规模={scale} | 正在加载种子: {seed_rel_path}...")
        
        # 1. 读取基础配置
        base_cfg_path = PROJECT_ROOT / "configs" / "dynamic" / f"{scale}.yaml"
        if not base_cfg_path.exists():
            base_cfg_path = PROJECT_ROOT / "configs" / f"{scale}.yaml"
            
        base_cfg = read_yaml(base_cfg_path)
        
        # 2. 构造静态模式配置
        cfg = yaml.safe_load(yaml.safe_dump(base_cfg)) # deepcopy
        
        # 修改为静态上帝视角模式
        opt = cfg.setdefault("optimization", {})
        opt["mode"] = "static"
        static_opt = opt.setdefault("static", {})
        static_opt["strategy"] = "static_exact_solver"
        static_opt["solver"] = "or-tools" if args.solver in ("or-tools", "ortools") else "gurobi"
        # 调优参数，默认解除限制以运行最优解模式
        static_opt["strict_global_optimum"] = args.strict
        static_opt["mip_gap_threshold"] = 0.0 if args.strict else 0.05
        static_opt["time_limit_s"] = args.time_limit_s
        
        # 指定调度算法
        sched = cfg.setdefault("scheduling", {})
        sched["strategy"] = "static_exact_solver"
        
        # 指定实验与日志目录
        exp = cfg.setdefault("experiment", {})
        log_dir = PROJECT_ROOT / "log" / "benchmarks" / "static" / scale / "seed_1"
        exp["log_dir"] = str(log_dir.as_posix())
        exp["name"] = "static_exact_solver"
        
        # 绑定种子数据文件，使其进行 replay 回放
        task_cfg = cfg.setdefault("task", {})
        task_cfg["generation_seed_file"] = str(seed_path.as_posix())
        
        # 3. 输出临时配置文件并运行
        temp_cfg_path = PROJECT_ROOT / "benchmark_results" / "static" / "generated_configs" / f"{scale}_static.yaml"
        write_yaml(temp_cfg_path, cfg)
        
        try:
            run_headless(temp_cfg_path)
            
            # 4. 解析结果
            run_log_dir = log_dir / "static_exact_solver"
            metrics = parse_final_results_from_log(run_log_dir / "log.txt")
            
            score = metrics.get("scores", {}).get("total", 0.0)
            tasks_info = metrics.get("tasks", {})
            comp_rate = tasks_info.get("completion_rate", 0.0)
            
            results.append({
                "scale": scale,
                "score": score,
                "completed": tasks_info.get("completed", 0),
                "total_tasks": tasks_info.get("total", 0),
                "completion_rate": comp_rate * 100,
                "log_path": str((run_log_dir / "log.txt").relative_to(PROJECT_ROOT))
            })
            
            print(f"[成功] 规模={scale} 完成！得分: {score:.2f} | 完成率: {comp_rate*100:.1f}%")
        except Exception as e:
            print(f"[失败] 规模={scale} 运行出错: {e}")
            import traceback
            traceback.print_exc()
            
    # 输出对比表格
    print("\n" + "=" * 60)
    print(" 静态上帝视角求解器 (Static Solver) 评测汇总 ")
    print("=" * 60)
    print(f"{'规模 (Scale)':<12} | {'总得分 (Score)':<14} | {'完成数/总任务':<15} | {'完成率':<8}")
    print("-" * 60)
    for r in results:
        tasks_ratio = f"{r['completed']}/{r['total_tasks']}"
        print(f"{r['scale']:<12} | {r['score']:<14.2f} | {tasks_ratio:<15} | {r['completion_rate']:.1f}%")
    print("=" * 60)
    print("所有详细日志保存在 log/benchmarks/static/ 下的各规模目录中。\n")

if __name__ == "__main__":
    main()
