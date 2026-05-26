"""FastAPI 路由。这里只做"HTTP <-> 内部对象"的转换，不含业务逻辑。"""

import random
from datetime import datetime
from typing import List

from fastapi import APIRouter, HTTPException

from backend.data.data_manager import DataManager
from backend.data.charging_station import ChargingStation
from backend.data.position import Position
from backend.data.task import Task
from backend.data.vehicle import Vehicle, VehicleStatus
from backend.decision.decision_manager import DecisionManager
from backend.interface.data_transformer import DataTransformer
from backend.interface.schemas import (
    ChargingStationModel,
    CommandResponse,
    CreateChargingStationRequest,
    CreateTaskRequest,
    CreateVehicleRequest,
    PerformanceMetricsResponse,
    PositionModel,
    SchedulingRequest,
    SchedulingResultResponse,
    SimulationSpeedRequest,
    SimulationStateResponse,
    SystemStatusResponse,
    TaskModel,
    UpdateVehicleRequest,
    VehicleModel,
    WarehousePositionModel,
)
from backend.interface.websocket_handler import WebSocketHandler


class APIController:
    def __init__(
        self,
        data_manager: DataManager,
        decision_manager: DecisionManager,
        websocket_handler: WebSocketHandler,
    ):
        self.data_manager = data_manager
        self.decision_manager = decision_manager
        self.websocket_handler = websocket_handler
        self.router = APIRouter()
        self._setup_routes()

    # ------------------------------------------------------------------
    def _setup_routes(self):
        # ------------------------- tasks -------------------------
        @self.router.get("/tasks", response_model=List[TaskModel])
        async def get_tasks():
            return [DataTransformer.task_to_model(t) for t in self.data_manager.get_visible_tasks()]

        @self.router.get("/tasks/{task_id}", response_model=TaskModel)
        async def get_task(task_id: int):
            task = self.data_manager.get_task(task_id)
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")
            return DataTransformer.task_to_model(task)

        @self.router.post("/tasks", response_model=TaskModel)
        async def create_task(request: CreateTaskRequest):
            task_id = int(datetime.now().timestamp() * 1000) + random.randint(0, 1000)
            task = Task(
                id=task_id,
                position=Position(x=request.position.x, y=request.position.y),
                weight=request.weight,
                create_time=int(datetime.now().timestamp()),
                deadline=request.deadline,
                priority=request.priority,
            )
            self.data_manager.add_task(task)
            await self.websocket_handler.broadcast_task_update(task)
            return DataTransformer.task_to_model(task)

        # ------------------------- vehicles -------------------------
        @self.router.get("/vehicles", response_model=List[VehicleModel])
        async def get_vehicles():
            return [DataTransformer.vehicle_to_model(v) for v in self.data_manager.get_vehicles()]

        @self.router.get("/vehicles/{vehicle_id}", response_model=VehicleModel)
        async def get_vehicle(vehicle_id: int):
            vehicle = self.data_manager.get_vehicle(vehicle_id)
            if not vehicle:
                raise HTTPException(status_code=404, detail="Vehicle not found")
            return DataTransformer.vehicle_to_model(vehicle)

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
                unit_energy_consumption=request.unit_energy_consumption,
            )
            self.data_manager.add_vehicle(vehicle)
            await self.websocket_handler.broadcast_vehicle_update(vehicle)
            return DataTransformer.vehicle_to_model(vehicle)

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
            return DataTransformer.vehicle_to_model(vehicle)

        # ------------------------- stations -------------------------
        @self.router.get("/stations", response_model=List[ChargingStationModel])
        async def get_charging_stations():
            return [
                DataTransformer.charging_station_to_model(s)
                for s in self.data_manager.get_charging_stations()
            ]

        @self.router.get("/stations/{station_id}", response_model=ChargingStationModel)
        async def get_charging_station(station_id: str):
            station = self.data_manager.get_charging_station(station_id)
            if not station:
                raise HTTPException(status_code=404, detail="Charging station not found")
            return DataTransformer.charging_station_to_model(station)

        @self.router.post("/stations", response_model=ChargingStationModel)
        async def create_charging_station(request: CreateChargingStationRequest):
            station = ChargingStation(
                id=request.id,
                position=Position(x=request.position.x, y=request.position.y),
                capacity=request.capacity,
                queue_count=0,
                charging_vehicles=[],
                load_pressure=0.0,
                charging_rate=request.charging_rate,
            )
            self.data_manager.add_charging_station(station)
            await self.websocket_handler.broadcast_station_update(station)
            return DataTransformer.charging_station_to_model(station)

        # ------------------------- map / system -------------------------
        @self.router.get("/map")
        async def get_map_data():
            return self.data_manager.get_map_data()

        @self.router.get("/system/status", response_model=SystemStatusResponse)
        async def get_system_status():
            return SystemStatusResponse(**self.decision_manager.get_system_status())

        @self.router.get("/system/performance", response_model=PerformanceMetricsResponse)
        async def get_performance_metrics():
            return PerformanceMetricsResponse(**self.decision_manager.evaluate_system_performance())

        @self.router.get("/system/state", response_model=SimulationStateResponse)
        async def get_simulation_state():
            state = self.data_manager.get_system_state()
            wh = state["warehouse_position"]
            return SimulationStateResponse(
                timestamp=state["timestamp"],
                warehouse_position=PositionModel(
                    x=wh["x"], y=wh["y"],
                    gcj_lng=wh.get("gcj_lng"), gcj_lat=wh.get("gcj_lat"),
                ),
                vehicles=[
                    DataTransformer.vehicle_to_model(v)
                    for v in self.data_manager.get_vehicles()
                ],
                tasks=[
                    DataTransformer.task_to_model(t)
                    for t in self.data_manager.get_visible_tasks()
                ],
                charging_stations=[
                    DataTransformer.charging_station_to_model(s)
                    for s in self.data_manager.get_charging_stations()
                ],
                total_score=state["total_score"],
                map_nodes=state["map_nodes"],
                map_edges=state["map_edges"],
            )

        # ------------------------- 调度 -------------------------
        @self.router.post("/scheduling", response_model=SchedulingResultResponse)
        async def schedule_tasks(request: SchedulingRequest):
            commands = self.decision_manager.dynamic_scheduling(strategy=request.strategy)

            for command in commands:
                await self.websocket_handler.broadcast_command(command)

            responses: List[CommandResponse] = []
            for cmd in commands:
                target_model = None
                if cmd.get("target_xy"):
                    target_model = PositionModel(
                        x=cmd["target_xy"]["x"], y=cmd["target_xy"]["y"]
                    )
                responses.append(CommandResponse(
                    vehicle_id=cmd["vehicle_id"],
                    action=cmd["action"],
                    target=target_model,
                    assigned_tasks=cmd.get("assigned_tasks", []),
                    task_id=cmd.get("task_id"),
                    station_id=cmd.get("station_id"),
                ))

            return SchedulingResultResponse(
                strategy=self.decision_manager.last_selected_strategy,
                commands=responses,
            )

        @self.router.get("/strategies")
        async def get_available_strategies():
            return {
                "strategies": self.decision_manager.algorithm_manager.get_available_strategies(),
                "current_strategy": self.decision_manager.last_selected_strategy,
            }

        @self.router.get("/commands")
        async def get_active_commands():
            return {"commands": self.decision_manager._dynamic_scheduling.get_last_commands()}

        # ------------------------- warehouse -------------------------
        @self.router.get("/warehouse/position", response_model=WarehousePositionModel)
        async def get_warehouse_position():
            pos = self.data_manager.get_warehouse_position()
            return WarehousePositionModel(x=pos.x, y=pos.y)

        @self.router.post("/warehouse/position")
        async def set_warehouse_position(request: WarehousePositionModel):
            self.data_manager.set_warehouse_position(
                Position(x=request.x, y=request.y)
            )
            await self.websocket_handler.broadcast_warehouse_position_update(request)
            return {"success": True, "position": {"x": request.x, "y": request.y}}

        # ------------------------- simulation speed -------------------------
        @self.router.get("/simulation/speed")
        async def get_simulation_speed():
            from backend.main import SIM_SPEED_FACTOR
            return {
                "speed_factor": int(SIM_SPEED_FACTOR),
                "message": f"当前模拟速度: 1 现实秒 = {int(SIM_SPEED_FACTOR)} 仿真秒",
            }

        @self.router.post("/simulation/speed")
        async def set_simulation_speed(request: SimulationSpeedRequest):
            return {
                "speed_factor": request.speed_factor,
                "message": f"已保存: {request.speed_factor}（需重启后端生效）",
            }

    def get_router(self):
        return self.router
