import asyncio
import time
import random
import os
import json
import sys
from datetime import datetime
from fastapi import FastAPI, WebSocket
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.data.data_manager import DataManager
from backend.data.position import Position
from backend.data.task import Task
from backend.data.vehicle import Vehicle, VehicleStatus
from backend.data.charging_station import ChargingStation

from backend.algorithm.algorithm_manager import AlgorithmManager

from backend.decision.decision_manager import DecisionManager

from backend.interface.api_controller import APIController
from backend.interface.websocket_handler import WebSocketHandler

from backend.config import config

# 全局变量，存储当前问题规模和算法
current_problem_scale = "medium"
current_algorithm = "genetic"


class SimulationConfigRequest(BaseModel):
    mode: str = "realtime"   # realtime | static
    scale: str = "medium"    # small | medium | large

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
    app.state.simulation_mode = "realtime"
    app.state.static_planning_interval = int(
        os.getenv("NEFT_STATIC_PLAN_INTERVAL_SEC", str(config.PLANNING_INTERVAL))
    )
    app.state.last_static_planning_ts = 0
    # Wall-clock throttle for realtime dynamic_scheduling (see NEFT_DYNAMIC_SCHEDULE_INTERVAL_SEC)
    app.state.last_dynamic_scheduling_ts = 0.0

    app.include_router(api_controller.get_router(), prefix="/api", tags=["API"])
    
    # 创建初始日志文件
    create_log_file()

    asyncio.create_task(background_tasks(app, data_manager, decision_manager, websocket_handler))
    asyncio.create_task(task_generator(app, data_manager))

    yield

    print("Shutting down NEFT System...")

app = FastAPI(
    title="New Energy Fleet Transportation System",
    description="新能源物流车队协同调度系统",
    version="1.0.0",
    lifespan=lifespan
)

@app.post("/api/set-problem-scale")
async def set_problem_scale(scale: str):
    """设置问题规模"""
    global current_problem_scale, current_algorithm
    
    if scale not in ["small", "medium", "large"]:
        return {"error": "Invalid scale. Must be one of: small, medium, large"}
    
    current_problem_scale = scale
    
    # 重新初始化数据
    data_manager = app.state.data_manager
    
    # 清空现有数据
    data_manager.tasks.clear()
    data_manager.vehicles.clear()
    data_manager.charging_stations.clear()
    
    # 重新初始化
    current_algorithm = initialize_test_data(data_manager, scale)
    
    return {
        "status": "success",
        "scale": scale,
        "algorithm": current_algorithm
    }


@app.post("/api/simulation/config")
async def set_simulation_config(request: SimulationConfigRequest):
    global current_problem_scale, current_algorithm

    if request.mode not in ["realtime", "static"]:
        return {"success": False, "message": "mode must be realtime or static"}
    if request.scale not in ["small", "medium", "large"]:
        return {"success": False, "message": "scale must be small, medium or large"}

    app.state.simulation_mode = request.mode

    # scale changes are applied immediately
    if current_problem_scale != request.scale:
        current_problem_scale = request.scale
        data_manager = app.state.data_manager
        data_manager.tasks.clear()
        data_manager.vehicles.clear()
        data_manager.charging_stations.clear()
        current_algorithm = initialize_test_data(data_manager, request.scale)

    return {
        "success": True,
        "running": app.state.simulation_running,
        "mode": app.state.simulation_mode,
        "scale": current_problem_scale,
        "algorithm": current_algorithm
    }


class SimulationStartRequest(BaseModel):
    mode: str = "realtime"   # realtime | static
    scale: str = "medium"    # small | medium | large (仅静态规划需要)


@app.post("/api/simulation/start")
async def start_simulation(request: SimulationStartRequest):
    global current_problem_scale, current_algorithm
    
    # 验证参数
    if request.mode not in ["realtime", "static"]:
        return {"success": False, "message": "mode must be realtime or static"}
    if request.scale not in ["small", "medium", "large"]:
        return {"success": False, "message": "scale must be small, medium or large"}
    
    # 设置模式和规模
    app.state.simulation_mode = request.mode
    current_problem_scale = request.scale
    
    data_manager = app.state.data_manager
    decision_manager = app.state.decision_manager
    
    # 清空现有数据
    data_manager.tasks.clear()
    data_manager.vehicles.clear()
    data_manager.charging_stations.clear()
    decision_manager._dynamic_scheduling.active_commands.clear()
    
    # 根据模式初始化
    if request.mode == "static":
        # 静态规划：预生成任务和车辆
        current_algorithm = initialize_test_data(data_manager, request.scale)
        print(f"[Static Mode] Initialized with scale={request.scale}, tasks={len(data_manager.get_tasks())}")
    else:
        # 实时规划：只初始化车辆和充电站，不生成任务
        _initialize_realtime_mode(data_manager, request.scale)
        current_algorithm = "realtime_heuristic"
        print(f"[Realtime Mode] Initialized with scale={request.scale}, no pre-generated tasks")
    
    # 设置算法管理器的仓库位置
    algorithm_manager = decision_manager.algorithm_manager
    if data_manager.warehouse_position:
        algorithm_manager.warehouse_pos = (data_manager.warehouse_position.x, data_manager.warehouse_position.y)
    
    # 启动仿真
    app.state.simulation_running = True
    app.state.last_static_planning_ts = 0
    app.state.last_dynamic_scheduling_ts = 0.0
    
    return {
        "success": True,
        "running": True,
        "mode": app.state.simulation_mode,
        "scale": current_problem_scale,
        "algorithm": current_algorithm,
        "tasks_count": len(data_manager.get_tasks()),
        "vehicles_count": len(data_manager.get_vehicles())
    }


@app.post("/api/simulation/stop")
async def stop_simulation():
    app.state.simulation_running = False
    return {
        "success": True,
        "running": False,
        "mode": app.state.simulation_mode,
        "scale": current_problem_scale,
        "algorithm": current_algorithm
    }


@app.post("/api/simulation/reset")
async def reset_simulation():
    """重置模拟到初始状态（未启动状态），清空所有数据，需要重新选择模式和规模后启动"""
    app.state.simulation_running = False
    global current_problem_scale, current_algorithm
    
    data_manager = app.state.data_manager
    # 清空所有数据
    data_manager.tasks.clear()
    data_manager.vehicles.clear()
    data_manager.charging_stations.clear()
    
    # 重置决策模块状态
    dsm = app.state.decision_manager._dynamic_scheduling
    dsm.active_commands.clear()
    dsm.pending_tasks.clear()
    app.state.decision_manager.last_selected_strategy = "shortest_task_first"
    app.state.decision_manager.last_strategy_reason = "init"
    app.state.decision_manager.last_strategy_scores = {}
    app.state.last_dynamic_scheduling_ts = 0.0
    app.state.last_static_planning_ts = 0
    
    # 重置为初始状态（未配置）
    current_problem_scale = None
    current_algorithm = None
    app.state.simulation_mode = None

    return {
        "success": True,
        "running": False,
        "mode": None,
        "scale": None,
        "message": "Simulation reset. Please select mode and scale, then start simulation."
    }


@app.get("/api/simulation/status")
async def get_simulation_status():
    return {
        "running": app.state.simulation_running,
        "mode": app.state.simulation_mode,
        "scale": current_problem_scale,
        "algorithm": current_algorithm
    }

@app.get("/api/problem-scale")
async def get_problem_scale():
    """获取当前问题规模"""
    return {
        "scale": current_problem_scale,
        "algorithm": current_algorithm
    }

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    if not hasattr(app.state, 'websocket_handler'):
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
        "message": "NEFT System API",
        "version": "1.0.0",
        "docs": "/docs",
        "websocket": "/ws"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

def _initialize_realtime_mode(data_manager: DataManager, problem_scale="medium"):
    """
    实时规划模式初始化：只创建车辆和充电站，不预生成任务。
    任务将通过 task_generator 动态生成。
    
    位置策略：
    - 仓库固定在图的中心节点
    - 充电站分布在图的四周节点
    - 车辆从仓库（中心）出发
    """
    print(f"Initializing realtime mode (scale={problem_scale})...")

    fleet_config = config.get_fleet_config()
    station_cfg = config.get_charging_station_config()
    task_config = config.get_task_config()

    # 任务重量范围
    global global_task_weight_range
    global_task_weight_range = (task_config["min_weight"], task_config["max_weight"])

    # 仓库位置：固定在图的中心节点
    warehouse_xy = data_manager.path_calculator.get_central_node_xy()
    warehouse_pos = Position(x=warehouse_xy[0], y=warehouse_xy[1])
    data_manager.set_warehouse_position(warehouse_pos)
    print(f"  Warehouse positioned at center node: ({warehouse_pos.x:.6f}, {warehouse_pos.y:.6f})")

    # 混合车队初始化：所有车辆从仓库出发
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

    # 充电站初始化：分布在图的四周节点
    station_count = fleet_config["station_count"]
    station_positions_xy = data_manager.path_calculator.get_peripheral_nodes_xy(station_count)
    for i, pos_xy in enumerate(station_positions_xy, start=1):
        station = ChargingStation(
            id=f"cs{i}",
            position=Position(x=pos_xy[0], y=pos_xy[1]),
            capacity=station_cfg["default_capacity"],
            queue_count=0,
            charging_vehicles=[],
            load_pressure=0.0,
            charging_rate=0.022,
        )
        data_manager.add_charging_station(station)
        print(f"  Charging station {i} positioned at peripheral node: ({pos_xy[0]:.6f}, {pos_xy[1]:.6f})")

    print(f"[Realtime Mode] Fleet: {vehicle_id - 1} vehicles, Stations: {station_count}, Tasks: 0 (will be generated dynamically)")


def initialize_test_data(data_manager: DataManager, problem_scale="medium"):
    """
    初始化仿真数据。
    修正要点：
    - 车队规模固定为适应番禺区的真实规模（small:8, medium:15, large:7 = 30辆）
    - problem_scale 小中大 = 静态规划下的任务规樘（实时模式下无意义）
    - 初始电量改为100%（满电出发）
    - 充电站数量固定为6座，每座内置3个充电桩
    
    位置策略：
    - 仓库固定在图的中心节点
    - 充电站分布在图的四周节点
    - 车辆从仓库（中心）出发
    """
    print(f"Initializing test data (scale={problem_scale})...")

    fleet_config = config.get_fleet_config()
    station_cfg  = config.get_charging_station_config()
    task_config  = config.get_task_config()

    # 任务重量范围（均以 kg 为单位，与 vehicle.max_load 一致）
    task_scale_cfg = config.get_task_scale_config(problem_scale)
    global global_task_weight_range
    global_task_weight_range = (task_config["min_weight"], task_config["max_weight"])

    # 仓库位置：固定在图的中心节点
    warehouse_xy = data_manager.path_calculator.get_central_node_xy()
    warehouse_pos = Position(x=warehouse_xy[0], y=warehouse_xy[1])
    data_manager.set_warehouse_position(warehouse_pos)
    print(f"  Warehouse positioned at center node: ({warehouse_pos.x:.6f}, {warehouse_pos.y:.6f})")

    # ----------------------------------------------------------------
    # 混合车队初始化：small 8辆 + medium 15辆 + large 7辆 = 30辆
    # 所有车辆从仓库（中心）出发
    # ----------------------------------------------------------------
    vehicle_id = 1
    type_counts = [
        ("small",  fleet_config["small_count"]),
        ("medium", fleet_config["medium_count"]),
        ("large",  fleet_config["large_count"]),
    ]
    for vtype, count in type_counts:
        vcfg = config.get_vehicle_config(vtype)
        for _ in range(count):
            vehicle = Vehicle(
                id=vehicle_id,
                position=Position(x=warehouse_pos.x, y=warehouse_pos.y),
                battery=vcfg["max_battery"],        # 满电出发（Q3）
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

    # ----------------------------------------------------------------
    # 充电站初始化：6座充电站，分布在图的四周节点
    # ----------------------------------------------------------------
    station_count = fleet_config["station_count"]
    station_positions_xy = data_manager.path_calculator.get_peripheral_nodes_xy(station_count)
    for i, pos_xy in enumerate(station_positions_xy, start=1):
        station = ChargingStation(
            id=f"cs{i}",
            position=Position(x=pos_xy[0], y=pos_xy[1]),
            capacity=station_cfg["default_capacity"],
            queue_count=0,
            charging_vehicles=[],
            load_pressure=0.0,
            charging_rate=0.022,   # 默认中型车充电功率，旧字段向后兼容
        )
        data_manager.add_charging_station(station)
        print(f"  Charging station {i} positioned at peripheral node: ({pos_xy[0]:.6f}, {pos_xy[1]:.6f})")

    # 静态规划模式：按规模预生成任务
    pre_generated_tasks = 0
    expected_tasks = 0
    if problem_scale in ("small", "medium", "large"):
        expected_tasks = random.randint(task_scale_cfg["min_tasks"], task_scale_cfg["max_tasks"])
        # 实际生成并添加任务到 DataManager，持续尝试直到生成足够任务或达到最大尝试次数
        task_id_start = 1
        max_attempts = expected_tasks * 3  # 最多尝试3倍预期数量的任务
        attempts = 0
        while pre_generated_tasks < expected_tasks and attempts < max_attempts:
            task = generate_random_task(data_manager, task_id_start + pre_generated_tasks)
            if task:
                pre_generated_tasks += 1
            attempts += 1
    
    # 如果生成的任务数量明显少于预期，发出警告
    if expected_tasks > 0 and pre_generated_tasks < expected_tasks * 0.8:
        print(f"[Warning] 任务生成率较低：预期 {expected_tasks} 个，实际生成 {pre_generated_tasks} 个"
              f"（{(pre_generated_tasks/expected_tasks*100):.1f}%）")

    print(f"Fleet: {vehicle_id-1} vehicles (small*{fleet_config['small_count']}, "
          f"medium*{fleet_config['medium_count']}, large*{fleet_config['large_count']}), "
          f"Stations: {station_count}, Pre-generated tasks: {pre_generated_tasks}")
    return "ortools"   # 默认算法标识


# 全局变量，存储当前问题规模的任务重量范围
global_task_weight_range = (10, 100)  # 默认中规模

def generate_random_task(data_manager: DataManager, task_id: int, max_retries: int = 50):
    """生成随机任务（与 offline_simulator.py 保持一致）
    
    新增：检查任务位置与仓库之间的路径可达性，不可达则重新生成位置
    
    Args:
        data_manager: 数据管理器
        task_id: 任务ID
        max_retries: 最大重试次数，超过则返回None
    
    Returns:
        Task对象，如果无法生成可达任务则返回None
    """
    task_config = config.get_task_config()
    path_calculator = data_manager.path_calculator
    warehouse_pos = data_manager.warehouse_position
    
    # 尝试生成可达的任务位置
    pos = None
    for attempt in range(max_retries):
        candidate_pos = data_manager.sample_graph_position()
        
        # 检查从仓库到任务位置是否可达
        try:
            path = path_calculator.find_shortest_path(
                (warehouse_pos.x, warehouse_pos.y),
                (candidate_pos.x, candidate_pos.y)
            )
            if path and len(path) > 0:
                pos = candidate_pos
                break  # 找到可达位置
        except Exception:
            # 路径不可达，继续尝试
            pass
    
    if pos is None:
        print(f"[Warning] 无法为任务 {task_id} 生成可达位置（已尝试 {max_retries} 次）")
        return None
    
    x, y = pos.x, pos.y
    weight = random.uniform(global_task_weight_range[0], global_task_weight_range[1])
    priority = random.randint(task_config["min_priority"], task_config["max_priority"])
    create_time = int(time.time())
    deadline = create_time + random.randint(1800, 7200)
    
    task = Task(
        id=task_id,
        position=Position(x=x, y=y),
        weight=weight,
        create_time=create_time,
        deadline=deadline,
        priority=priority
    )
    
    data_manager.add_task(task)
    return task

def get_log_file_path():
    log_dir = os.path.join(os.path.dirname(__file__), '..', 'test', 'log')
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return os.path.join(log_dir, f'neft_log_{timestamp}.json')

def get_last_log_file():
    log_dir = os.path.join(os.path.dirname(__file__), '..', 'test', 'log')
    if not os.path.exists(log_dir):
        return None
    
    log_files = [f for f in os.listdir(log_dir) if f.endswith('.json')]
    if not log_files:
        return None
    
    log_files.sort(reverse=True)
    return os.path.join(log_dir, log_files[0])

def get_current_parameters():
    vehicle_config = config.get_vehicle_config("medium")
    return {
        "vehicle_config": {
            "max_battery": vehicle_config["max_battery"],
            "max_load": vehicle_config["max_load"],
            "unit_energy_consumption": vehicle_config["unit_energy_consumption"]
        },
        "vehicle_count": 3,
        "charging_station_config": config.get_charging_station_config(),
        "task_config": config.get_task_config()
    }

def parameters_changed():
    last_log_file = get_last_log_file()
    if not last_log_file:
        return True
    
    try:
        with open(last_log_file, 'r', encoding='utf-8') as f:
            last_log = json.load(f)
        
        last_params = last_log.get('parameters', {})
        current_params = get_current_parameters()
        
        return last_params != current_params
    except Exception:
        return True

def create_log_file(tasks=None):
    if not parameters_changed():
        print("Parameters unchanged, skipping log creation")
        return
    
    log_path = get_log_file_path()
    log_data = {
        "timestamp": datetime.now().isoformat(),
        "parameters": get_current_parameters(),
        "tasks": []
    }
    
    if tasks:
        for task in tasks:
            log_data["tasks"].append({
                "id": task.id,
                "position": {"x": task.position.x, "y": task.position.y},
                "weight": task.weight,
                "create_time": task.create_time,
                "deadline": task.deadline,
                "priority": task.priority
            })
    
    with open(log_path, 'w', encoding='utf-8') as f:
        json.dump(log_data, f, indent=2, ensure_ascii=False)
    
    print(f"Log created: {log_path}")

async def task_generator(app: FastAPI, data_manager: DataManager):
    task_id_counter = 100
    while True:
        try:
            await asyncio.sleep(random.randint(10, 30))
            if not getattr(app.state, "simulation_running", False):
                continue
            
            # 静态规划模式下不生成新任务
            if getattr(app.state, "simulation_mode", "realtime") == "static":
                continue

            pending_count = len(data_manager.get_pending_tasks())
            if pending_count >= 50:
                print(f"Pending tasks reached {pending_count}, skipping generation this cycle")
                continue
            
            # 随机生成1-5个任务，更贴近真实场景
            num_tasks_to_generate = random.randint(1, 5)
            generated_count = 0
            
            for _ in range(num_tasks_to_generate):
                if pending_count + generated_count >= 50:
                    break
                    
                task_id_counter += 1
                task = generate_random_task(data_manager, task_id_counter)
                if task:
                    generated_count += 1
                    print(f"Generated new task {task.id}: position=({task.position.x:.2f}, {task.position.y:.2f}), weight={task.weight:.2f}")
            
            print(f"[TaskGenerator] Batch generated {generated_count}/{num_tasks_to_generate} tasks (pending: {pending_count + generated_count})")
            
            # 记录每个新生成任务
            log_dir = os.path.join(os.path.dirname(__file__), '..', 'test', 'log')
            os.makedirs(log_dir, exist_ok=True)
            
            # 获取当前日志文件（若不存在则创建）
            current_log = None
            log_files = [f for f in os.listdir(log_dir) if f.endswith('.json')]
            if log_files:
                log_files.sort(reverse=True)
                current_log = os.path.join(log_dir, log_files[0])
                
                # 读取当前日志
                try:
                    with open(current_log, 'r', encoding='utf-8') as f:
                        log_data = json.load(f)
                    
                    # 将新任务追加到日志
                    log_data["tasks"].append({
                        "id": task.id,
                        "position": {"x": task.position.x, "y": task.position.y},
                        "weight": task.weight,
                        "create_time": task.create_time,
                        "deadline": task.deadline,
                        "priority": task.priority
                    })
                    
                    # 回写日志文件
                    with open(current_log, 'w', encoding='utf-8') as f:
                        json.dump(log_data, f, indent=2, ensure_ascii=False)
                except Exception as e:
                    print(f"Error updating log: {e}")
            
        except Exception as e:
            print(f"Task generator error: {e}")

# ============================================================
# 仿真加速倍率（建议2：1 现实秒 = 60 仿真秒）# ============================================================
# 仿真速度从配置读取，可通过环境变量 NEFT_SIM_SPEED 覆盖
# ============================================================
sim_config = config.get_simulation_config()
SIM_SPEED_FACTOR: float = float(sim_config.get("speed_factor", 120))

# 实时模式下 dynamic_scheduling 最小间隔（秒，墙钟）。默认 1 与原先「每秒重调度」一致；调大可降 CPU。
DYNAMIC_SCHEDULE_INTERVAL_SEC: float = float(os.getenv("NEFT_DYNAMIC_SCHEDULE_INTERVAL_SEC", "1"))

async def background_tasks(app: FastAPI, data_manager: DataManager, decision_manager: DecisionManager,
                          websocket_handler: WebSocketHandler):
    """
    主循环（1次/秒现实时间 = SIM_SPEED_FACTOR 秒仿真时间）。

    建议1 落地：正常调度默认充到100%（config.normal_release=100.0），
               仅在任务紧急（deadline<30min）时截止60%离站。
    建议2 落地：SIM_SPEED_FACTOR=60，每现实秒推进60仿真秒。
              - 位置更新 time_delta = SIM_SPEED_FACTOR
              - 充电量    charge_δ  = charging_power × SIM_SPEED_FACTOR
    """
    while True:
        try:
            await asyncio.sleep(1)

            if not getattr(app.state, "simulation_running", False):
                await websocket_handler.broadcast_system_status()
                await websocket_handler.broadcast_state()
                continue

            vehicles = data_manager.get_vehicles()
            for vehicle in vehicles:

                if vehicle.status == VehicleStatus.TRANSPORTING:
                    # 运输中：time_delta 乘以加速倍率（建议2）
                    data_manager.update_vehicle_position_by_speed(
                        vehicle.id, time_delta=SIM_SPEED_FACTOR
                    )

                elif vehicle.status == VehicleStatus.CHARGING:
                    # 充电中：每tick充电量 = power × 加速倍率（建议2）
                    charge_rate = vehicle.charging_power if vehicle.charging_power > 0 else 0.022
                    charge_delta = charge_rate * SIM_SPEED_FACTOR
                    new_battery = min(vehicle.max_battery, vehicle.battery + charge_delta)
                    data_manager.update_vehicle_battery(vehicle.id, new_battery)

                    # 情境感知离站阈值（建议1 + Q4）
                    release_threshold_pct = decision_manager.evaluate_charge_release_threshold(vehicle)

                    should_release = False
                    if release_threshold_pct <= 0.0:
                        should_release = True  # 高优打断
                    elif vehicle.get_battery_percentage() >= release_threshold_pct:
                        should_release = True  # 达到阈值

                    if should_release and vehicle.charging_station_id:
                        data_manager.remove_vehicle_from_charging_station(
                            vehicle.id, vehicle.charging_station_id
                        )
                        print(f"[Sim×{SIM_SPEED_FACTOR:.0f}] Vehicle {vehicle.id} "
                              f"({vehicle.vehicle_type}) left station "
                              f"at {vehicle.get_battery_percentage():.1f}% "
                              f"(threshold={release_threshold_pct:.0f}%)")

                elif vehicle.status == VehicleStatus.IDLE:
                    # 空闲车：主动电量管理（修复 B3）
                    charge_cmd = decision_manager.manage_battery(vehicle)
                    if charge_cmd:
                        station_id = charge_cmd.get("charging_station_id")
                        if station_id:
                            data_manager.add_vehicle_to_charging_station(vehicle.id, station_id)
                            print(f"[Sim×{SIM_SPEED_FACTOR:.0f}] Vehicle {vehicle.id} "
                                  f"auto-sent to station {station_id} "
                                  f"(battery={vehicle.get_battery_percentage():.1f}%)")

                # WAITING_CHARGE：由 ChargingStation.remove_vehicle 自动晋升，无需处理。

            decision_manager._dynamic_scheduling.clear_completed_commands()

            await websocket_handler.broadcast_system_status()
            await websocket_handler.broadcast_performance_metrics()
            await websocket_handler.broadcast_state()

            # 调度分支：实时模式每轮重调度；静态模式按周期触发
            global current_algorithm
            if getattr(app.state, "simulation_mode", "realtime") == "static":
                now_ts = int(time.time())
                interval = int(getattr(app.state, "static_planning_interval", 3600))
                if (app.state.last_static_planning_ts == 0
                        or now_ts - app.state.last_static_planning_ts >= interval):
                    print(f"[DEBUG] Executing static planning...")
                    try:
                        plan = decision_manager.static_planning()
                        print(f"[DEBUG] Static plan generated: {plan is not None}")
                        if plan:
                            print(f"[DEBUG] Plan routes: {len(plan.vehicle_routes) if plan.vehicle_routes else 0} vehicles")
                        commands = decision_manager.apply_static_plan(plan)
                        print(f"[DEBUG] Applied static plan: {len(commands)} commands")
                        # 静态规划模式下不执行实时调度，只执行静态规划生成的命令
                    except Exception as e:
                        print(f"[ERROR] Static planning failed: {e}")
                        import traceback
                        traceback.print_exc()
                    app.state.last_static_planning_ts = now_ts
            else:
                now_wall = time.time()
                last_dyn = float(getattr(app.state, "last_dynamic_scheduling_ts", 0.0))
                if (now_wall - last_dyn) >= DYNAMIC_SCHEDULE_INTERVAL_SEC:
                    pending = len(data_manager.get_pending_tasks())
                    idle = len(data_manager.get_idle_vehicles())
                    print(f"[DEBUG] Scheduling triggered: {pending} pending, {idle} idle vehicles")
                    try:
                        commands = decision_manager.dynamic_scheduling(strategy="auto")
                        print(f"[DEBUG] Generated {len(commands)} commands, strategy={decision_manager.last_selected_strategy}")
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
