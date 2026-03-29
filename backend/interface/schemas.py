from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from datetime import datetime

class PositionModel(BaseModel):
    x: float
    y: float
    gcj_lng: Optional[float] = None
    gcj_lat: Optional[float] = None

class PathPointModel(BaseModel):
    x: float
    y: float
    gcj_lng: Optional[float] = None
    gcj_lat: Optional[float] = None

class TaskModel(BaseModel):
    id: int
    position: PositionModel
    weight: float
    create_time: int
    deadline: int
    priority: int
    status: str
    assigned_vehicle_id: Optional[int] = None
    start_time: Optional[int] = None
    complete_time: Optional[int] = None
    complete_path: List[PositionModel] = []
    complete_path_distance: float = 0.0
    estimated_completion_time: float = 0.0
    score: float = 0.0
    is_on_time: bool = True

class VehicleModel(BaseModel):
    id: int
    position: PositionModel
    battery: float
    max_battery: float
    battery_percentage: float
    current_load: float
    max_load: float
    load_percentage: float
    unit_energy_consumption: float
    speed: float = 0.1
    status: str
    assigned_task_ids: List[int] = []
    current_path: List[PathPointModel] = []
    charging_station_id: Optional[str] = None
    complete_path: List[PathPointModel] = []
    path_progress: float = 0.0
    energy_consumption: float = 0.0
    total_distance_traveled: float = 0.0

class ChargingStationModel(BaseModel):
    id: str
    position: PositionModel
    capacity: int
    queue_count: int
    charging_vehicles: List[int] = []
    load_pressure: float
    charging_rate: float
    available_capacity: int

class CreateTaskRequest(BaseModel):
    position: PositionModel
    weight: float
    deadline: int
    priority: int = 1

class CreateVehicleRequest(BaseModel):
    position: PositionModel
    battery: float
    max_battery: float
    current_load: float
    max_load: float
    unit_energy_consumption: float

class CreateChargingStationRequest(BaseModel):
    id: str
    position: PositionModel
    capacity: int
    charging_rate: float

class UpdateVehicleRequest(BaseModel):
    position: Optional[PositionModel] = None
    battery: Optional[float] = None
    current_load: Optional[float] = None
    status: Optional[str] = None

class SchedulingRequest(BaseModel):
    strategy: str = "auto"
    task_ids: Optional[List[int]] = None

class SystemStatusResponse(BaseModel):
    timestamp: int
    total_tasks: int
    pending_tasks: int
    completed_tasks: int
    timeout_tasks: int
    total_vehicles: int
    idle_vehicles: int
    transporting_vehicles: int
    charging_vehicles: int
    total_charging_stations: int
    active_commands: int
    current_strategy: str
    current_strategy_reason: Optional[str] = None
    strategy_scores: Dict[str, Dict[str, float]] = {}
    completion_rate: float = 0.0
    vehicle_utilization: float = 0.0

class PerformanceMetricsResponse(BaseModel):
    completion_rate: float
    avg_completion_time: float
    total_distance: float
    total_score: float

class SimulationStateResponse(BaseModel):
    timestamp: int
    warehouse_position: PositionModel
    vehicles: List[VehicleModel]
    tasks: List[TaskModel]
    charging_stations: List[ChargingStationModel]
    total_score: float
    map_nodes: List[Dict[str, Any]]
    map_edges: List[List[Any]]

class CommandResponse(BaseModel):
    vehicle_id: int
    action_type: str
    assigned_tasks: List[int]
    path: List[PathPointModel]
    charging_station_id: Optional[str]
    estimated_time: int
    complete_path: List[PathPointModel] = []
    total_distance: float = 0.0
    energy_consumption: float = 0.0


class SchedulingResultResponse(BaseModel):
    selected_strategy: str
    selection_reason: str
    strategy_scores: Dict[str, Dict[str, float]] = {}
    commands: List[CommandResponse] = []

class CompletePathRequest(BaseModel):
    task_id: int
    vehicle_id: int

class CompletePathResponse(BaseModel):
    task_id: int
    vehicle_id: int
    complete_path: List[PositionModel]
    total_distance: float
    energy_consumption: float
    is_feasible: bool
    estimated_completion_time: float

class BatchCompletePathRequest(BaseModel):
    task_vehicle_pairs: List[dict]

class WarehousePositionModel(BaseModel):
    x: float
    y: float

class TaskCompletionInfo(BaseModel):
    task_id: int
    completion_time: int
    score: float
    is_on_time: bool
    total_distance: float

class SimulationSpeedRequest(BaseModel):
    speed_factor: int = Field(..., ge=1, le=600, description="模拟速度倍率：1-600，每现实秒推进的仿真秒数")

class SimulationSpeedResponse(BaseModel):
    speed_factor: int
    message: str
