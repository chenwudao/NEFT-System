#!/usr/bin/env python
"""动态调度策略自定义实验运行脚本。

支持选择不同规模（small/medium/large）的 seed_1 种子，并选择相应的动态策略来运行实验。
支持命令行参数运行，也支持无参数交互式运行。
"""

import argparse
import subprocess
import sys
from pathlib import Path
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXE = sys.executable

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 定义知名调度算法的中文友好标签
STRATEGY_MAP = {
    "nearest_task": "最近任务优先 (Baseline)",
    "priority_task": "最高优先级优先",
    "heaviest_task": "最重任务优先",
    "deadline_earliest": "最早截止优先",
    "composite_score": "综合评分策略",
    "dfs_score_search": "DFS评分搜索",
    "insertion_heuristic": "插入启发式",
    "simulated_annealing": "模拟退火",
    "tabu_search": "禁忌搜索",
    "q_learning": "Q-Learning强化学习",
    "hyper_heuristic_eps": "超启发式(ε-贪心)",
    "relay_handoff": "接力换手协同",
    "region_partition": "区域划分协同",
    "multi_agent_auction": "多智能体拍卖",
    "multi_agent_contract_net": "合同网协议",
}

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
    # 在命令行交互式运行时，直接把子进程的输出重定向到终端，以便用户实时看到日志
    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Simulation failed with exit code {proc.returncode}")

def get_registered_strategies() -> list:
    """自动从动态调度算法注册表获取所有可用算法，并映射为 (value, label) 的形式。"""
    try:
        from backend.algorithm.schedulers.dynamic import DYNAMIC_SCHEDULERS
        names = []
        for cls in DYNAMIC_SCHEDULERS:
            name = str(getattr(cls, "name", "")).strip()
            if name:
                names.append(name)
    except Exception as e:
        print(f"[WARN] 无法自动加载动态调度器列表: {e}，将使用静态硬编码列表。")
        names = list(STRATEGY_MAP.keys())
    
    # 转换为 (name, label)
    strategies = []
    for name in names:
        label = STRATEGY_MAP.get(name, "未知自定义策略")
        strategies.append((name, label))
        
    # 确保 nearest_task 放在第一位作为默认/首选
    strategies.sort(key=lambda x: 0 if x[0] == "nearest_task" else 1)
    return strategies

def choose_scale() -> str:
    print("\n" + "=" * 50)
    print(" 请选择实验规模 (Select Scale)")
    print("=" * 50)
    print(" 1) small  (小规模: 3辆车, 1充电站, 30任务)")
    print(" 2) medium (中规模: 5辆车, 2充电站, 50任务)")
    print(" 3) large  (大规模: 8辆车, 3充电站, 100任务)")
    print("-" * 50)
    while True:
        choice = input("请输入序号 (1-3) 或规模名称: ").strip().lower()
        if choice in ("1", "small"):
            return "small"
        elif choice in ("2", "medium"):
            return "medium"
        elif choice in ("3", "large"):
            return "large"
        print("[错误] 输入无效，请输入 1、2、3 或对应规模名称。")

def choose_strategy(strategies: list) -> str:
    print("\n" + "=" * 50)
    print(" 请选择动态调度策略 (Select Strategy)")
    print("=" * 50)
    for idx, (name, label) in enumerate(strategies, 1):
        print(f" {idx:2d}) {name:<28} | {label}")
    print("-" * 50)
    while True:
        choice = input(f"请输入序号 (1-{len(strategies)}) 或策略标识: ").strip()
        if choice.isdigit():
            i = int(choice) - 1
            if 0 <= i < len(strategies):
                return strategies[i][0]
        else:
            # 检查是否直接输入了策略名称
            for name, _ in strategies:
                if name == choice:
                    return name
        print(f"[错误] 输入无效，请输入 1-{len(strategies)} 之间的数字或直接输入策略名称标识。")

def main():
    strategies = get_registered_strategies()
    strategy_choices = [name for name, _ in strategies]
    
    parser = argparse.ArgumentParser(description="以指定的规模(seed_1)和指定的动态调度策略运行实验")
    parser.add_argument(
        "-s", "--scale",
        choices=["small", "medium", "large"],
        help="实验规模 (small / medium / large)"
    )
    parser.add_argument(
        "-a", "--strategy", "--algo",
        choices=strategy_choices,
        help="动态调度策略名称"
    )
    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="强制进入交互式选择模式"
    )
    args = parser.parse_args()
    
    # 判定是否需要进入交互模式
    scale = args.scale
    strategy = args.strategy
    
    if args.interactive or not scale or not strategy:
        print("\n>>> 进入交互式选择模式 <<<")
        if not scale:
            scale = choose_scale()
        if not strategy:
            strategy = choose_strategy(strategies)
            
    # 确定种子路径
    seed_rel_path = f"log/benchmarks/dynamic/{scale}/seed_1/nearest_task/task_generation_seed.yaml"
    seed_path = PROJECT_ROOT / seed_rel_path
    
    if not seed_path.exists():
        print(f"\n[错误] 找不到对应的种子文件: {seed_rel_path}")
        print("请确认是否已经执行过基准运行（例如 nearest_task 算法在这个规模下的 seed_1 实验）。")
        sys.exit(1)
        
    print("\n" + "=" * 60)
    print(f" 开始执行自定义动态实验")
    print(f" - 规模: {scale}")
    print(f" - 策略: {strategy} ({dict(strategies).get(strategy, '未知')})")
    print(f" - 种子: {seed_rel_path}")
    print("=" * 60)
    
    # 1. 加载基础规模配置
    base_cfg_path = PROJECT_ROOT / "configs" / "dynamic" / f"{scale}.yaml"
    if not base_cfg_path.exists():
        base_cfg_path = PROJECT_ROOT / "configs" / f"{scale}.yaml"
        
    if not base_cfg_path.exists():
        print(f"[错误] 找不到基础配置文件: configs/dynamic/{scale}.yaml")
        sys.exit(1)
        
    base_cfg = read_yaml(base_cfg_path)
    
    # 2. 拷贝并修改配置
    cfg = yaml.safe_load(yaml.safe_dump(base_cfg))  # deep copy
    
    # 强制动态模式
    opt = cfg.setdefault("optimization", {})
    opt["mode"] = "dynamic"
    
    # 修改调度策略
    sched = cfg.setdefault("scheduling", {})
    sched["strategy"] = strategy
    
    # 修改实验及日志参数
    exp = cfg.setdefault("experiment", {})
    log_dir = PROJECT_ROOT / "log" / "benchmarks" / "dynamic_custom" / scale / "seed_1"
    exp["log_dir"] = str(log_dir.as_posix())
    exp["name"] = strategy
    
    # 绑定 replay 的种子文件
    task_cfg = cfg.setdefault("task", {})
    task_cfg["generation_seed_file"] = str(seed_path.as_posix())
    
    # 3. 保存生成的临时配置文件
    temp_cfg_path = PROJECT_ROOT / "benchmark_results" / "dynamic_custom" / "generated_configs" / f"{scale}_seed_1_{strategy}.yaml"
    write_yaml(temp_cfg_path, cfg)
    
    # 4. 运行仿真
    print(f"[运行] 启动仿真引擎中...")
    try:
        run_headless(temp_cfg_path)
        
        # 5. 解析并打印实验结果
        run_log_dir = log_dir / strategy
        metrics = parse_final_results_from_log(run_log_dir / "log.txt")
        
        scores = metrics.get("scores", {})
        tasks = metrics.get("tasks", {})
        timing = metrics.get("timing", {})
        
        total_score = scores.get("total", 0.0)
        completion_rate = tasks.get("completion_rate", 0.0) * 100
        completed = tasks.get("completed", 0)
        total_tasks = tasks.get("total", 0)
        on_time_rate = tasks.get("on_time_rate", 0.0) * 100
        avg_overdue = timing.get("avg_overdue_minutes", 0.0)
        
        print("\n" + "=" * 60)
        print(" 实验运行成功！结果汇总如下: ")
        print("=" * 60)
        print(f" - 运行算法/策略: {strategy}")
        print(f" - 综合评测总分: {total_score:.2f}")
        print(f" - 任务完成数量: {completed} / {total_tasks}")
        print(f" - 任务完成率  : {completion_rate:.2f}%")
        print(f" - 按时完成率  : {on_time_rate:.2f}%")
        print(f" - 平均逾期时间: {avg_overdue:.2f} 分钟")
        print(f" - 详细运行日志: {run_log_dir / 'log.txt'}")
        print("=" * 60 + "\n")
        
    except Exception as e:
        print(f"\n[失败] 实验运行出错: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
