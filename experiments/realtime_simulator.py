#!/usr/bin/env python3
"""
NEFT 实时调度离线验证沙盒 (Realtime Simulator)

专门用于测试实时调度策略的性能和稳定性。
特点：
- 从0任务开始，动态生成任务
- 测试启发式策略的实时响应能力
- 适用于事件驱动的调度场景

使用方法:
  python experiments/realtime_simulator.py --ticks 1000 --freq 5 --scale medium
"""

import sys
import os
import time
import argparse
import random
import logging

# 配置日志
log_file_path = os.path.join(os.path.dirname(__file__), "realtime_simulation_run.log")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file_path, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logging.getLogger("osmnx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.data.data_manager import DataManager
from backend.data.position import Position
from backend.data.task import Task
from backend.data.vehicle import Vehicle, VehicleStatus
from backend.data.charging_station import ChargingStation
from backend.decision.decision_manager import DecisionManager
from backend.algorithm.algorithm_manager import AlgorithmManager
from backend.config import config

SIM_SPEED_FACTOR: float = float(os.getenv("NEFT_SIM_SPEED", "60"))
DYNAMIC_SCHEDULE_INTERVAL_SEC: float = float(os.getenv("NEFT_DYNAMIC_SCHEDULE_INTERVAL_SEC", "1"))
global_task_weight_range = (10, 100)


def _initialize_realtime_mode(data_manager: DataManager, problem_scale="medium"):
    """实时模式初始化：只创建车辆和充电站，不预生成任务"""
    logging.info(f"Initializing realtime mode (scale={problem_scale})...")

    fleet_config = config.get_fleet_config()
    station_cfg = config.get_charging_station_config()
    task_config = config.get_task_config()

    global global_task_weight_range
    global_task_weight_range = (task_config["min_weight"], task_config["max_weight"])

    warehouse_pos = data_manager.sample_graph_position()
    data_manager.set_warehouse_position(warehouse_pos)

    # 混合车队初始化
    vehicle_id = 1
    type_counts = [
        ("small", fleet_config["small_count"]),
        ("medium", fleet_config["medium_count"]),
        ("large", fleet_config["large_count"]),
    ]
    for vtype, count in type_counts:
        vcfg = config.get_vehicle_config(vtype)
        for _ in range(count):
            vehicle = Vehicle(
                id=vehicle_id,
                position=Position(x=warehouse_pos.x, y=warehouse_pos.y),
                battery=vcfg["max_battery"],
                max_battery=vcfg["max_battery"],
                current_load=0.0,
                max_load=vcfg["max_load"],
                unit_energy_consumption=vcfg["unit_energy_consumption"],
                speed=vcfg["speed"],
                vehicle_type=vtype,
                charging_power=vcfg["charging_power"],
            )
            data_manager.add_vehicle(vehicle)
            vehicle_id += 1

    # 充电站初始化
    station_count = fleet_config["station_count"]
    station_positions = data_manager.sample_graph_positions_unique(station_count)
    for i, pos in enumerate(station_positions, start=1):
        station = ChargingStation(
            id=f"cs{i}",
            position=pos,
            capacity=station_cfg["default_capacity"],
            queue_count=0,
            charging_vehicles=[],
            load_pressure=0.0,
            charging_rate=0.022,
        )
        data_manager.add_charging_station(station)

    logging.info(f"[Realtime Mode] Fleet: {vehicle_id - 1} vehicles, "
                 f"Stations: {station_count}, Tasks: 0 (dynamic generation)")
    return warehouse_pos


def generate_random_task(data_manager: DataManager, task_id: int, max_retries: int = 10):
    """生成随机任务（带可达性检查）"""
    task_config = config.get_task_config()
    path_calculator = data_manager.path_calculator
    warehouse_pos = data_manager.warehouse_position

    pos = None
    for attempt in range(max_retries):
        candidate_pos = data_manager.sample_graph_position()
        try:
            path = path_calculator.find_shortest_path(
                (warehouse_pos.x, warehouse_pos.y),
                (candidate_pos.x, candidate_pos.y)
            )
            if path and len(path) > 0:
                pos = candidate_pos
                break
        except Exception:
            pass

    if pos is None:
        logging.warning(f"无法为任务 {task_id} 生成可达位置")
        return None

    weight = random.uniform(global_task_weight_range[0], global_task_weight_range[1])
    priority = random.randint(task_config["min_priority"], task_config["max_priority"])
    create_time = int(time.time())
    deadline = create_time + random.randint(
        task_config["min_deadline_offset"],
        task_config["max_deadline_offset"]
    )

    task = Task(
        id=task_id,
        position=Position(x=pos.x, y=pos.y),
        weight=weight,
        create_time=create_time,
        deadline=deadline,
        priority=priority
    )
    data_manager.add_task(task)
    return task


def main():
    parser = argparse.ArgumentParser(description="NEFT Realtime Scheduling Simulator")
    parser.add_argument("--ticks", type=int, default=1000, help="运行多少个仿真 Tick")
    parser.add_argument("--freq", type=int, default=5, help="每过多少个tick生成一次任务")
    parser.add_argument("--scale", type=str, default="medium", choices=["small", "medium", "large"],
                        help="车队规模: small=小, medium=中, large=大")
    args = parser.parse_args()

    logging.info("=" * 50)
    logging.info("NEFT 实时调度离线验证沙盒启动")
    logging.info(f"设定执行 Tick 总数: {args.ticks}")
    logging.info(f"任务生成频率: 每 {args.freq} ticks")
    logging.info(f"车队规模: {args.scale}")
    logging.info("=" * 50)

    # 1. 初始化核心模块
    logging.info("[1/3] 正在加载基础数据（OSM 路网下载 / 缓存检查）...")
    dm = DataManager()
    algorithm_mgr = AlgorithmManager(dm.path_calculator)
    decision_mgr = DecisionManager(dm, algorithm_mgr)
    logging.info("      - 路网与资源模块加载完成。")

    # 2. 初始化实时模式（不预生成任务）
    logging.info("[2/3] 正在生成充电站与车辆车队...")
    warehouse_pos = _initialize_realtime_mode(dm, args.scale)
    algorithm_mgr.warehouse_pos = (warehouse_pos.x, warehouse_pos.y)
    logging.info("      - 初始化成功")

    # 3. 开始执行高频 Tick 主循环
    logging.info("[3/3] 开始执行实时调度仿真循环...\n")

    start_time = time.time()
    task_id_counter = 100
    last_dynamic_scheduling_ts = 0.0
    strategy_stats = {}  # 统计策略使用频率

    for tick in range(1, args.ticks + 1):
        current_time = int(time.time())

        # A. 动态任务生成
        if tick % args.freq == 0:
            pending_count = len(dm.get_pending_tasks())
            if pending_count < 50:
                count = random.randint(1, 3)
                for _ in range(count):
                    task_id_counter += 1
                    task = generate_random_task(dm, task_id_counter)
                    if task:
                        logging.debug(f"Generated task {task.id}: "
                                      f"pos=({task.position.x:.2f}, {task.position.y:.2f})")

        # B. 推进车辆状态
        vehicles = dm.get_vehicles()
        for vehicle in vehicles:
            if vehicle.status == VehicleStatus.TRANSPORTING:
                dm.update_vehicle_position_by_speed(vehicle.id, time_delta=SIM_SPEED_FACTOR)
            elif vehicle.status == VehicleStatus.CHARGING:
                charge_rate = vehicle.charging_power if vehicle.charging_power > 0 else 0.022
                charge_delta = charge_rate * SIM_SPEED_FACTOR
                new_battery = min(vehicle.max_battery, vehicle.battery + charge_delta)
                dm.update_vehicle_battery(vehicle.id, new_battery)

                release_threshold_pct = decision_mgr.evaluate_charge_release_threshold(vehicle)
                should_release = False
                if release_threshold_pct <= 0.0:
                    should_release = True
                elif vehicle.get_battery_percentage() >= release_threshold_pct:
                    should_release = True

                if should_release and vehicle.charging_station_id:
                    dm.remove_vehicle_from_charging_station(vehicle.id, vehicle.charging_station_id)

            elif vehicle.status == VehicleStatus.IDLE:
                charge_cmd = decision_mgr.manage_battery(vehicle)
                if charge_cmd:
                    station_id = charge_cmd.get("charging_station_id")
                    if station_id:
                        dm.add_vehicle_to_charging_station(vehicle.id, station_id)

        decision_mgr._dynamic_scheduling.clear_completed_commands()

        # C. 执行实时调度
        now_wall = time.time()
        if (now_wall - last_dynamic_scheduling_ts) >= DYNAMIC_SCHEDULE_INTERVAL_SEC:
            pending_count = len(dm.get_pending_tasks())
            idle_count = len(dm.get_idle_vehicles())
            
            if pending_count > 0 and idle_count > 0:
                commands = decision_mgr.dynamic_scheduling(strategy="auto")
                strategy = decision_mgr.last_selected_strategy
                reason = decision_mgr.last_strategy_reason
                
                # 统计策略使用
                strategy_stats[strategy] = strategy_stats.get(strategy, 0) + 1
                
                logging.debug(f"[Tick {tick:04d}] Strategy: {strategy} ({reason}), "
                              f"Generated {len(commands)} commands")
            
            last_dynamic_scheduling_ts = now_wall

        # D. 周期性打印日志
        log_interval = max(1, args.ticks // 10)
        if tick % log_interval == 0 or tick == args.ticks:
            try:
                state = dm.get_system_state()
                idle_count = len([v for v in vehicles if v.status == VehicleStatus.IDLE])
                transport_count = len([v for v in vehicles if v.status == VehicleStatus.TRANSPORTING])
                charging_count = len([v for v in vehicles if v.status == VehicleStatus.CHARGING])

                logging.info(f"[Tick {tick:04d}] 完成率: {state.get('completion_rate', 0) * 100:.1f}%, "
                             f"总得分: {state.get('total_score', 0):.1f}, "
                             f"闲/送/充: {idle_count}/{transport_count}/{charging_count}")
            except Exception as e:
                logging.warning(f"[Tick {tick:04d}] 获取状态时出错: {e}")

    elapsed = time.time() - start_time
    logging.info("\n" + "=" * 50)
    logging.info("实时调度仿真完成！")
    logging.info(f"耗时: {elapsed:.2f} 秒")
    logging.info(f"共生成 {task_id_counter - 100} 个任务")
    logging.info(f"策略使用统计: {strategy_stats}")

    try:
        final_state = dm.get_system_state()
        logging.info(f"最终完成率: {final_state.get('completion_rate', 0) * 100:.1f}%")
        logging.info(f"最终总得分: {final_state.get('total_score', 0):.1f}")
    except Exception as e:
        logging.warning(f"获取最终状态时出错: {e}")

    logging.info("=" * 50)


if __name__ == "__main__":
    main()
