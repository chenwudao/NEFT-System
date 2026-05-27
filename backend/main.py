"""NEFT 系统后端入口。

要点：
    - 配置入口在 backend/config.py + configs/*.yaml；可通过命令行
      `python backend/main.py --cfg configs/small.yaml` 选择 yaml。
    - 每次启动会创建一个实验目录 log/<experiment.name>/，内含 config.yaml 与 log.txt。
    - 主循环：推进运动、充电、触发调度；达到时间上限 / 任务全部结算时自动停。
"""

import asyncio
import os
import random
import sys
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _apply_cli_config_arg() -> None:
    """在导入 backend.config 前处理 --cfg/--config。

    config.py 在 import 时读取 NEFT_CONFIG_FILE，因此 CLI 参数必须尽早写入
    环境变量。保留参数在 sys.argv 中也没问题：uvicorn 不会消费它。
    """
    for flag in ("--cfg", "--config"):
        if flag in sys.argv:
            idx = sys.argv.index(flag)
            if idx + 1 >= len(sys.argv):
                raise SystemExit(f"{flag} requires a yaml config path")
            os.environ["NEFT_CONFIG_FILE"] = sys.argv[idx + 1]
            # 避免未来有库解析 argv 时看到未知参数。
            del sys.argv[idx:idx + 2]
            return


_apply_cli_config_arg()

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

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ============================================================
# 仿真级常量（从 config.py 一次性读出；运行时不再变）
# ============================================================
_sim_cfg = config.get_simulation_config()
SIM_SPEED_FACTOR: float = float(_sim_cfg.get("speed_factor", 120))
TICK_INTERVAL_SEC: float = float(_sim_cfg.get("tick_interval", 1.0))
MAX_SIM_SECONDS = _sim_cfg.get("max_sim_seconds")  # None = 无限
STOP_WHEN_ALL_TASKS_DONE: bool = bool(_sim_cfg.get("stop_when_all_tasks_done", True))

_sched_cfg = config.get_scheduling_config()
DEFAULT_STRATEGY: str = str(_sched_cfg.get("strategy", "nearest_task"))
CHARGE_UNTIL_PCT: float = float(_sched_cfg.get("charge_until_pct", 90.0))
_opt_cfg = config.get_optimization_config()
OPT_MODE: str = str(_opt_cfg.get("mode", "dynamic")).strip().lower()

_task_cfg = config.get_task_config()
TOTAL_TASK_BUDGET = _task_cfg.get("total_task_budget")  # None = 不限

DYNAMIC_SCHEDULE_INTERVAL_SEC: float = float(
    os.getenv("NEFT_DYNAMIC_SCHEDULE_INTERVAL_SEC", "1")
)
# 连续多少次调度“无法继续派单”后，判定为不可完成并自动结束
MAX_STUCK_SCHED_CYCLES: int = int(os.getenv("NEFT_MAX_STUCK_SCHED_CYCLES", "5"))


def _is_static_mode() -> bool:
    return OPT_MODE == "static"


def _configured_strategy_name() -> str:
    if _is_static_mode():
        static_cfg = _opt_cfg.get("static") or {}
        return str(static_cfg.get("strategy", "static_exact_solver"))
    return DEFAULT_STRATEGY


def _resolve_project_path(path: Optional[str]) -> Optional[str]:
    """把相对路径解析为项目根目录下的绝对路径。"""
    if not path:
        return None
    if os.path.isabs(path):
        return path
    return os.path.join(_PROJECT_ROOT, path)


class TaskSeedController:
    """任务生成种子流控制器：record / replay 两种模式。"""

    def __init__(self, mode: str, source_path: Optional[str], base_seed: int):
        self.mode = mode  # "record" | "replay"
        self.source_path = source_path
        self.base_seed = int(base_seed)
        self.rng = random.Random(self.base_seed)
        self.events: List[Dict[str, Any]] = []
        self._replay_idx = 0

    @property
    def is_replay(self) -> bool:
        return self.mode == "replay"

    def record_event(self, event: Dict[str, Any]) -> None:
        if self.mode != "record":
            return
        self.events.append(dict(event))

    def load_replay_events(self, events: List[Dict[str, Any]]) -> None:
        self.events = sorted(
            [dict(e) for e in (events or [])],
            key=lambda e: (float(e.get("sim_seconds", 0.0)), int(e.get("task_id", 0))),
        )
        self._replay_idx = 0

    def pop_due_events(
        self,
        sim_seconds: float,
        *,
        phase: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """取出 replay 中到点可注入的任务事件。"""
        if self.mode != "replay":
            return []
        out: List[Dict[str, Any]] = []
        while self._replay_idx < len(self.events):
            ev = self.events[self._replay_idx]
            ev_sim = float(ev.get("sim_seconds", 0.0))
            if ev_sim > sim_seconds + 1e-9:
                break
            if phase is not None and str(ev.get("phase", "")) != phase:
                break
            out.append(ev)
            self._replay_idx += 1
        return out

    def replay_exhausted(self) -> bool:
        return self.mode == "replay" and self._replay_idx >= len(self.events)

    def to_payload(self, *, note: str = "") -> Dict[str, Any]:
        return {
            "version": 1,
            "mode": self.mode,
            "source_path": self.source_path,
            "base_seed": self.base_seed,
            "event_count": len(self.events),
            "note": note,
            "events": self.events,
        }


def _build_task_seed_controller() -> TaskSeedController:
    """根据 task.generation_seed_file 初始化种子控制器。"""
    task_cfg = config.get_task_config()
    src = _resolve_project_path(task_cfg.get("generation_seed_file"))
    if src and os.path.exists(src):
        try:
            import yaml as _yaml  # type: ignore

            with open(src, "r", encoding="utf-8") as f:
                payload = _yaml.safe_load(f) or {}
            base_seed = int(payload.get("base_seed", random.SystemRandom().randint(1, 2**31 - 1)))
            ctrl = TaskSeedController(mode="replay", source_path=src, base_seed=base_seed)
            ctrl.load_replay_events(payload.get("events") or [])
            return ctrl
        except Exception as exc:
            print(f"[Seed] WARN: failed to read seed file '{src}', fallback to record mode: {exc}")
    # 没配种子文件或读取失败：随机新种子并记录
    seed = random.SystemRandom().randint(1, 2**31 - 1)
    return TaskSeedController(mode="record", source_path=src, base_seed=seed)


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
    app.state.task_id_counter = 0
    app.state.last_progress_log_sim = 0.0
    app.state.no_assign_sched_streak = 0
    # 后台协程会先于“开始仿真”运行，这里先给一个兜底对象，避免属性不存在报错。
    app.state.task_seed_controller = None
    app.state.task_generation_seed_artifact = None
    app.state.seed_note = ""
    app.state.static_release_notified_ids = set()

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
    global _task_id_counter, _runtime_tasks_generated
    data_manager: DataManager = app.state.data_manager

    # 清空旧状态
    data_manager.tasks.clear()
    data_manager.vehicles.clear()
    data_manager.charging_stations.clear()
    _task_id_counter = 1000
    _runtime_tasks_generated = 0

    app.state.task_seed_controller = _build_task_seed_controller()
    app.state.task_generation_seed_artifact = None
    app.state.seed_note = ""
    app.state.static_release_notified_ids = set()
    _initialize_simulation(app, data_manager)

    app.state.sim_seconds_elapsed = 0.0
    app.state.last_dynamic_scheduling_ts = 0.0
    app.state.last_progress_log_sim = 0.0
    app.state._gen_stop_logged = False
    app.state.no_assign_sched_streak = 0

    experiment_logger.start_experiment(
        config.get_experiment_config(),
        config.snapshot(),
    )
    seed_ctrl: TaskSeedController = app.state.task_seed_controller
    seed_payload = seed_ctrl.to_payload(
        note="replay from seed file" if seed_ctrl.is_replay else "recorded in this run"
    )
    artifact_path = experiment_logger.write_yaml_artifact(
        "task_generation_seed.yaml",
        seed_payload,
    )
    app.state.task_generation_seed_artifact = artifact_path
    if seed_ctrl.is_replay:
        app.state.seed_note = f"replay={seed_ctrl.source_path}"
    else:
        app.state.seed_note = f"record(base_seed={seed_ctrl.base_seed})"

    # 静态模式：先完成一次全局规划，再进入可视化执行阶段。
    if _is_static_mode():
        try:
            pre_cmds = app.state.decision_manager.dynamic_scheduling()
            experiment_logger.log(
                f"[STATIC_PREPLAN] precomputed commands={len(pre_cmds)} before visualization start."
            )
        except Exception as exc:
            print(f"[WARN] static preplan failed before start: {exc}")

    app.state.simulation_running = True

    experiment_logger.log(
        f"mode={OPT_MODE}, strategy={_configured_strategy_name()}, "
        f"fleet_size={len(data_manager.get_vehicles())}, "
        f"stations={len(data_manager.get_charging_stations())}, "
        f"initial_tasks={len(data_manager.get_tasks())}, "
        f"task_budget={TOTAL_TASK_BUDGET}, max_sim_seconds={MAX_SIM_SECONDS}, "
        f"task_seed={app.state.seed_note}, seed_file={artifact_path or '(none)'}"
    )

    return {
        "success":       True,
        "running":       True,
        "strategy":      _configured_strategy_name(),
        "optimization_mode": OPT_MODE,
        "tasks_count":   len(data_manager.get_tasks()),
        "vehicles_count": len(data_manager.get_vehicles()),
        "log_dir":       experiment_logger.run_dir,
        "max_sim_seconds": MAX_SIM_SECONDS,
        "task_seed_mode": "replay" if seed_ctrl.is_replay else "record",
        "task_seed_file": artifact_path,
    }


@app.post("/api/simulation/stop")
async def stop_simulation():
    """暂停仿真并落盘 results.json。"""
    was_running = getattr(app.state, "simulation_running", False)
    app.state.simulation_running = False
    if was_running:
        _flush_task_seed_artifact(app)
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
        _flush_task_seed_artifact(app)
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
    app.state.decision_manager.last_selected_strategy = _configured_strategy_name()
    app.state.sim_seconds_elapsed = 0.0
    app.state.last_dynamic_scheduling_ts = 0.0
    app.state.last_progress_log_sim = 0.0
    app.state._gen_stop_logged = False
    app.state.no_assign_sched_streak = 0

    return {
        "success": True,
        "running": False,
        "message": "Simulation reset.",
    }


@app.get("/api/simulation/status")
async def get_simulation_status():
    return {
        "running":             bool(getattr(app.state, "simulation_running", False)),
        "strategy":            _configured_strategy_name(),
        "optimization_mode":   OPT_MODE,
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
def _initialize_simulation(app: FastAPI, data_manager: DataManager) -> None:
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

    # 任务初始化
    initial_tasks = int(task_cfg.get("initial_tasks", 0))
    if _is_static_mode():
        static_created = _generate_static_known_tasks(app, data_manager)
        print(f"[Init-Static] preloaded known tasks={static_created}")
    elif initial_tasks > 0:
        _generate_initial_tasks(app, data_manager, initial_tasks)

    print(
        f"[Init] fleet={vehicle_id - 1} (small={fleet_plan[0][1]} medium={fleet_plan[1][1]} "
        f"large={fleet_plan[2][1]}), stations={station_count}, "
        f"initial_tasks={initial_tasks}, strategy={_configured_strategy_name()}, mode={OPT_MODE}"
    )


def _create_task(
    data_manager: DataManager,
    task_id: int,
    pos: Position,
    weight: float,
    priority: int,
    create_time: int,
    deadline_offset: int,
    notify: bool = True,
) -> Task:
    deadline = int(create_time + int(deadline_offset))
    task = Task(
        id=task_id,
        position=Position(x=pos.x, y=pos.y),
        weight=float(weight),
        create_time=int(create_time),
        deadline=deadline,
        priority=int(priority),
    )
    data_manager.add_task(task, notify=notify)
    return task


def _generate_static_known_tasks(app: FastAPI, data_manager: DataManager) -> int:
    """静态模式：一次性构建任务全集（上帝视角）。"""
    global _task_id_counter, _runtime_tasks_generated
    task_cfg = config.get_task_config()
    seed_ctrl: TaskSeedController = app.state.task_seed_controller
    created = 0

    static_start_wall = int(time.time())

    def _create_from_event(ev: Dict[str, Any]) -> Optional[Task]:
        pos_raw = ev.get("position") or {}
        pos = Position(
            x=float(pos_raw.get("x", 0.0)),
            y=float(pos_raw.get("y", 0.0)),
        )
        ev_sim = float(ev.get("sim_seconds", 0.0))
        # 把“仿真秒时间线”映射为“墙钟释放时间”，保证未来任务不会被提前执行。
        wall_release = static_start_wall + int(max(0.0, ev_sim) / max(1e-6, float(SIM_SPEED_FACTOR)))
        t = _create_task(
            data_manager=data_manager,
            task_id=int(ev.get("task_id")),
            pos=pos,
            weight=float(ev.get("weight", 10.0)),
            priority=int(ev.get("priority", 1)),
            create_time=wall_release,
            deadline_offset=int(ev.get("deadline_offset", 1800)),
            notify=(wall_release <= static_start_wall),
        )
        return t

    if seed_ctrl.is_replay:
        events = sorted(
            list(seed_ctrl.events),
            key=lambda e: (float(e.get("sim_seconds", 0.0)), int(e.get("task_id", 0))),
        )
        for ev in events:
            t = _create_from_event(ev)
            if t is None:
                continue
            created += 1
            _runtime_tasks_generated += 1
            _task_id_counter = max(_task_id_counter, int(t.id))
            seed_ctrl._replay_idx = min(len(seed_ctrl.events), seed_ctrl._replay_idx + 1)
        return created

    # record 模式：构造整段已知任务流（不再运行期追加）
    initial_tasks = int(task_cfg.get("initial_tasks", 0))
    budget = task_cfg.get("total_task_budget")
    total = int(budget) if budget is not None else initial_tasks
    total = max(total, initial_tasks)

    interval_min = int(task_cfg.get("generation_interval_sec_min", 10))
    interval_max = int(task_cfg.get("generation_interval_sec_max", 30))
    cur_sim = 0.0
    tid = 1
    for i in range(total):
        phase = "initial" if i < initial_tasks else "runtime"
        if phase == "runtime":
            cur_sim += float(seed_ctrl.rng.randint(interval_min, interval_max))
        # 先按动态规则抽样参数并记录事件，再按静态时间线预创建任务（带未来 release 时间）。
        t = generate_random_task(
            app,
            data_manager,
            task_id=tid,
            sim_seconds=cur_sim,
            phase=phase,
            notify=(phase == "initial"),
        )
        if t is None:
            continue
        # 覆盖 create_time 到静态时间线释放时刻（且同步 deadline）
        wall_release = static_start_wall + int(max(0.0, cur_sim) / max(1e-6, float(SIM_SPEED_FACTOR)))
        old_create = int(getattr(t, "create_time", wall_release))
        old_deadline = int(getattr(t, "deadline", wall_release + 1800))
        deadline_offset = max(0, old_deadline - old_create)
        t.create_time = wall_release
        t.deadline = wall_release + deadline_offset
        created += 1
        _runtime_tasks_generated += 1
        _task_id_counter = max(_task_id_counter, int(t.id))
        tid += 1
    return created


def _generate_initial_tasks(app: FastAPI, data_manager: DataManager, n: int) -> int:
    """启动时一次性生成 n 个任务（尽力而为）。"""
    global _task_id_counter, _runtime_tasks_generated
    seed_ctrl: TaskSeedController = app.state.task_seed_controller
    created = 0
    if seed_ctrl.is_replay:
        replay_events = seed_ctrl.pop_due_events(0.0, phase="initial")
        replay_events.sort(key=lambda e: int(e.get("task_id", 0)))
        for ev in replay_events[:n]:
            pos_raw = ev.get("position") or {}
            pos = Position(x=float(pos_raw.get("x", 0.0)), y=float(pos_raw.get("y", 0.0)))
            create_time = int(time.time())
            t = _create_task(
                data_manager=data_manager,
                task_id=int(ev.get("task_id")),
                pos=pos,
                weight=float(ev.get("weight", 10.0)),
                priority=int(ev.get("priority", 1)),
                create_time=create_time,
                deadline_offset=int(ev.get("deadline_offset", 1800)),
            )
            created += 1
            _runtime_tasks_generated += 1
            _task_id_counter = max(_task_id_counter, int(t.id))
        return created

    tid = 1
    max_attempts = n * 5
    attempts = 0
    while created < n and attempts < max_attempts:
        task = generate_random_task(app, data_manager, tid, sim_seconds=0.0, phase="initial")
        attempts += 1
        if task is not None:
            created += 1
            _runtime_tasks_generated += 1
            _task_id_counter = max(_task_id_counter, int(task.id))
            tid += 1
    return created


# ============================================================
# 任务生成（运行过程中周期性生成）
# ============================================================
_task_id_counter = 1000  # 运行期生成的任务从 1000 开始，避开初始任务
_runtime_tasks_generated = 0  # 主循环内累计生成的任务数（含初始）


def generate_random_task(
    app: FastAPI,
    data_manager: DataManager,
    task_id: int,
    sim_seconds: float,
    phase: str = "runtime",
    max_retries: int = 50,
    notify: bool = True,
):
    """生成一个位置在路网连通分量中、可达仓库的随机任务。失败返回 None。"""
    task_cfg = config.get_task_config()
    path_calculator = data_manager.path_calculator
    warehouse_pos = data_manager.warehouse_position

    seed_ctrl: TaskSeedController = app.state.task_seed_controller
    rng = seed_ctrl.rng
    pos = None
    for _ in range(max_retries):
        candidate = data_manager.sample_graph_position(rng=rng)
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

    weight = rng.uniform(task_cfg["min_weight"], task_cfg["max_weight"])
    priority = rng.randint(task_cfg["min_priority"], task_cfg["max_priority"])
    create_time = int(time.time())
    deadline_offset = rng.randint(
        int(task_cfg["min_deadline_offset"]),
        int(task_cfg["max_deadline_offset"]),
    )
    task = _create_task(
        data_manager=data_manager,
        task_id=task_id,
        pos=Position(x=pos.x, y=pos.y),
        weight=weight,
        priority=priority,
        create_time=create_time,
        deadline_offset=deadline_offset,
        notify=notify,
    )
    seed_ctrl.record_event(
        {
            "task_id": int(task_id),
            "phase": str(phase),
            "sim_seconds": float(sim_seconds),
            "position": {"x": float(pos.x), "y": float(pos.y)},
            "weight": float(weight),
            "priority": int(priority),
            "deadline_offset": int(deadline_offset),
        }
    )
    return task


async def task_generator(app: FastAPI, data_manager: DataManager):
    """每隔一段时间生成一批新任务。

    生成停止条件（取或，由 `_task_generation_stopped` 判断）：
      1) 累计任务数 >= total_task_budget
      2) 仿真时间已达 max_sim_seconds（"任务生成截止时间"语义）

    达到上述任一条件后停止生成，但仿真主循环继续，直到所有现存任务结算完。
    """
    global _task_id_counter, _runtime_tasks_generated
    task_cfg = config.get_task_config()
    interval_min = int(task_cfg.get("generation_interval_sec_min", 10))
    interval_max = int(task_cfg.get("generation_interval_sec_max", 30))
    batch_min = int(task_cfg.get("generation_batch_min", 1))
    batch_max = int(task_cfg.get("generation_batch_max", 3))
    max_pending = int(task_cfg.get("max_pending_tasks", 20))

    while True:
        try:
            if _is_static_mode():
                await asyncio.sleep(max(0.5, TICK_INTERVAL_SEC))
                continue

            if not getattr(app.state, "simulation_running", False):
                await asyncio.sleep(max(0.5, TICK_INTERVAL_SEC))
                continue

            seed_ctrl = getattr(app.state, "task_seed_controller", None)
            if not isinstance(seed_ctrl, TaskSeedController):
                seed_ctrl = _build_task_seed_controller()
                app.state.task_seed_controller = seed_ctrl

            if seed_ctrl.is_replay:
                await asyncio.sleep(max(0.2, TICK_INTERVAL_SEC))
            else:
                await asyncio.sleep(seed_ctrl.rng.randint(interval_min, interval_max))

            if seed_ctrl.is_replay:
                sim_s = float(getattr(app.state, "sim_seconds_elapsed", 0.0))
                due = seed_ctrl.pop_due_events(sim_s)
                if not due:
                    continue
                for ev in due:
                    if str(ev.get("phase", "")) == "initial":
                        continue
                    pos_raw = ev.get("position") or {}
                    pos = Position(
                        x=float(pos_raw.get("x", 0.0)),
                        y=float(pos_raw.get("y", 0.0)),
                    )
                    create_time = int(time.time())
                    t = _create_task(
                        data_manager=data_manager,
                        task_id=int(ev.get("task_id")),
                        pos=pos,
                        weight=float(ev.get("weight", 10.0)),
                        priority=int(ev.get("priority", 1)),
                        create_time=create_time,
                        deadline_offset=int(ev.get("deadline_offset", 1800)),
                    )
                    _runtime_tasks_generated += 1
                    _task_id_counter = max(_task_id_counter, int(t.id))
                    pending_now = len(data_manager.get_pending_tasks())
                    print(
                        f"[TaskGen-Replay] task {t.id} weight={t.weight:.1f} prio={t.priority} "
                        f"pending={pending_now}/{max_pending}"
                    )
                    experiment_logger.log(
                        f"replay task t{t.id} weight={t.weight:.1f} prio={t.priority} "
                        f"deadline={t.deadline} pending={pending_now}/{max_pending}",
                        level="TASK",
                    )
                continue

            # record 模式下沿用旧逻辑
            if _task_generation_stopped(app, data_manager):
                continue

            pending = len(data_manager.get_pending_tasks())
            if pending >= max_pending:
                continue

            batch = seed_ctrl.rng.randint(batch_min, batch_max)
            created = 0
            for _ in range(batch):
                if pending + created >= max_pending:
                    break
                if _task_generation_stopped(app, data_manager):
                    break
                _task_id_counter += 1
                t = generate_random_task(
                    app,
                    data_manager,
                    _task_id_counter,
                    sim_seconds=float(getattr(app.state, "sim_seconds_elapsed", 0.0)),
                    phase="runtime",
                )
                if t is not None:
                    created += 1
                    _runtime_tasks_generated += 1
                    print(
                        f"[TaskGen] new task {t.id} weight={t.weight:.1f} prio={t.priority} "
                        f"pending={pending + created}/{max_pending}"
                    )
                    experiment_logger.log(
                        f"new task t{t.id} weight={t.weight:.1f} prio={t.priority} "
                        f"deadline={t.deadline} pending={pending + created}/{max_pending}",
                        level="TASK"
                    )
        except Exception as e:
            print(f"Task generator error: {e}")


# ============================================================
# 终止条件 / 周期性日志
# ============================================================
def _task_generation_stopped(app: FastAPI, data_manager: DataManager) -> bool:
    """任务生成是否已经截止（不会再有新任务进来）。

    两个停止条件取或：
      1) 已生成任务数 >= total_task_budget
      2) 仿真时间已达 max_sim_seconds（这里把 max_sim_seconds 解释为
         '任务生成截止时间'，到达后不再生成新任务，但仿真继续直到所有
          已有任务结算完毕）
    若两者都没设，则任务生成永不截止——只能手动 stop。
    """
    if _is_static_mode():
        return True
    seed_ctrl = getattr(app.state, "task_seed_controller", None)
    if isinstance(seed_ctrl, TaskSeedController) and seed_ctrl.is_replay:
        return seed_ctrl.replay_exhausted()
    if TOTAL_TASK_BUDGET is not None:
        if len(data_manager.get_tasks()) >= int(TOTAL_TASK_BUDGET):
            return True
    if MAX_SIM_SECONDS is not None:
        if float(getattr(app.state, "sim_seconds_elapsed", 0.0)) >= float(MAX_SIM_SECONDS):
            return True
    return False


def _all_tasks_settled(app: FastAPI, data_manager: DataManager) -> bool:
    """是否可以结束仿真：任务生成已停止 + 所有任务都到了终态。"""
    from backend.data.task import TaskStatus

    if not _task_generation_stopped(app, data_manager):
        return False
    tasks = data_manager.get_tasks()
    if not tasks:
        return False
    for t in tasks:
        if t.status not in (TaskStatus.COMPLETED, TaskStatus.TIMEOUT):
            return False
    return True


def _all_vehicles_at_warehouse_and_idle(data_manager: DataManager, eps: float = 1e-4) -> bool:
    """所有车辆都在仓库且 IDLE。"""
    vehicles = data_manager.get_vehicles()
    if not vehicles:
        return False
    wh = data_manager.get_warehouse_position()
    for v in vehicles:
        if v.status != VehicleStatus.IDLE:
            return False
        if abs(v.position.x - wh.x) > eps or abs(v.position.y - wh.y) > eps:
            return False
    return True


def _mark_unfinished_tasks_zero(data_manager: DataManager) -> int:
    """把未完成任务结算为 TIMEOUT，分数置 0。返回处理数量。"""
    from backend.data.task import TaskStatus

    changed = 0
    with data_manager.lock:
        for task in data_manager.tasks.values():
            if task.status in (TaskStatus.COMPLETED, TaskStatus.TIMEOUT):
                continue
            task.update_status(TaskStatus.TIMEOUT)
            task.score = 0.0
            changed += 1
            data_manager._notify_task_update(task)
    return changed


def _log_progress(
    data_manager: DataManager,
    decision_manager: DecisionManager,
    sim_seconds_elapsed: float,
) -> None:
    """落一行进度日志到 log.txt（每 ~300 仿真秒一次）。"""
    try:
        status = decision_manager.get_system_status()
        experiment_logger.log(
            f"sim_elapsed={sim_seconds_elapsed:.0f}s "
            f"strategy={status.get('current_strategy')} "
            f"tasks total={status.get('total_tasks')} "
            f"completed={status.get('completed_tasks')} "
            f"pending={status.get('pending_tasks')} "
            f"in_progress={status.get('in_progress_tasks')} "
            f"timeout={status.get('timeout_tasks')} "
            f"vehicles idle={status.get('idle_vehicles')} "
            f"moving={status.get('moving_vehicles')} "
            f"charging={status.get('charging_vehicles')}",
            level="PROGRESS",
        )
    except Exception as exc:
        print(f"[ERROR] _log_progress: {exc}")


def _flush_task_seed_artifact(app: FastAPI) -> Optional[str]:
    """把当前任务生成种子流写回实验目录。"""
    seed_ctrl = getattr(app.state, "task_seed_controller", None)
    if not isinstance(seed_ctrl, TaskSeedController):
        return None
    payload = seed_ctrl.to_payload(
        note="replay source" if seed_ctrl.is_replay else "recorded during this run"
    )
    path = experiment_logger.write_yaml_artifact("task_generation_seed.yaml", payload)
    if path:
        app.state.task_generation_seed_artifact = path
    return path


def _notify_released_static_tasks(app: FastAPI, data_manager: DataManager) -> None:
    """静态模式：任务到释放时刻时再触发一次 task_update，供前端显示。"""
    if not _is_static_mode():
        return
    notified = getattr(app.state, "static_release_notified_ids", None)
    if not isinstance(notified, set):
        notified = set()
        app.state.static_release_notified_ids = notified
    now_ts = int(time.time())
    for t in data_manager.get_tasks():
        if int(getattr(t, "create_time", 0)) > now_ts:
            continue
        if int(t.id) in notified:
            continue
        data_manager._notify_task_update(t)
        notified.add(int(t.id))


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
            _notify_released_static_tasks(app, data_manager)

            # 周期性 progress 日志：每 ~300 仿真秒落一行到 log.txt
            last_prog = float(getattr(app.state, "last_progress_log_sim", 0.0))
            if app.state.sim_seconds_elapsed - last_prog >= 300.0:
                _log_progress(data_manager, decision_manager,
                              float(app.state.sim_seconds_elapsed))
                app.state.last_progress_log_sim = float(app.state.sim_seconds_elapsed)

            # ---- 唯一终止条件：任务生成已停止 + 所有任务都结算 ----
            # 注意：达到 max_sim_seconds **不会**直接停仿真——它只表示
            # "不再生成新任务"。仿真会继续推进直到现存任务全部 COMPLETED / TIMEOUT。
            stopped_this_tick = False
            stop_reason_this_tick = ""
            gen_just_stopped = _task_generation_stopped(app, data_manager)
            if gen_just_stopped and not getattr(app.state, "_gen_stop_logged", False):
                print(
                    f"[Sim] Task generation stopped "
                    f"(sim_elapsed={app.state.sim_seconds_elapsed:.0f}s, "
                    f"total_tasks={len(data_manager.get_tasks())}). "
                    f"Simulation continues until all tasks are settled."
                )
                experiment_logger.log(
                    f"task generation stopped at sim_elapsed="
                    f"{app.state.sim_seconds_elapsed:.0f}s "
                    f"(reason: budget/max_sim_seconds reached). "
                    f"continuing until all tasks settle.",
                    level="INFO",
                )
                app.state._gen_stop_logged = True

            if STOP_WHEN_ALL_TASKS_DONE and _all_tasks_settled(app, data_manager):
                print("[Sim] All tasks settled, auto-stopping simulation.")
                app.state.simulation_running = False
                _flush_task_seed_artifact(app)
                experiment_logger.finalize_experiment(
                    data_manager,
                    float(app.state.sim_seconds_elapsed),
                    stop_reason="all_tasks_done",
                )
                stopped_this_tick = True
                stop_reason_this_tick = "all_tasks_done"

            await websocket_handler.broadcast_system_status()
            await websocket_handler.broadcast_performance_metrics()
            await websocket_handler.broadcast_state()
            if stopped_this_tick:
                await websocket_handler.broadcast_simulation_finished(
                    stop_reason_this_tick or "all_tasks_done",
                    float(app.state.sim_seconds_elapsed),
                )

            # 仿真在本 tick 内被自动停掉了：跳过本 tick 的调度
            if stopped_this_tick:
                continue

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

                    # 兜底终止：任务不再生成 + 全车回仓空闲 + 连续多轮无派送命令
                    # 视为“剩余任务当前不可完成”，自动结束，并把未完成任务记 0 分。
                    if STOP_WHEN_ALL_TASKS_DONE and _task_generation_stopped(app, data_manager):
                        from backend.data.task import TaskStatus

                        tasks_now = data_manager.get_tasks()
                        has_unsettled = any(
                            t.status not in (TaskStatus.COMPLETED, TaskStatus.TIMEOUT)
                            for t in tasks_now
                        )
                        deliver_count = sum(
                            1 for c in (commands or []) if c.get("action") == "deliver"
                        )
                        if (
                            has_unsettled
                            and _all_vehicles_at_warehouse_and_idle(data_manager)
                            and deliver_count == 0
                        ):
                            app.state.no_assign_sched_streak = int(
                                getattr(app.state, "no_assign_sched_streak", 0)
                            ) + 1
                        else:
                            app.state.no_assign_sched_streak = 0

                        if int(getattr(app.state, "no_assign_sched_streak", 0)) >= MAX_STUCK_SCHED_CYCLES:
                            changed = _mark_unfinished_tasks_zero(data_manager)
                            print(
                                "[Sim] No feasible assignments for consecutive cycles; "
                                f"auto-stopping. unresolved tasks marked TIMEOUT: {changed}"
                            )
                            app.state.simulation_running = False
                            _flush_task_seed_artifact(app)
                            experiment_logger.finalize_experiment(
                                data_manager,
                                float(app.state.sim_seconds_elapsed),
                                stop_reason="no_feasible_tasks_left",
                            )
                            await websocket_handler.broadcast_system_status()
                            await websocket_handler.broadcast_performance_metrics()
                            await websocket_handler.broadcast_state()
                            await websocket_handler.broadcast_simulation_finished(
                                "no_feasible_tasks_left",
                                float(app.state.sim_seconds_elapsed),
                            )
                            continue
                    else:
                        app.state.no_assign_sched_streak = 0
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

    def _consume_cli_flag(*names: str) -> bool:
        hit = False
        for name in names:
            while name in sys.argv:
                hit = True
                sys.argv.remove(name)
        return hit

    def _run_headless_experiment() -> None:
        """无前端模式：直接后端完成整次仿真并自动结束。"""
        global _task_id_counter, _runtime_tasks_generated

        data_manager = DataManager()
        algorithm_manager = AlgorithmManager(data_manager.path_calculator)
        decision_manager = DecisionManager(data_manager, algorithm_manager)

        # 伪 app/state（复用现有 helper）
        fake_app = SimpleNamespace()
        fake_app.state = SimpleNamespace()
        fake_app.state.simulation_running = True
        fake_app.state.sim_seconds_elapsed = 0.0
        fake_app.state.last_dynamic_scheduling_ts = 0.0
        fake_app.state.last_progress_log_sim = 0.0
        fake_app.state._gen_stop_logged = False
        fake_app.state.no_assign_sched_streak = 0
        fake_app.state.task_seed_controller = _build_task_seed_controller()
        fake_app.state.task_generation_seed_artifact = None
        fake_app.state.seed_note = ""
        fake_app.state.static_release_notified_ids = set()

        _task_id_counter = 1000
        _runtime_tasks_generated = 0
        data_manager.tasks.clear()
        data_manager.vehicles.clear()
        data_manager.charging_stations.clear()
        _initialize_simulation(fake_app, data_manager)

        experiment_logger.start_experiment(
            config.get_experiment_config(),
            config.snapshot(),
        )
        seed_ctrl: TaskSeedController = fake_app.state.task_seed_controller
        seed_payload = seed_ctrl.to_payload(
            note="replay from seed file" if seed_ctrl.is_replay else "recorded in this run"
        )
        artifact_path = experiment_logger.write_yaml_artifact(
            "task_generation_seed.yaml",
            seed_payload,
        )
        fake_app.state.task_generation_seed_artifact = artifact_path
        fake_app.state.seed_note = (
            f"replay={seed_ctrl.source_path}"
            if seed_ctrl.is_replay
            else f"record(base_seed={seed_ctrl.base_seed})"
        )

        experiment_logger.log(
            f"[HEADLESS] mode={OPT_MODE}, strategy={_configured_strategy_name()}, "
            f"fleet_size={len(data_manager.get_vehicles())}, "
            f"stations={len(data_manager.get_charging_stations())}, "
            f"initial_tasks={len(data_manager.get_tasks())}, "
            f"task_budget={TOTAL_TASK_BUDGET}, max_sim_seconds={MAX_SIM_SECONDS}, "
            f"task_seed={fake_app.state.seed_note}, seed_file={artifact_path or '(none)'}"
        )

        task_cfg = config.get_task_config()
        interval_min = int(task_cfg.get("generation_interval_sec_min", 10))
        interval_max = int(task_cfg.get("generation_interval_sec_max", 30))
        batch_min = int(task_cfg.get("generation_batch_min", 1))
        batch_max = int(task_cfg.get("generation_batch_max", 3))
        max_pending = int(task_cfg.get("max_pending_tasks", 20))
        # 将“真实秒间隔”映射为“仿真秒间隔”
        next_gen_at_sim = float(seed_ctrl.rng.randint(interval_min, interval_max) * SIM_SPEED_FACTOR)

        stop_reason = "manual_stop"
        while fake_app.state.simulation_running:
            # 与在线模式保持一致：每 tick 先等待一个真实时间片，
            # 避免“仿真秒暴走但墙钟几乎不走”导致 release/deadline 偏差。
            time.sleep(max(0.0, float(TICK_INTERVAL_SEC)))
            sim_dt = SIM_SPEED_FACTOR * TICK_INTERVAL_SEC

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

            fake_app.state.sim_seconds_elapsed += sim_dt
            _notify_released_static_tasks(fake_app, data_manager)

            last_prog = float(getattr(fake_app.state, "last_progress_log_sim", 0.0))
            if fake_app.state.sim_seconds_elapsed - last_prog >= 300.0:
                _log_progress(
                    data_manager,
                    decision_manager,
                    float(fake_app.state.sim_seconds_elapsed),
                )
                fake_app.state.last_progress_log_sim = float(fake_app.state.sim_seconds_elapsed)

            # 任务生成（headless 同步版）
            if seed_ctrl.is_replay:
                due = seed_ctrl.pop_due_events(float(fake_app.state.sim_seconds_elapsed))
                for ev in due:
                    if str(ev.get("phase", "")) == "initial":
                        continue
                    pos_raw = ev.get("position") or {}
                    pos = Position(x=float(pos_raw.get("x", 0.0)), y=float(pos_raw.get("y", 0.0)))
                    t = _create_task(
                        data_manager=data_manager,
                        task_id=int(ev.get("task_id")),
                        pos=pos,
                        weight=float(ev.get("weight", 10.0)),
                        priority=int(ev.get("priority", 1)),
                        create_time=int(time.time()),
                        deadline_offset=int(ev.get("deadline_offset", 1800)),
                    )
                    _runtime_tasks_generated += 1
                    _task_id_counter = max(_task_id_counter, int(t.id))
            else:
                if (
                    float(fake_app.state.sim_seconds_elapsed) >= next_gen_at_sim
                    and not _task_generation_stopped(fake_app, data_manager)
                ):
                    pending = len(data_manager.get_pending_tasks())
                    if pending < max_pending:
                        batch = seed_ctrl.rng.randint(batch_min, batch_max)
                        created = 0
                        for _ in range(batch):
                            if pending + created >= max_pending:
                                break
                            if _task_generation_stopped(fake_app, data_manager):
                                break
                            _task_id_counter += 1
                            t = generate_random_task(
                                fake_app,
                                data_manager,
                                _task_id_counter,
                                sim_seconds=float(fake_app.state.sim_seconds_elapsed),
                                phase="runtime",
                            )
                            if t is not None:
                                created += 1
                                _runtime_tasks_generated += 1
                    next_gen_at_sim += float(seed_ctrl.rng.randint(interval_min, interval_max) * SIM_SPEED_FACTOR)

            if STOP_WHEN_ALL_TASKS_DONE and _all_tasks_settled(fake_app, data_manager):
                stop_reason = "all_tasks_done"
                fake_app.state.simulation_running = False
                break

            now_wall = time.time()
            last_dyn = float(getattr(fake_app.state, "last_dynamic_scheduling_ts", 0.0))
            commands = []
            if (now_wall - last_dyn) >= DYNAMIC_SCHEDULE_INTERVAL_SEC:
                commands = decision_manager.dynamic_scheduling()
                fake_app.state.last_dynamic_scheduling_ts = now_wall
            if STOP_WHEN_ALL_TASKS_DONE and _task_generation_stopped(fake_app, data_manager):
                from backend.data.task import TaskStatus

                tasks_now = data_manager.get_tasks()
                has_unsettled = any(
                    t.status not in (TaskStatus.COMPLETED, TaskStatus.TIMEOUT)
                    for t in tasks_now
                )
                deliver_count = sum(
                    1 for c in (commands or []) if c.get("action") == "deliver"
                )
                if (
                    has_unsettled
                    and _all_vehicles_at_warehouse_and_idle(data_manager)
                    and deliver_count == 0
                ):
                    fake_app.state.no_assign_sched_streak = int(
                        getattr(fake_app.state, "no_assign_sched_streak", 0)
                    ) + 1
                else:
                    fake_app.state.no_assign_sched_streak = 0

                if int(getattr(fake_app.state, "no_assign_sched_streak", 0)) >= MAX_STUCK_SCHED_CYCLES:
                    _mark_unfinished_tasks_zero(data_manager)
                    stop_reason = "no_feasible_tasks_left"
                    fake_app.state.simulation_running = False
                    break
            else:
                fake_app.state.no_assign_sched_streak = 0

        _flush_task_seed_artifact(fake_app)
        experiment_logger.finalize_experiment(
            data_manager,
            float(getattr(fake_app.state, "sim_seconds_elapsed", 0.0)),
            stop_reason=stop_reason,
        )
        print(
            f"[Headless] finished. reason={stop_reason}, "
            f"sim_seconds={float(getattr(fake_app.state, 'sim_seconds_elapsed', 0.0)):.0f}, "
            f"log_dir={experiment_logger.run_dir}"
        )

    use_headless = _consume_cli_flag("-u", "--headless")
    if use_headless:
        _run_headless_experiment()
    else:
        uvicorn.run(app, host="0.0.0.0", port=8000)
