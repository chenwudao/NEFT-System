"""NEFT 系统后端入口。

相较旧版本，这里做了大幅简化：
    - 不再有 scale / static mode：所有数量、速度、阈值都在 backend/config.py 里硬指定。
    - 每次启动会创建一个实验目录 log/<name>_<ts>/，结束时写 results.json。
    - 主循环只管：推进运动、给充电中车辆充电、触发调度、必要时自动停止。
"""

import asyncio
import os
import random
import sys
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.algorithm.algorithm_manager import AlgorithmManager
from backend.config import config
from backend.data.charging_station import ChargingStation
from backend.data.data_manager import DataManager
from backend.data.position import Position
from backend.data.task import Task
from backend.data.vehicle import Vehicle, VehicleStatus
from backend.decision.decision_manager import DecisionManager
from backend.experiment_logger import experiment_logger
from backend.interface.api_controller import APIController
from backend.interface.websocket_handler import WebSocketHandler


# ============================================================
# 仿真级常量（从 config.py 一次性读出；运行时不再变）
# ============================================================
_sim_cfg = config.get_simulation_config()
SIM_SPEED_FACTOR: float = float(_sim_cfg.get("speed_factor", 120))
TICK_INTERVAL_SEC: float = float(_sim_cfg.get("tick_interval", 1.0))
MAX_SIM_SECONDS = _sim_cfg.get("max_sim_seconds")  # None = 无限

_sched_cfg = config.get_scheduling_config()
DEFAULT_STRATEGY: str = str(_sched_cfg.get("strategy", "nearest_task"))
CHARGE_UNTIL_PCT: float = float(_sched_cfg.get("charge_until_pct", 90.0))

DYNAMIC_SCHEDULE_INTERVAL_SEC: float = float(
    os.getenv("NEFT_DYNAMIC_SCHEDULE_INTERVAL_SEC", "1")
)


# ============================================================
# FastAPI 生命周期
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting NEFT System...")

    data_manager = DataManager()
    algorithm_manager = AlgorithmManager(data_manager.path_calculator)
    decision_manager = DecisionManager(data_manager, algorithm_manager)
    websocket_handler = WebSocketHandler(data_manager, decision_manager)
    api_controller = APIController(data_manager, decision_manager, websocket_handler)

    data_manager.register_task_update_callback(websocket_handler.broadcast_task_update)
    data_manager.register_vehicle_update_callback(websocket_handler.broadcast_vehicle_update)
    data_manager.register_station_update_callback(websocket_handler.broadcast_station_update)

    app.state.data_manager = data_manager
    app.state.decision_manager = decision_manager
    app.state.websocket_handler = websocket_handler
    app.state.api_controller = api_controller

    app.state.simulation_running = False
    app.state.sim_seconds_elapsed = 0.0
    app.state.last_dynamic_scheduling_ts = 0.0

    app.include_router(api_controller.get_router(), prefix="/api", tags=["API"])

    asyncio.create_task(background_tasks(app, data_manager, decision_manager, websocket_handler))
    asyncio.create_task(task_generator(app, data_manager))

    yield

    print("Shutting down NEFT System...")


app = FastAPI(
    title="New Energy Fleet Transportation System",
    description="新能源物流车队协同调度系统",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# REST API
# ============================================================
class SimulationStartRequest(BaseModel):
    """保留空 body 做兼容：前端不需要再传 mode/scale。"""
    pass


@app.post("/api/simulation/start")
async def start_simulation(_: SimulationStartRequest | None = None):
    """初始化车队 / 充电站 / 仓库 / 任务，开始仿真并创建实验日志目录。"""
    data_manager: DataManager = app.state.data_manager

    # 清空旧状态
    data_manager.tasks.clear()
    data_manager.vehicles.clear()
    data_manager.charging_stations.clear()

    _initialize_simulation(data_manager)

    app.state.simulation_running = True
    app.state.sim_seconds_elapsed = 0.0
    app.state.last_dynamic_scheduling_ts = 0.0

    # 建实验日志目录 + 写 config 快照
    experiment_logger.start_experiment(
        config.get_experiment_config(),
        config.snapshot(),
    )

    return {
        "success":       True,
        "running":       True,
        "strategy":      DEFAULT_STRATEGY,
        "tasks_count":   len(data_manager.get_tasks()),
        "vehicles_count": len(data_manager.get_vehicles()),
        "log_dir":       experiment_logger.run_dir,
        "max_sim_seconds": MAX_SIM_SECONDS,
    }


@app.post("/api/simulation/stop")
async def stop_simulation():
    """暂停仿真并落盘 results.json。"""
    was_running = getattr(app.state, "simulation_running", False)
    app.state.simulation_running = False
    if was_running:
        experiment_logger.finalize_experiment(
            app.state.data_manager,
            float(getattr(app.state, "sim_seconds_elapsed", 0.0)),
            stop_reason="manual_stop",
        )
    return {
        "success": True,
        "running": False,
        "log_dir": experiment_logger.run_dir,
    }


@app.post("/api/simulation/reset")
async def reset_simulation():
    """重置回初始（未启动）状态；若还在跑，顺手把 results 落盘。"""
    was_running = getattr(app.state, "simulation_running", False)
    app.state.simulation_running = False
    data_manager: DataManager = app.state.data_manager

    if was_running:
        experiment_logger.finalize_experiment(
            data_manager,
            float(getattr(app.state, "sim_seconds_elapsed", 0.0)),
            stop_reason="reset",
        )

    data_manager.tasks.clear()
    data_manager.vehicles.clear()
    data_manager.charging_stations.clear()

    dsm = app.state.decision_manager._dynamic_scheduling
    dsm.last_commands = []
    app.state.decision_manager.last_selected_strategy = DEFAULT_STRATEGY
    app.state.sim_seconds_elapsed = 0.0
    app.state.last_dynamic_scheduling_ts = 0.0

    return {
        "success": True,
        "running": False,
        "message": "Simulation reset.",
    }


@app.get("/api/simulation/status")
async def get_simulation_status():
    return {
        "running":             bool(getattr(app.state, "simulation_running", False)),
        "strategy":            DEFAULT_STRATEGY,
        "sim_seconds_elapsed": float(getattr(app.state, "sim_seconds_elapsed", 0.0)),
        "max_sim_seconds":     MAX_SIM_SECONDS,
        "log_dir":             experiment_logger.run_dir,
        # 渲染相关参数（前端读一次即可）
        "render": {
            "speed_factor":          SIM_SPEED_FACTOR,
            "tick_interval":         TICK_INTERVAL_SEC,
            "marker_tween_ms":       int(_sim_cfg.get("marker_tween_ms", 900)),
            "marker_tween_adaptive": bool(_sim_cfg.get("marker_tween_adaptive", True)),
        },
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    if not hasattr(app.state, "websocket_handler"):
        return
    await websocket.accept()
    await app.state.websocket_handler.connect(websocket)
    try:
        while True:
            message = await websocket.receive_json()
            await app.state.websocket_handler.handle_message(websocket, message)
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        app.state.websocket_handler.disconnect(websocket)


@app.get("/")
async def root():
    return {
        "message":   "NEFT System API",
        "version":   "1.0.0",
        "docs":      "/docs",
        "websocket": "/ws",
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.get("/api/graph")
async def get_road_graph():
    """导出后端正在使用的 NetworkX 路网（用于前端 2D Canvas 画"nx.draw 风格"底图）。

    返回:
        {
            "nodes": [[id, x, y], ...],       # x=lng, y=lat
            "edges": [[u_idx, v_idx], ...],   # 注意这里是 nodes 里的下标，不是原 id
            "bounds": {minLng, maxLng, minLat, maxLat},
        }
    只返回几何信息，不含 OSM 标签，payload 尽量精简。
    """
    pc = app.state.data_manager.path_calculator
    g = getattr(pc, "nx_graph", None)
    if g is None:
        return {"nodes": [], "edges": [], "bounds": None}

    # 一次性分配 id→下标，避免前端再去建哈希
    id_to_idx = {}
    nodes_out = []
    min_lng = float("inf"); max_lng = float("-inf")
    min_lat = float("inf"); max_lat = float("-inf")

    for node_id, attrs in g.nodes(data=True):
        x = attrs.get("x"); y = attrs.get("y")
        if x is None or y is None:
            continue
        x = float(x); y = float(y)
        id_to_idx[node_id] = len(nodes_out)
        nodes_out.append([node_id, x, y])
        if x < min_lng: min_lng = x
        if x > max_lng: max_lng = x
        if y < min_lat: min_lat = y
        if y > max_lat: max_lat = y

    edges_out = []
    for u, v in g.edges():
        iu = id_to_idx.get(u); iv = id_to_idx.get(v)
        if iu is None or iv is None:
            continue
        edges_out.append([iu, iv])

    bounds = None
    if nodes_out:
        bounds = {
            "minLng": min_lng, "maxLng": max_lng,
            "minLat": min_lat, "maxLat": max_lat,
        }

    return {"nodes": nodes_out, "edges": edges_out, "bounds": bounds}


# ============================================================
# 仿真初始化
# ============================================================
def _initialize_simulation(data_manager: DataManager) -> None:
    """按 config 里的 FLEET_CONFIG / TASK_CONFIG 建车、建充电站、播初始任务。

    仓库固定在路网中心节点；充电站分布在外围节点；车辆全部从仓库出发。
    """
    fleet_cfg = config.get_fleet_config()
    task_cfg = config.get_task_config()

    # 仓库
    warehouse_xy = data_manager.path_calculator.get_central_node_xy()
    warehouse_pos = Position(x=warehouse_xy[0], y=warehouse_xy[1])
    data_manager.set_warehouse_position(warehouse_pos)

    # 车队
    vehicle_id = 1
    fleet_plan = [
        ("small",  int(fleet_cfg.get("small_count", 0))),
        ("medium", int(fleet_cfg.get("medium_count", 0))),
        ("large",  int(fleet_cfg.get("large_count", 0))),
    ]
    for vtype, count in fleet_plan:
        vcfg = config.get_vehicle_config(vtype)
        for _ in range(count):
            data_manager.add_vehicle(Vehicle(
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
            ))
            vehicle_id += 1

    # 充电站
    station_count = int(fleet_cfg.get("station_count", 0))
    if station_count > 0:
        station_cfg = config.get_charging_station_config()
        station_positions = data_manager.path_calculator.get_peripheral_nodes_xy(station_count)
        for i, pos_xy in enumerate(station_positions, start=1):
            data_manager.add_charging_station(ChargingStation(
                id=f"cs{i}",
                position=Position(x=pos_xy[0], y=pos_xy[1]),
                capacity=station_cfg["default_capacity"],
                queue_count=0,
                charging_vehicles=[],
                load_pressure=0.0,
                charging_rate=0.022,
            ))

    # 初始任务
    initial_tasks = int(task_cfg.get("initial_tasks", 0))
    if initial_tasks > 0:
        _generate_initial_tasks(data_manager, initial_tasks)

    print(
        f"[Init] fleet={vehicle_id - 1} (small={fleet_plan[0][1]} medium={fleet_plan[1][1]} "
        f"large={fleet_plan[2][1]}), stations={station_count}, "
        f"initial_tasks={initial_tasks}, strategy={DEFAULT_STRATEGY}"
    )


def _generate_initial_tasks(data_manager: DataManager, n: int) -> int:
    """启动时一次性生成 n 个任务（尽力而为）。"""
    created = 0
    tid = 1
    max_attempts = n * 5
    attempts = 0
    while created < n and attempts < max_attempts:
        task = generate_random_task(data_manager, tid)
        attempts += 1
        if task is not None:
            created += 1
            tid += 1
    return created


# ============================================================
# 任务生成（运行过程中周期性生成）
# ============================================================
_task_id_counter = 1000  # 运行期生成的任务从 1000 开始，避开初始任务


def generate_random_task(data_manager: DataManager, task_id: int, max_retries: int = 50):
    """生成一个位置在路网连通分量中、可达仓库的随机任务。失败返回 None。"""
    task_cfg = config.get_task_config()
    path_calculator = data_manager.path_calculator
    warehouse_pos = data_manager.warehouse_position

    pos = None
    for _ in range(max_retries):
        candidate = data_manager.sample_graph_position()
        try:
            path = path_calculator.find_shortest_path(
                (warehouse_pos.x, warehouse_pos.y),
                (candidate.x, candidate.y),
            )
            if path and len(path) > 0:
                pos = candidate
                break
        except Exception:
            continue

    if pos is None:
        print(f"[Warning] 无法为任务 {task_id} 生成可达位置（已尝试 {max_retries} 次）")
        return None

    weight = random.uniform(task_cfg["min_weight"], task_cfg["max_weight"])
    priority = random.randint(task_cfg["min_priority"], task_cfg["max_priority"])
    create_time = int(time.time())
    deadline = create_time + random.randint(
        int(task_cfg["min_deadline_offset"]),
        int(task_cfg["max_deadline_offset"]),
    )
    task = Task(
        id=task_id,
        position=Position(x=pos.x, y=pos.y),
        weight=weight,
        create_time=create_time,
        deadline=deadline,
        priority=priority,
    )
    data_manager.add_task(task)
    return task


async def task_generator(app: FastAPI, data_manager: DataManager):
    """每隔一段时间生成一批新任务，直到 PENDING 达到上限。"""
    global _task_id_counter
    task_cfg = config.get_task_config()
    interval_min = int(task_cfg.get("generation_interval_sec_min", 10))
    interval_max = int(task_cfg.get("generation_interval_sec_max", 30))
    batch_min = int(task_cfg.get("generation_batch_min", 1))
    batch_max = int(task_cfg.get("generation_batch_max", 3))
    max_pending = int(task_cfg.get("max_pending_tasks", 20))

    while True:
        try:
            await asyncio.sleep(random.randint(interval_min, interval_max))

            if not getattr(app.state, "simulation_running", False):
                continue

            pending = len(data_manager.get_pending_tasks())
            if pending >= max_pending:
                continue

            batch = random.randint(batch_min, batch_max)
            created = 0
            for _ in range(batch):
                if pending + created >= max_pending:
                    break
                _task_id_counter += 1
                t = generate_random_task(data_manager, _task_id_counter)
                if t is not None:
                    created += 1
                    print(
                        f"[TaskGen] new task {t.id} weight={t.weight:.1f} prio={t.priority} "
                        f"pending={pending + created}/{max_pending}"
                    )
        except Exception as e:
            print(f"Task generator error: {e}")


# ============================================================
# 仿真主循环
# ============================================================
async def background_tasks(
    app: FastAPI,
    data_manager: DataManager,
    decision_manager: DecisionManager,
    websocket_handler: WebSocketHandler,
):
    """每 TICK_INTERVAL_SEC 现实秒推进仿真一步（= SIM_SPEED_FACTOR 仿真秒）。

    每 tick 执行：
        1. 推进 MOVING 车辆 / 给 CHARGING 车辆充电
        2. 累加 sim_seconds_elapsed，到达 MAX_SIM_SECONDS 自动停
        3. 广播状态
        4. 按节流触发调度器
    """
    while True:
        try:
            await asyncio.sleep(TICK_INTERVAL_SEC)

            running = getattr(app.state, "simulation_running", False)
            if not running:
                await websocket_handler.broadcast_system_status()
                await websocket_handler.broadcast_state()
                continue

            sim_dt = SIM_SPEED_FACTOR * TICK_INTERVAL_SEC

            # 新 tick 开始：先把所有车的 tick_path 清空，确保"没动的车"
            # 不会把上一轮走过的折线留给前端。随后只有在 advance_vehicle 里才填新数据。
            for vehicle in data_manager.get_vehicles():
                vehicle.tick_path = []

            for vehicle in data_manager.get_vehicles():
                if vehicle.is_moving():
                    data_manager.advance_vehicle(vehicle.id, time_delta=sim_dt)

                elif vehicle.status == VehicleStatus.CHARGING:
                    rate = vehicle.charging_power if vehicle.charging_power > 0 else 0.022
                    new_battery = min(vehicle.max_battery, vehicle.battery + rate * sim_dt)
                    data_manager.update_vehicle_battery(vehicle.id, new_battery)

                    if (
                        vehicle.get_battery_percentage() >= CHARGE_UNTIL_PCT
                        and vehicle.charging_station_id
                    ):
                        data_manager.remove_vehicle_from_charging_station(
                            vehicle.id, vehicle.charging_station_id
                        )

            # 仿真时间推进 + 到时自动停
            app.state.sim_seconds_elapsed = float(
                getattr(app.state, "sim_seconds_elapsed", 0.0)
            ) + sim_dt
            if (
                MAX_SIM_SECONDS is not None
                and app.state.sim_seconds_elapsed >= float(MAX_SIM_SECONDS)
            ):
                print(
                    f"[Sim] Reached max_sim_seconds={MAX_SIM_SECONDS}, "
                    f"auto-stopping simulation."
                )
                app.state.simulation_running = False
                experiment_logger.finalize_experiment(
                    data_manager,
                    float(app.state.sim_seconds_elapsed),
                    stop_reason="max_sim_seconds_reached",
                )

            await websocket_handler.broadcast_system_status()
            await websocket_handler.broadcast_performance_metrics()
            await websocket_handler.broadcast_state()

            # 动态调度节流
            now_wall = time.time()
            last_dyn = float(getattr(app.state, "last_dynamic_scheduling_ts", 0.0))
            if (now_wall - last_dyn) >= DYNAMIC_SCHEDULE_INTERVAL_SEC:
                try:
                    commands = decision_manager.dynamic_scheduling()
                    if commands:
                        print(
                            f"[Sched] strategy={decision_manager.last_selected_strategy} "
                            f"produced {len(commands)} commands"
                        )
                except Exception as sched_e:
                    print(f"[ERROR] Scheduling failed: {sched_e}")
                    import traceback
                    traceback.print_exc()
                app.state.last_dynamic_scheduling_ts = now_wall

        except Exception as e:
            print(f"Background task error: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
