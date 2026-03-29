from typing import List, Dict, Optional
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
import random
from backend.data.data_manager import DataManager
from backend.data.task import Task, TaskStatus, Position
from backend.data.vehicle import Vehicle, VehicleStatus
from backend.data.charging_station import ChargingStation
from backend.decision.decision_manager import DecisionManager
from backend.interface.websocket_handler import WebSocketHandler
from backend.interface.schemas import (
    PositionModel, TaskModel, VehicleModel, ChargingStationModel,
    CreateTaskRequest, CreateVehicleRequest, CreateChargingStationRequest,
    UpdateVehicleRequest, SchedulingRequest,
    SystemStatusResponse, PerformanceMetricsResponse,
    SimulationStateResponse, CommandResponse, SchedulingResultResponse,
    CompletePathRequest, CompletePathResponse,
    BatchCompletePathRequest, WarehousePositionModel, TaskCompletionInfo,
    SimulationSpeedRequest, SimulationSpeedResponse
)
from backend.interface.data_transformer import DataTransformer

class APIController:
    def __init__(self, data_manager: DataManager, decision_manager: DecisionManager,
                 websocket_handler: WebSocketHandler):
        self.data_manager = data_manager
        self.decision_manager = decision_manager
        self.websocket_handler = websocket_handler
        self.transformer = DataTransformer()
        self.router = APIRouter()

        self._setup_routes()

    def _setup_routes(self):
        @self.router.get("/tasks", response_model=List[TaskModel])
        async def get_tasks():
            tasks = self.data_manager.get_tasks()
            return [self.transformer.task_to_model(task) for task in tasks]

        @self.router.get("/tasks/{task_id}", response_model=TaskModel)
        async def get_task(task_id: int):
            task = self.data_manager.get_task(task_id)
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")
            return self.transformer.task_to_model(task)

        @self.router.post("/tasks", response_model=TaskModel)
        async def create_task(request: CreateTaskRequest):
            task_id = int(datetime.now().timestamp() * 1000) + random.randint(0, 1000)
            task = Task(
                id=task_id,
                position=Position(x=request.position.x, y=request.position.y),
                weight=request.weight,
                create_time=int(datetime.now().timestamp()),
                deadline=request.deadline,
                priority=request.priority
            )
            self.data_manager.add_task(task)
            await self.websocket_handler.broadcast_task_update(task)
            return self.transformer.task_to_model(task)

        @self.router.get("/vehicles", response_model=List[VehicleModel])
        async def get_vehicles():
            vehicles = self.data_manager.get_vehicles()
            return [self.transformer.vehicle_to_model(vehicle) for vehicle in vehicles]

        @self.router.get("/vehicles/{vehicle_id}", response_model=VehicleModel)
        async def get_vehicle(vehicle_id: int):
            vehicle = self.data_manager.get_vehicle(vehicle_id)
            if not vehicle:
                raise HTTPException(status_code=404, detail="Vehicle not found")
            return self.transformer.vehicle_to_model(vehicle)

        @self.router.post("/vehicles", response_model=VehicleModel)
        async def create_vehicle(request: CreateVehicleRequest):
            vehicle_id = len(self.data_manager.get_vehicles()) + 1
            vehicle = Vehicle(
                id=vehicle_id,
                position=Position(x=request.position.x, y=request.position.y),
                battery=request.battery,
                max_battery=request.max_battery,
                current_load=request.current_load,
                max_load=request.max_load,
                unit_energy_consumption=request.unit_energy_consumption
            )
            self.data_manager.add_vehicle(vehicle)
            await self.websocket_handler.broadcast_vehicle_update(vehicle)
            return self.transformer.vehicle_to_model(vehicle)

        @self.router.put("/vehicles/{vehicle_id}", response_model=VehicleModel)
        async def update_vehicle(vehicle_id: int, request: UpdateVehicleRequest):
            vehicle = self.data_manager.get_vehicle(vehicle_id)
            if not vehicle:
                raise HTTPException(status_code=404, detail="Vehicle not found")

            if request.position:
                vehicle.update_position(Position(x=request.position.x, y=request.position.y))
            if request.battery is not None:
                vehicle.update_battery(request.battery)
            if request.current_load is not None:
                vehicle.update_load(request.current_load)
            if request.status:
                vehicle.update_status(VehicleStatus(request.status))

            await self.websocket_handler.broadcast_vehicle_update(vehicle)
            return self.transformer.vehicle_to_model(vehicle)

        @self.router.get("/stations", response_model=List[ChargingStationModel])
        async def get_charging_stations():
            stations = self.data_manager.get_charging_stations()
            return [self.transformer.charging_station_to_model(station) for station in stations]

        @self.router.get("/stations/{station_id}", response_model=ChargingStationModel)
        async def get_charging_station(station_id: str):
            station = self.data_manager.get_charging_station(station_id)
            if not station:
                raise HTTPException(status_code=404, detail="Charging station not found")
            return self.transformer.charging_station_to_model(station)

        @self.router.post("/stations", response_model=ChargingStationModel)
        async def create_charging_station(request: CreateChargingStationRequest):
            station = ChargingStation(
                id=request.id,
                position=Position(x=request.position.x, y=request.position.y),
                capacity=request.capacity,
                queue_count=0,
                charging_vehicles=[],
                load_pressure=0.0,
                charging_rate=request.charging_rate
            )
            self.data_manager.add_charging_station(station)
            await self.websocket_handler.broadcast_station_update(station)
            return self.transformer.charging_station_to_model(station)

        @self.router.get("/map")
        async def get_map_data():
            return self.data_manager.get_map_data()

        @self.router.get("/system/status", response_model=SystemStatusResponse)
        async def get_system_status():
            status = self.decision_manager.get_system_status()
            return SystemStatusResponse(**status)

        @self.router.get("/system/performance", response_model=PerformanceMetricsResponse)
        async def get_performance_metrics():
            metrics = self.decision_manager.evaluate_system_performance()
            return PerformanceMetricsResponse(**metrics)

        @self.router.get("/system/state", response_model=SimulationStateResponse)
        async def get_simulation_state():
            state = self.data_manager.get_system_state()

            wh = state["warehouse_position"]
            return SimulationStateResponse(
                timestamp=state["timestamp"],
                warehouse_position=PositionModel(
                    x=wh["x"],
                    y=wh["y"],
                    gcj_lng=wh.get("gcj_lng"),
                    gcj_lat=wh.get("gcj_lat"),
                ),
                vehicles=[self.transformer.vehicle_to_model(v) for v in self.data_manager.get_vehicles()],
                tasks=[self.transformer.task_to_model(t) for t in self.data_manager.get_tasks()],
                charging_stations=[
                    self.transformer.charging_station_to_model(s)
                    for s in self.data_manager.get_charging_stations()
                ],
                total_score=state["total_score"],
                map_nodes=state["map_nodes"],
                map_edges=state["map_edges"]
            )

        @self.router.post("/scheduling", response_model=SchedulingResultResponse)
        async def schedule_tasks(request: SchedulingRequest):
            commands = self.decision_manager.dynamic_scheduling(strategy=request.strategy)

            for command in commands:
                await self.websocket_handler.broadcast_command(command)

            converted_commands = []
            for cmd in commands:
                command_data = dict(cmd)
                command_data["path"] = [
                    {"x": float(p[0]), "y": float(p[1])} if isinstance(p, (tuple, list)) else p
                    for p in command_data.get("path", [])
                ]
                command_data["complete_path"] = [
                    {"x": float(p[0]), "y": float(p[1])} if isinstance(p, (tuple, list)) else p
                    for p in command_data.get("complete_path", [])
                ]
                converted_commands.append(CommandResponse(**command_data))

            strategy_eval = self.decision_manager.get_last_strategy_evaluation()
            selected_strategy = strategy_eval.get("selected_strategy", request.strategy)
            selection_reason = strategy_eval.get("selection_reason", "manual_strategy")

            return SchedulingResultResponse(
                selected_strategy=selected_strategy,
                selection_reason=selection_reason,
                strategy_scores={},  # 不再返回详细策略分数
                commands=converted_commands
            )

        @self.router.post("/scheduling/static")
        async def execute_static_planning():
            plan = self.decision_manager.static_planning()
            if plan:
                return {"success": True, "plan": plan.to_dict()}
            else:
                return {"success": False, "message": "No plan generated"}

        @self.router.post("/vehicles/{vehicle_id}/charge")
        async def charge_vehicle(vehicle_id: int):
            vehicle = self.data_manager.get_vehicle(vehicle_id)
            if not vehicle:
                raise HTTPException(status_code=404, detail="Vehicle not found")

            command = self.decision_manager.manage_battery(vehicle)
            if command:
                await self.websocket_handler.broadcast_command(command)
                return {"success": True, "command": command}
            else:
                return {"success": False, "message": "No charging needed"}

        @self.router.get("/strategies")
        async def get_available_strategies():
            return {
                "strategies": ["shortest_task_first", "heaviest_task_first", "auto"],
                "current_strategy": self.decision_manager.last_selected_strategy
            }

        @self.router.get("/commands")
        async def get_active_commands():
            commands = self.decision_manager._dynamic_scheduling.get_active_commands()
            return {"commands": commands}

        # 中央仓库管理接口
        @self.router.get("/warehouse/position", response_model=WarehousePositionModel)
        async def get_warehouse_position():
            pos = self.data_manager.get_warehouse_position()
            return WarehousePositionModel(x=pos.x, y=pos.y)

        @self.router.post("/warehouse/position")
        async def set_warehouse_position(request: WarehousePositionModel):
            self.data_manager.set_warehouse_position(Position(x=request.x, y=request.y))
            await self.websocket_handler.broadcast_warehouse_position_update(request)
            return {"success": True, "position": {"x": request.x, "y": request.y}}

        # 完整路径规划接口
        @self.router.post("/paths/complete", response_model=CompletePathResponse)
        async def calculate_complete_path(request: CompletePathRequest):
            result = self.data_manager.calculate_complete_path(request.task_id, request.vehicle_id)
            if not result:
                raise HTTPException(status_code=404, detail="Task or vehicle not found")
            
            # 广播完整路径更新
            await self.websocket_handler.broadcast_complete_path_update(result)
            
            return CompletePathResponse(
                task_id=result["task_id"],
                vehicle_id=result["vehicle_id"],
                complete_path=[PositionModel(x=p[0], y=p[1]) for p in result["complete_path"]],
                total_distance=result["total_distance"],
                energy_consumption=result["energy_consumption"],
                is_feasible=result["is_feasible"],
                estimated_completion_time=result["estimated_completion_time"]
            )

        @self.router.post("/paths/complete/batch")
        async def calculate_batch_complete_paths(request: BatchCompletePathRequest):
            results = []
            for pair in request.task_vehicle_pairs:
                result = self.data_manager.calculate_complete_path(pair["task_id"], pair["vehicle_id"])
                if result:
                    await self.websocket_handler.broadcast_complete_path_update(result)
                    results.append(CompletePathResponse(
                        task_id=result["task_id"],
                        vehicle_id=result["vehicle_id"],
                        complete_path=[PositionModel(x=p[0], y=p[1]) for p in result["complete_path"]],
                        total_distance=result["total_distance"],
                        energy_consumption=result["energy_consumption"],
                        is_feasible=result["is_feasible"],
                        estimated_completion_time=result["estimated_completion_time"]
                    ))
            return results

        # 任务完成接口
        @self.router.get("/tasks/{task_id}/completion", response_model=TaskCompletionInfo)
        async def get_task_completion_info(task_id: int):
            task = self.data_manager.get_task(task_id)
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")
            
            return TaskCompletionInfo(
                task_id=task.id,
                completion_time=task.complete_time or 0,
                score=task.score,
                is_on_time=task.is_on_time,
                total_distance=task.complete_path_distance
            )

        @self.router.get("/tasks/completed")
        async def get_all_completed_tasks_info():
            from backend.data.task import TaskStatus
            completed_tasks = [task for task in self.data_manager.get_tasks() 
                             if task.status == TaskStatus.COMPLETED]
            
            return [
                TaskCompletionInfo(
                    task_id=task.id,
                    completion_time=task.complete_time or 0,
                    score=task.score,
                    is_on_time=task.is_on_time,
                    total_distance=task.complete_path_distance
                )
                for task in completed_tasks
            ]

        # 任务完成检查接口
        @self.router.post("/vehicles/{vehicle_id}/check-completion")
        async def check_and_complete_tasks(vehicle_id: int):
            completed_tasks = self.data_manager.check_and_complete_task(vehicle_id)
            
            # 广播任务完成事件
            for task in completed_tasks:
                await self.websocket_handler.broadcast_task_completed(task)
            
            # 广播车辆返回仓库事件
            vehicle = self.data_manager.get_vehicle(vehicle_id)
            if vehicle and self.data_manager.is_at_warehouse(vehicle.position):
                await self.websocket_handler.broadcast_vehicle_returned_to_warehouse(vehicle)
            
            return {
                "completed_tasks": [task.id for task in completed_tasks],
                "count": len(completed_tasks)
            }

        # 模拟速度控制接口
        @self.router.get("/simulation/speed")
        async def get_simulation_speed():
            """获取当前模拟速度"""
            from backend.main import SIM_SPEED_FACTOR
            return {
                "speed_factor": int(SIM_SPEED_FACTOR),
                "message": f"当前模拟速度: 1现实秒 = {int(SIM_SPEED_FACTOR)}仿真秒"
            }

        @self.router.post("/simulation/speed")
        async def set_simulation_speed(request: SimulationSpeedRequest):
            """设置模拟速度（需要重启后端才能生效）"""
            return {
                "speed_factor": request.speed_factor,
                "message": f"速度设置已保存: {request.speed_factor}。请重启后端服务使新速度生效。"
            }

    def get_router(self):
        return self.router
