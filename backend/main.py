import asyncio
import time
import random
import os
import json
import sys
from datetime import datetime
from fastapi import FastAPI, WebSocket
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting NEFT System...")
    
    data_manager = DataManager()
    algorithm_manager = AlgorithmManager(data_manager.path_calculator)
    decision_manager = DecisionManager(data_manager, algorithm_manager)
    websocket_handler = WebSocketHandler(data_manager, decision_manager)
    api_controller = APIController(data_manager, decision_manager, websocket_handler)

    data_manager.set_warehouse_position(Position(x=0, y=0))

    data_manager.register_task_update_callback(websocket_handler.broadcast_task_update)
    data_manager.register_vehicle_update_callback(websocket_handler.broadcast_vehicle_update)
    data_manager.register_station_update_callback(websocket_handler.broadcast_station_update)

    app.state.data_manager = data_manager
    app.state.decision_manager = decision_manager
    app.state.websocket_handler = websocket_handler
    app.state.api_controller = api_controller

    app.include_router(api_controller.get_router(), prefix="/api", tags=["API"])

    # 初始化测试数据，默认中规模
    global current_algorithm
    current_algorithm = initialize_test_data(data_manager, current_problem_scale)
    
    # Create initial log file
    create_log_file()

    asyncio.create_task(background_tasks(data_manager, decision_manager, websocket_handler))
    asyncio.create_task(task_generator(data_manager))

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

def initialize_test_data(data_manager: DataManager, problem_scale="medium"):
    print(f"Initializing test data for {problem_scale} scale problem...")

    # 根据问题规模设置参数
    if problem_scale == "small":
        # 小规模问题：1-5辆车，1-10个任务
        vehicle_count = 3
        station_count = 1
        vehicle_type = "medium"
        task_weight_range = (10, 50)
        algorithm = "mip"
    elif problem_scale == "large":
        # 大规模问题：15-50辆车，30-100个任务
        vehicle_count = 20
        station_count = 5
        vehicle_type = "large"
        task_weight_range = (10, 200)
        algorithm = "clustering+genetic"
    else:
        # 中规模问题：5-15辆车，10-30个任务
        problem_scale = "medium"
        vehicle_count = 10
        station_count = 2
        vehicle_type = "medium"
        task_weight_range = (10, 100)
        algorithm = "genetic"

    # 更新全局任务重量范围
    global global_task_weight_range
    global_task_weight_range = task_weight_range

    print(f"Scale: {problem_scale}, Vehicles: {vehicle_count}, Stations: {station_count}, Algorithm: {algorithm}")

    vehicle_config = config.get_vehicle_config(vehicle_type)
    station_config = config.get_charging_station_config()
    task_config = config.get_task_config()

    # 添加车辆（所有车辆从仓库出发）
    warehouse_pos = Position(x=0, y=0)
    for i in range(1, vehicle_count + 1):
        vehicle = Vehicle(
            id=i,
            position=Position(x=warehouse_pos.x, y=warehouse_pos.y),  # 车辆从仓库出发
            battery=vehicle_config["max_battery"] * 0.8,
            max_battery=vehicle_config["max_battery"],
            current_load=0.0,
            max_load=vehicle_config["max_load"],
            unit_energy_consumption=vehicle_config["unit_energy_consumption"],
            speed=vehicle_config["speed"]  # 添加速度配置
        )
        data_manager.add_vehicle(vehicle)

    # 添加充电站
    for i in range(1, station_count + 1):
        station = ChargingStation(
            id=f"cs{i}",
            position=Position(x=150 + i * 100, y=150),
            capacity=station_config["default_capacity"],
            queue_count=0,
            charging_vehicles=[],
            load_pressure=0.0,
            charging_rate=station_config["default_charging_rate"]
        )
        data_manager.add_charging_station(station)

    print(f"Test data initialized successfully for {problem_scale} scale problem")
    return algorithm

# 全局变量，存储当前问题规模的任务重量范围
global_task_weight_range = (10, 100)  # 默认中规模

def generate_random_task(data_manager: DataManager, task_id: int):
    task_config = config.get_task_config()
    
    x = random.uniform(50, 200)  # 缩小范围，使任务更接近仓库
    y = random.uniform(50, 200)  # 缩小范围，使任务更接近仓库
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

async def task_generator(data_manager: DataManager):
    task_id_counter = 100
    while True:
        try:
            await asyncio.sleep(random.randint(10, 30))
            
            task_id_counter += 1
            task = generate_random_task(data_manager, task_id_counter)
            print(f"Generated new task {task.id}: position=({task.position.x:.2f}, {task.position.y:.2f}), weight={task.weight:.2f}")
            
            # Log each generated task
            log_dir = os.path.join(os.path.dirname(__file__), '..', 'test', 'log')
            os.makedirs(log_dir, exist_ok=True)
            
            # Get the current log file or create a new one
            current_log = None
            log_files = [f for f in os.listdir(log_dir) if f.endswith('.json')]
            if log_files:
                log_files.sort(reverse=True)
                current_log = os.path.join(log_dir, log_files[0])
                
                # Read current log
                try:
                    with open(current_log, 'r', encoding='utf-8') as f:
                        log_data = json.load(f)
                    
                    # Add new task to log
                    log_data["tasks"].append({
                        "id": task.id,
                        "position": {"x": task.position.x, "y": task.position.y},
                        "weight": task.weight,
                        "create_time": task.create_time,
                        "deadline": task.deadline,
                        "priority": task.priority
                    })
                    
                    # Write back to log file
                    with open(current_log, 'w', encoding='utf-8') as f:
                        json.dump(log_data, f, indent=2, ensure_ascii=False)
                except Exception as e:
                    print(f"Error updating log: {e}")
            
        except Exception as e:
            print(f"Task generator error: {e}")

async def background_tasks(data_manager: DataManager, decision_manager: DecisionManager, 
                          websocket_handler: WebSocketHandler):
    while True:
        try:
            await asyncio.sleep(1)

            # 更新所有运输中车辆的位置（基于速度）
            vehicles = data_manager.get_vehicles()
            for vehicle in vehicles:
                if vehicle.status == VehicleStatus.TRANSPORTING:
                    data_manager.update_vehicle_position_by_speed(vehicle.id, time_delta=1.0)

            await websocket_handler.broadcast_system_status()

            await websocket_handler.broadcast_performance_metrics()

            await websocket_handler.broadcast_state()

            # 每次循环都执行动态调度，确保任务能够被及时分配
            # 使用当前选择的算法
            global current_algorithm
            decision_manager.dynamic_scheduling(strategy=current_algorithm)

        except Exception as e:
            print(f"Background task error: {e}")

if __name__ == "__main__":
	import uvicorn
	uvicorn.run(app, host="0.0.0.0", port=8000)
