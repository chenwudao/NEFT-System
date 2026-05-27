# Dynamic Benchmark Runner

这个脚本用于自动化动态实验对比：

- 默认规模：`medium / large`（可通过 `--scales` 自定义）
- 每个规模多个 seed 组（默认 3）
- 默认自动发现并运行**全部动态算法**（注册于 `DYNAMIC_SCHEDULERS`）
- 每个 seed 组：
  - 先用第一个算法跑一次并记录 `task_generation_seed.yaml`
  - 其余算法复用该 seed 回放，保证公平对比

## 运行方式

在项目根目录执行：

```powershell
python scripts/run_dynamic_benchmark.py
```

可选参数示例：

```powershell
python scripts/run_dynamic_benchmark.py --seeds 3 --scales small medium large --algorithms nearest_task composite_score tabu_search
```

不传 `--algorithms` 时，会自动跑全部动态算法。

## 输出结构

### 1) 生成配置（每次运行自动生成）

`benchmark_results/dynamic/generated_configs/<scale>/seed_<n>/<algorithm>.yaml`

### 2) 日志（按规模/种子/算法分层）

`log/benchmarks/dynamic/<scale>/seed_<n>/<algorithm>/`

每个算法目录内仍保持原有格式：

- `config.yaml`
- `log.txt`
- `task_generation_seed.yaml`

### 3) 汇总结果与可视化

`benchmark_results/dynamic/reports/`

- `results.csv`：每次实验的关键指标明细
- `<scale>_avg_total_score.png`：各算法平均总分
- `avg_completion_rate.png`：跨规模完成率对比
- `avg_timeout_rate.png`：跨规模超时率对比

