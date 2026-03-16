from typing import Set, Dict, List, Optional
import asyncio
import json
from fastapi import WebSocket, WebSocketDisconnect
from datetime import datetime
from backend.data.data_manager import DataManager
from backend.data.task import Task
from backend.data.vehicle import Vehicle
from backend.data.charging_station import ChargingStation
from backend.decision.decision_manager import DecisionManager

class WebSocketHandler:
    def __init__(self, data_manager: DataManager, decision_manager: DecisionManager):
        self.data_manager = data_manager
        self.decision_manager = decision_manager
        self.active_connections: Set[WebSocket] = set()
        self.subscribed_events: Dict[WebSocket, List[str]] = {}

    async def connect(self, websocket: WebSocket):
        self.active_connections.add(websocket)
        self.subscribed_events[websocket] = ["all"]

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if websocket in self.subscribed_events:
            del self.subscribed_events[websocket]

    async def subscribe(self, websocket: WebSocket, events: List[str]):
        if websocket in self.subscribed_events:
            self.subscribed_events[websocket] = events

    async def broadcast_state(self):
        state = self.data_manager.get_system_state()
        message = {
            "type": "state_update",
            "data": state,
            "timestamp": int(datetime.now().timestamp())
        }

        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                print(f"Error broadcasting to connection: {e}")
                disconnected.append(connection)

        for connection in disconnected:
            self.disconnect(connection)

    async def broadcast_task_update(self, task: Task):
        message = {
            "type": "task_update",
            "data": task.to_dict(),
            "timestamp": int(datetime.now().timestamp())
        }

        await self._broadcast_to_subscribers(message, ["task_update", "all"])

    async def broadcast_vehicle_update(self, vehicle: Vehicle):
        message = {
            "type": "vehicle_update",
            "data": vehicle.to_dict(),
            "timestamp": int(datetime.now().timestamp())
        }

        await self._broadcast_to_subscribers(message, ["vehicle_update", "all"])

    async def broadcast_station_update(self, station: ChargingStation):
        message = {
            "type": "station_update",
            "data": station.to_dict(),
            "timestamp": int(datetime.now().timestamp())
        }

        await self._broadcast_to_subscribers(message, ["station_update", "all"])

    async def broadcast_command(self, command: Dict):
        message = {
            "type": "command_update",
            "data": command,
            "timestamp": int(datetime.now().timestamp())
        }

        await self._broadcast_to_subscribers(message, ["command_update", "all"])

    async def broadcast_system_status(self):
        status = self.decision_manager.get_system_status()
        message = {
            "type": "system_status",
            "data": status,
            "timestamp": int(datetime.now().timestamp())
        }

        await self._broadcast_to_subscribers(message, ["system_status", "all"])

    async def broadcast_performance_metrics(self):
        metrics = self.decision_manager.evaluate_system_performance()
        message = {
            "type": "performance_metrics",
            "data": metrics,
            "timestamp": int(datetime.now().timestamp())
        }

        await self._broadcast_to_subscribers(message, ["performance_metrics", "all"])

    async def broadcast_warehouse_position_update(self, position):
        """广播中央仓库位置更新"""
        message = {
            "type": "warehouse_position_update",
            "data": {"x": position.x, "y": position.y},
            "timestamp": int(datetime.now().timestamp())
        }
        await self._broadcast_to_subscribers(message, ["warehouse_update", "all"])

    async def broadcast_complete_path_update(self, path_info: Dict):
        """广播完整路径更新"""
        message = {
            "type": "complete_path_update",
            "data": {
                "task_id": path_info["task_id"],
                "vehicle_id": path_info["vehicle_id"],
                "complete_path": path_info["complete_path"],
                "total_distance": path_info["total_distance"],
                "energy_consumption": path_info["energy_consumption"],
                "is_feasible": path_info["is_feasible"],
                "estimated_completion_time": path_info["estimated_completion_time"]
            },
            "timestamp": int(datetime.now().timestamp())
        }
        await self._broadcast_to_subscribers(message, ["path_update", "all"])

    async def broadcast_task_completed(self, task: Task):
        """广播任务完成事件"""
        message = {
            "type": "task_completed",
            "data": {
                "task_id": task.id,
                "completion_time": task.complete_time,
                "score": task.score,
                "is_on_time": task.is_on_time,
                "total_distance": task.complete_path_distance
            },
            "timestamp": int(datetime.now().timestamp())
        }
        await self._broadcast_to_subscribers(message, ["task_completed", "all"])

    async def broadcast_vehicle_returned_to_warehouse(self, vehicle: Vehicle):
        """广播车辆返回仓库事件"""
        message = {
            "type": "vehicle_returned_to_warehouse",
            "data": {
                "vehicle_id": vehicle.id,
                "position": {"x": vehicle.position.x, "y": vehicle.position.y},
                "total_distance_traveled": vehicle.total_distance_traveled,
                "energy_consumption": vehicle.energy_consumption
            },
            "timestamp": int(datetime.now().timestamp())
        }
        await self._broadcast_to_subscribers(message, ["vehicle_update", "all"])

    async def _broadcast_to_subscribers(self, message: Dict, event_types: List[str]):
        disconnected = []
        for connection in self.active_connections:
            subscribed = self.subscribed_events.get(connection, [])
            if any(event in subscribed for event in event_types):
                try:
                    await connection.send_json(message)
                except Exception as e:
                    print(f"Error broadcasting to connection: {e}")
                    disconnected.append(connection)

        for connection in disconnected:
            self.disconnect(connection)

    def get_connection_count(self) -> int:
        return len(self.active_connections)

    async def handle_message(self, websocket: WebSocket, message: Dict):
        message_type = message.get("type")

        if message_type == "subscribe":
            events = message.get("events", ["all"])
            await self.subscribe(websocket, events)

        elif message_type == "get_state":
            state = self.data_manager.get_system_state()
            await websocket.send_json({
                "type": "state_response",
                "data": state,
                "timestamp": int(datetime.now().timestamp())
            })

        elif message_type == "ping":
            await websocket.send_json({
                "type": "pong",
                "timestamp": int(datetime.now().timestamp())
            })
