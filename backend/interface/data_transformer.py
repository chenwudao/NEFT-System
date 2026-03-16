from typing import Dict, List, Any, Optional
from datetime import datetime
from backend.data.data_manager import DataManager
from backend.data.task import Task, TaskStatus, Position
from backend.data.vehicle import Vehicle, VehicleStatus
from backend.data.charging_station import ChargingStation
from backend.decision.decision_manager import DecisionManager
from .schemas import (
    PositionModel, TaskModel, VehicleModel, ChargingStationModel,
    CreateTaskRequest, CreateVehicleRequest, CreateChargingStationRequest,
    UpdateVehicleRequest, SchedulingRequest,
    SystemStatusResponse, PerformanceMetricsResponse,
    SimulationStateResponse, CommandResponse
)

class DataTransformer:
    @staticmethod
    def task_to_dict(task: Task) -> Dict:
        return task.to_dict()

    @staticmethod
    def dict_to_task(data: Dict) -> Task:
        return Task(
            id=data["id"],
            position=Position(x=data["position"]["x"], y=data["position"]["y"]),
            weight=data["weight"],
            create_time=data["create_time"],
            deadline=data["deadline"],
            priority=data["priority"],
            status=TaskStatus(data.get("status", "pending")),
            assigned_vehicle_id=data.get("assigned_vehicle_id"),
            start_time=data.get("start_time"),
            complete_time=data.get("complete_time")
        )

    @staticmethod
    def vehicle_to_dict(vehicle: Vehicle) -> Dict:
        return vehicle.to_dict()

    @staticmethod
    def dict_to_vehicle(data: Dict) -> Vehicle:
        return Vehicle(
            id=data["id"],
            position=Position(x=data["position"]["x"], y=data["position"]["y"]),
            battery=data["battery"],
            max_battery=data["max_battery"],
            current_load=data["current_load"],
            max_load=data["max_load"],
            unit_energy_consumption=data["unit_energy_consumption"],
            status=VehicleStatus(data.get("status", "idle"))
        )

    @staticmethod
    def charging_station_to_dict(station: ChargingStation) -> Dict:
        return station.to_dict()

    @staticmethod
    def dict_to_charging_station(data: Dict) -> ChargingStation:
        return ChargingStation(
            id=data["id"],
            position=Position(x=data["position"]["x"], y=data["position"]["y"]),
            capacity=data["capacity"],
            queue_count=data.get("queue_count", 0),
            charging_vehicles=data.get("charging_vehicles", []),
            load_pressure=data.get("load_pressure", 0.0),
            charging_rate=data["charging_rate"]
        )

    @staticmethod
    def validate_data(data: Dict, required_fields: List[str]) -> bool:
        return all(field in data for field in required_fields)

    @staticmethod
    def task_to_model(task: Task) -> TaskModel:
        return TaskModel(
            id=task.id,
            position=PositionModel(x=task.position.x, y=task.position.y),
            weight=task.weight,
            create_time=task.create_time,
            deadline=task.deadline,
            priority=task.priority,
            status=task.status.value,
            assigned_vehicle_id=task.assigned_vehicle_id,
            start_time=task.start_time,
            complete_time=task.complete_time,
            complete_path=[PositionModel(x=p.x, y=p.y) for p in task.complete_path],
            complete_path_distance=task.complete_path_distance,
            estimated_completion_time=task.estimated_completion_time,
            score=task.score,
            is_on_time=task.is_on_time
        )

    @staticmethod
    def vehicle_to_model(vehicle: Vehicle) -> VehicleModel:
        return VehicleModel(
            id=vehicle.id,
            position=PositionModel(x=vehicle.position.x, y=vehicle.position.y),
            battery=vehicle.battery,
            max_battery=vehicle.max_battery,
            battery_percentage=vehicle.get_battery_percentage(),
            current_load=vehicle.current_load,
            max_load=vehicle.max_load,
            load_percentage=vehicle.get_load_percentage(),
            unit_energy_consumption=vehicle.unit_energy_consumption,
            speed=vehicle.speed,
            status=vehicle.status.value,
            assigned_task_ids=vehicle.assigned_task_ids,
            current_path=vehicle.current_path,
            charging_station_id=vehicle.charging_station_id,
            complete_path=vehicle.complete_path,
            path_progress=vehicle.path_progress,
            energy_consumption=vehicle.energy_consumption,
            total_distance_traveled=vehicle.total_distance_traveled
        )

    @staticmethod
    def charging_station_to_model(station: ChargingStation) -> ChargingStationModel:
        return ChargingStationModel(
            id=station.id,
            position=PositionModel(x=station.position.x, y=station.position.y),
            capacity=station.capacity,
            queue_count=station.queue_count,
            charging_vehicles=station.charging_vehicles,
            load_pressure=station.load_pressure,
            charging_rate=station.charging_rate,
            available_capacity=station.get_available_capacity()
        )
