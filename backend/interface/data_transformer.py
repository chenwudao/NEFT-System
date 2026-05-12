"""Pydantic 模型与内部 dataclass 之间的双向转换。"""

from typing import Any, List, Optional, Sequence

from backend.data.charging_station import ChargingStation
from backend.data.geo_display import wgs84_to_gcj02
from backend.data.position import Position
from backend.data.task import Task
from backend.data.vehicle import Vehicle

from .schemas import (
    ChargingStationModel,
    PathPointModel,
    PositionModel,
    TaskModel,
    VehicleModel,
)


def _position_model(x: float, y: float) -> PositionModel:
    glng, glat = wgs84_to_gcj02(x, y)
    return PositionModel(x=x, y=y, gcj_lng=glng, gcj_lat=glat)


def _path_point_list(points: Sequence[Any]) -> List[PathPointModel]:
    result: List[PathPointModel] = []
    for p in points:
        if isinstance(p, (tuple, list)):
            x, y = float(p[0]), float(p[1])
        elif isinstance(p, dict):
            x, y = float(p["x"]), float(p["y"])
        elif hasattr(p, "x") and hasattr(p, "y"):
            x, y = float(p.x), float(p.y)
        else:
            continue
        glng, glat = wgs84_to_gcj02(x, y)
        result.append(PathPointModel(x=x, y=y, gcj_lng=glng, gcj_lat=glat))
    return result


class DataTransformer:
    """纯静态工具类，不持有状态。"""

    @staticmethod
    def task_to_model(task: Task) -> TaskModel:
        return TaskModel(
            id=task.id,
            position=_position_model(task.position.x, task.position.y),
            weight=task.weight,
            create_time=task.create_time,
            deadline=task.deadline,
            priority=task.priority,
            status=task.status.value,
            assigned_vehicle_id=task.assigned_vehicle_id,
            start_time=task.start_time,
            complete_time=task.complete_time,
            complete_path_distance=task.complete_path_distance,
            score=task.score,
            is_on_time=task.is_on_time,
        )

    @staticmethod
    def vehicle_to_model(vehicle: Vehicle) -> VehicleModel:
        target_model: Optional[PositionModel] = None
        if vehicle.current_target_xy is not None:
            tx, ty = vehicle.current_target_xy
            target_model = _position_model(tx, ty)
        return VehicleModel(
            id=vehicle.id,
            position=_position_model(vehicle.position.x, vehicle.position.y),
            battery=vehicle.battery,
            max_battery=vehicle.max_battery,
            battery_percentage=vehicle.get_battery_percentage(),
            current_load=vehicle.current_load,
            max_load=vehicle.max_load,
            load_percentage=vehicle.get_load_percentage(),
            unit_energy_consumption=vehicle.unit_energy_consumption,
            speed=vehicle.speed,
            vehicle_type=vehicle.vehicle_type,
            status=vehicle.status.value,
            assigned_task_ids=list(vehicle.assigned_task_ids),
            current_target=target_model,
            current_route=_path_point_list(vehicle.current_route),
            charging_station_id=vehicle.charging_station_id,
            path_progress=vehicle.get_path_progress(),
            energy_consumption=vehicle.energy_consumption,
            total_distance_traveled=vehicle.total_distance_traveled,
        )

    @staticmethod
    def charging_station_to_model(station: ChargingStation) -> ChargingStationModel:
        return ChargingStationModel(
            id=station.id,
            position=_position_model(station.position.x, station.position.y),
            capacity=station.capacity,
            queue_count=station.queue_count,
            charging_vehicles=station.charging_vehicles,
            load_pressure=station.load_pressure,
            charging_rate=station.charging_rate,
            available_capacity=station.get_available_slots(),
        )
