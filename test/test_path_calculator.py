import pytest
import networkx as nx
from backend.data.data_manager import DataManager
from backend.data.position import Position
from backend.data.task import Task
from backend.data.vehicle import Vehicle
from backend.data.charging_station import ChargingStation
from backend.data.path_calculator import PathCalculator

@pytest.fixture
def path_calculator():
    pc = PathCalculator()
    # 为测试创建一个 3x3 的 Mock 图，避免加载庞大的 OSM 真实地图缓存
    # 每个节点间距 10.0
    G = nx.MultiDiGraph()
    for i in range(3):
        for j in range(3):
            node_id = i * 3 + j
            G.add_node(node_id, x=i * 10.0, y=j * 10.0)
            
    for i in range(3):
        for j in range(3):
            node_id = i * 3 + j
            if i < 2:
                right_node = (i + 1) * 3 + j
                G.add_edge(node_id, right_node, 0, length=10.0)
                G.add_edge(right_node, node_id, 0, length=10.0)
            if j < 2:
                down_node = i * 3 + (j + 1)
                G.add_edge(node_id, down_node, 0, length=10.0)
                G.add_edge(down_node, node_id, 0, length=10.0)
                
    pc.set_networkx_graph(G)
    return pc

@pytest.fixture
def mock_data_manager():
    # 绕过图加载的数据管理器
    class MockDM:
        def add_charging_station(self, st): pass
    return MockDM()

def test_calculate_distance_from_positions(path_calculator):
    # 使用与 Mock 图节点对齐的坐标
    positions = [
        Position(x=0.0, y=0.0),
        Position(x=10.0, y=0.0),  # 向下一步
        Position(x=10.0, y=10.0)  # 向右一步
    ]
    distance = path_calculator.calculate_distance_from_positions(positions)
    assert distance >= 20.0

def test_calculate_energy_consumption(path_calculator):
    vehicle = Vehicle(
        id=1, position=Position(x=0.0, y=0.0),
        battery=100.0, max_battery=100.0,
        current_load=50.0, max_load=100.0,
        unit_energy_consumption=0.3
    )
    positions = [Position(x=0.0, y=0.0), Position(x=10.0, y=0.0)]
    energy = path_calculator.calculate_energy_consumption_from_positions(vehicle, positions)
    assert energy > 0
    assert energy < vehicle.battery

def test_find_nearest_charging_station(path_calculator, mock_data_manager):
    vehicle = Vehicle(
        id=1, position=Position(x=100.0, y=100.0),
        battery=100.0, max_battery=100.0, current_load=0.0,
        max_load=100.0, unit_energy_consumption=0.1
    )
    station1 = ChargingStation(
        id="cs1", position=Position(x=150.0, y=150.0),
        capacity=5, queue_count=0, charging_vehicles=[],
        load_pressure=0.0, charging_rate=10.0
    )
    station2 = ChargingStation(
        id="cs2", position=Position(x=300.0, y=300.0),
        capacity=5, queue_count=0, charging_vehicles=[],
        load_pressure=0.0, charging_rate=10.0
    )
    
    nearest_station_id = path_calculator.find_nearest_charging_station(vehicle, [station1, station2])
    assert nearest_station_id == "cs1"

def test_calculate_path_distance(path_calculator):
    # 0,0 到 10,10 的曼哈顿图距离是 20
    start_pos = Position(x=0.0, y=0.0)
    end_pos = Position(x=10.0, y=10.0)
    distance = path_calculator.calculate_distance([(start_pos.x, start_pos.y), (end_pos.x, end_pos.y)])
    assert distance == 20.0

def test_calculate_complete_path(path_calculator):
    warehouse_pos = Position(x=0.0, y=0.0)
    task_pos = Position(x=10.0, y=10.0)
    
    complete_path, total_distance = path_calculator.calculate_complete_path(warehouse_pos, task_pos)
    assert len(complete_path) >= 3
    assert total_distance == 40.0
    assert complete_path[0] == (0.0, 0.0)
    assert complete_path[-1] == (0.0, 0.0)

def test_calculate_energy_consumption_for_complete_path(path_calculator):
    vehicle = Vehicle(
        id=1, position=Position(x=0.0, y=0.0),
        battery=100.0, max_battery=100.0, current_load=50.0,
        max_load=100.0, unit_energy_consumption=0.1
    )
    complete_path = [(0.0, 0.0), (10.0, 10.0), (0.0, 0.0)]
    total_energy, is_feasible = path_calculator.calculate_energy_consumption_for_complete_path(vehicle, complete_path)
    
    assert total_energy > 0
    assert total_energy >= 40.0 * 0.1
    assert is_feasible == True

def test_calculate_task_completion_time(path_calculator):
    complete_path = [(0.0, 0.0), (10.0, 10.0), (0.0, 0.0)]
    completion_time = path_calculator.calculate_task_completion_time(complete_path)
    assert completion_time > 0

def test_calculate_task_score(path_calculator):
    task = Task(id=1, position=Position(x=3.0, y=4.0), weight=10.0, create_time=1000, deadline=2000, priority=1)
    score = path_calculator.calculate_task_score(task, 1500, 10.0)
    assert score > 100.0
    
    score_late = path_calculator.calculate_task_score(task, 2500, 10.0)
    assert score_late > -50.0
