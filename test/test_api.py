import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.data.data_manager import DataManager
from backend.algorithm.algorithm_manager import AlgorithmManager
from backend.decision.decision_manager import DecisionManager
from backend.interface.api_controller import APIController
from backend.interface.websocket_handler import WebSocketHandler

@pytest.fixture
def client():
    # 手动初始化并注册路由
    data_manager = DataManager()
    algorithm_manager = AlgorithmManager(data_manager.path_calculator)
    decision_manager = DecisionManager(data_manager, algorithm_manager)
    websocket_handler = WebSocketHandler(data_manager, decision_manager)
    api_controller = APIController(data_manager, decision_manager, websocket_handler)
    
    # 注册路由
    app.include_router(api_controller.get_router(), prefix="/api", tags=["API"])
    
    # 将组件注入 APP 状态，以便后端控制器中的 request.app.state 能找到它们
    app.state.data_manager = data_manager
    app.state.algorithm_manager = algorithm_manager
    app.state.decision_manager = decision_manager
    app.state.websocket_handler = websocket_handler
    app.state.simulation_running = False
    app.state.simulation_mode = "realtime"
    
    return TestClient(app)

def test_root(client):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert data["message"] == "NEFT System API"

def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"

def test_get_tasks(client):
    response = client.get("/api/tasks")
    assert response.status_code == 200
    tasks = response.json()
    assert isinstance(tasks, list)

def test_create_task(client):
    task_data = {
        "position": {"x": 100.0, "y": 200.0},
        "weight": 50.0,
        "deadline": 1678892488,
        "priority": 2
    }
    response = client.post("/api/tasks", json=task_data)
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["weight"] == 50.0

def test_get_vehicles(client):
    response = client.get("/api/vehicles")
    assert response.status_code == 200
    vehicles = response.json()
    assert isinstance(vehicles, list)

def test_create_vehicle(client):
    vehicle_data = {
        "position": {"x": 100.0, "y": 100.0},
        "battery": 80.0,
        "max_battery": 100.0,
        "current_load": 0.0,
        "max_load": 100.0,
        "unit_energy_consumption": 0.1
    }
    response = client.post("/api/vehicles", json=vehicle_data)
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["battery"] == 80.0

def test_get_charging_stations(client):
    response = client.get("/api/stations")
    assert response.status_code == 200
    stations = response.json()
    assert isinstance(stations, list)

def test_create_charging_station(client):
    station_data = {
        "id": "cs_test",
        "position": {"x": 200.0, "y": 200.0},
        "capacity": 5,
        "charging_rate": 10.0
    }
    response = client.post("/api/stations", json=station_data)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "cs_test"
    assert data["capacity"] == 5

def test_get_system_status(client):
    response = client.get("/api/system/status")
    assert response.status_code == 200
    data = response.json()
    assert "total_tasks" in data
    assert "total_vehicles" in data
    assert "total_charging_stations" in data
    assert "strategy_scores" in data

def test_get_performance_metrics(client):
    response = client.get("/api/system/performance")
    assert response.status_code == 200
    data = response.json()
    assert "completion_rate" in data
    assert "avg_completion_time" in data
    assert "total_distance" in data

def test_get_simulation_state(client):
    response = client.get("/api/system/state")
    assert response.status_code == 200
    data = response.json()
    assert "timestamp" in data
    assert "warehouse_position" in data
    assert "vehicles" in data
    assert "tasks" in data
    assert "charging_stations" in data

def test_schedule_tasks(client):
    scheduling_data = {
        "strategy": "auto"
    }
    response = client.post("/api/scheduling", json=scheduling_data)
    assert response.status_code == 200
    data = response.json()
    assert "commands" in data
    assert "selected_strategy" in data
    assert "strategy_scores" in data
    assert isinstance(data["commands"], list)


def test_simulation_control_endpoints(client):
    cfg = client.post("/api/simulation/config", json={"mode": "realtime", "scale": "small"})
    assert cfg.status_code == 200
    assert cfg.json()["success"] is True

    start = client.post("/api/simulation/start", json={"mode": "realtime", "scale": "small"})
    assert start.status_code == 200
    assert start.json()["running"] is True

    status = client.get("/api/simulation/status")
    assert status.status_code == 200
    assert "mode" in status.json()
    assert "scale" in status.json()

    stop = client.post("/api/simulation/stop")
    assert stop.status_code == 200
    assert stop.json()["running"] is False

def test_get_strategies(client):
    response = client.get("/api/strategies")
    assert response.status_code == 200
    data = response.json()
    assert "strategies" in data
    assert "current_strategy" in data
    assert isinstance(data["strategies"], list)

def test_get_active_commands(client):
    response = client.get("/api/commands")
    assert response.status_code == 200
    data = response.json()
    assert "commands" in data
    assert isinstance(data["commands"], list)
