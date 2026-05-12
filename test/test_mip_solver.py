"""
MIP 求解器增强约束测试集。
覆盖电量、载重与单任务约束。
"""
import pytest
import time
import networkx as nx
from backend.algorithm.mip_solver import MIPSolver
from backend.data.data_manager import DataManager
from backend.data.task import Task, TaskStatus
from backend.data.vehicle import Vehicle, VehicleStatus
from backend.data.charging_station import ChargingStation
from backend.data.position import Position


@pytest.fixture
def mip_solver():
    dm = DataManager()
    graph = nx.Graph()
    graph.graph["crs"] = "EPSG:3857"
    node_points = {
        1: (0.0, 0.0),
        2: (50.0, 50.0),
        3: (100.0, 100.0),
        4: (150.0, 50.0),
        5: (200.0, 100.0),
        6: (100.0, 200.0),
        7: (50.0, 150.0),
        8: (200.0, 200.0),
        9: (75.0, 75.0),
        10: (125.0, 125.0),
        11: (175.0, 175.0),
        12: (500.0, 500.0),
        13: (1000.0, 1000.0),
    }
    for node_id, (x, y) in node_points.items():
        graph.add_node(node_id, x=x, y=y)
    node_ids = list(node_points.keys())
    for i, u in enumerate(node_ids):
        ux, uy = node_points[u]
        for v in node_ids[i + 1:]:
            vx, vy = node_points[v]
            length = abs(ux - vx) + abs(uy - vy)
            graph.add_edge(u, v, length=length)
    dm.path_calculator.set_networkx_graph(graph)
    return MIPSolver(dm.path_calculator)


@pytest.fixture
def warehouse_position():
    return (0, 0)


@pytest.fixture
def simple_tasks():
    """创建简单测试任务。"""
    return [
        Task(
            id=1,
            position=Position(x=50, y=50),
            weight=20.0,
            create_time=int(time.time()),
            deadline=int(time.time()) + 3600,
            priority=1,
            status=TaskStatus.PENDING
        ),
        Task(
            id=2,
            position=Position(x=100, y=100),
            weight=30.0,
            create_time=int(time.time()),
            deadline=int(time.time()) + 3600,
            priority=2,
            status=TaskStatus.PENDING
        ),
    ]


@pytest.fixture
def simple_vehicles():
    """创建电量充足的简单测试车辆。"""
    return [
        Vehicle(
            id=1,
            position=Position(x=0, y=0),
            battery=100.0,
            max_battery=100.0,
            current_load=0.0,
            max_load=100.0,
            unit_energy_consumption=0.1,
            status=VehicleStatus.IDLE
        ),
        Vehicle(
            id=2,
            position=Position(x=0, y=0),
            battery=100.0,
            max_battery=100.0,
            current_load=0.0,
            max_load=100.0,
            unit_energy_consumption=0.1,
            status=VehicleStatus.IDLE
        ),
    ]


@pytest.fixture
def large_scenario_tasks():
    """为较真实场景创建 10 个测试任务。"""
    tasks = []
    positions = [
        (50, 50), (100, 100), (150, 50), (200, 100), (100, 200),
        (50, 150), (200, 200), (75, 75), (125, 125), (175, 175)
    ]
    for i, (x, y) in enumerate(positions, 1):
        tasks.append(Task(
            id=i,
            position=Position(x=x, y=y),
            weight=20.0 + i * 2,  # 不同任务重量
            create_time=int(time.time()),
            deadline=int(time.time()) + 3600,
            priority=(i % 5) + 1,  # 不同任务优先级
            status=TaskStatus.PENDING
        ))
    return tasks


@pytest.fixture
def large_scenario_vehicles():
    """为大规模场景创建 3 辆车辆。"""
    return [
        Vehicle(
            id=1,
            position=Position(x=0, y=0),
            battery=200.0,
            max_battery=200.0,
            current_load=0.0,
            max_load=150.0,
            unit_energy_consumption=0.1,
            status=VehicleStatus.IDLE
        ),
        Vehicle(
            id=2,
            position=Position(x=0, y=0),
            battery=200.0,
            max_battery=200.0,
            current_load=0.0,
            max_load=150.0,
            unit_energy_consumption=0.1,
            status=VehicleStatus.IDLE
        ),
        Vehicle(
            id=3,
            position=Position(x=0, y=0),
            battery=200.0,
            max_battery=200.0,
            current_load=0.0,
            max_load=150.0,
            unit_energy_consumption=0.1,
            status=VehicleStatus.IDLE
        ),
    ]


class TestMIPSolverFallback:
    """测试无 Gurobi 时的后备求解器。"""

    def test_fallback_basic_assignment(self, mip_solver, simple_tasks, simple_vehicles, warehouse_position):
        """测试后备求解器的基础任务分配。"""
        solution = mip_solver._fallback_solve(simple_tasks, simple_vehicles, [], warehouse_position)
        
        assert solution is not None
        assert solution.vehicle_assignments is not None
        # 至少应分配一个任务
        total_assigned = sum(len(tasks) for tasks in solution.vehicle_assignments.values())
        assert total_assigned >= 1

    def test_fallback_capacity_constraint(self, mip_solver, warehouse_position):
        """测试后备求解器遵守载重约束。"""
        # 构造总重量超过单车容量的任务
        tasks = [
            Task(id=i, position=Position(x=50, y=50), weight=60.0,
                 create_time=int(time.time()), deadline=int(time.time()) + 3600,
                 priority=1, status=TaskStatus.PENDING)
            for i in range(1, 4)
        ]
        
        # 容量受限车辆
        vehicles = [
            Vehicle(id=1, position=Position(x=0, y=0), battery=100.0, max_battery=100.0,
                   current_load=0.0, max_load=100.0, unit_energy_consumption=0.1,
                   status=VehicleStatus.IDLE)
        ]
        
        solution = mip_solver._fallback_solve(tasks, vehicles, [], warehouse_position)
        
        # 车辆 1 的分配总载重不应超过 100
        if 1 in solution.vehicle_assignments:
            total_weight = sum(t.weight for t in tasks if t.id in solution.vehicle_assignments[1])
            assert total_weight <= 100.0

    def test_fallback_battery_constraint(self, mip_solver, warehouse_position):
        """测试后备求解器遵守电量约束。"""
        # 构造远距离高能耗任务
        tasks = [
            Task(id=1, position=Position(x=500, y=500), weight=10.0,
                 create_time=int(time.time()), deadline=int(time.time()) + 3600,
                 priority=1, status=TaskStatus.PENDING)
        ]
        
        # 低电量车辆无法完成该任务（距离约 707，需能耗约 141.4）
        vehicles = [
            Vehicle(id=1, position=Position(x=0, y=0), battery=50.0, max_battery=50.0,
                   current_load=0.0, max_load=100.0, unit_energy_consumption=0.1,
                   status=VehicleStatus.IDLE)
        ]
        
        solution = mip_solver._fallback_solve(tasks, vehicles, [], warehouse_position)
        
        # 电量不足时任务不应被分配
        total_assigned = sum(len(tasks) for tasks in solution.vehicle_assignments.values())
        assert total_assigned == 0

    def test_fallback_single_task_per_vehicle(self, mip_solver, simple_tasks, simple_vehicles, warehouse_position):
        """测试每辆车最多分配一个任务。"""
        solution = mip_solver._fallback_solve(simple_tasks, simple_vehicles, [], warehouse_position)
        
        # 每辆车最多 1 个任务（简化单任务模型）
        for vehicle_id, assigned_tasks in solution.vehicle_assignments.items():
            assert len(assigned_tasks) <= 1, f"Vehicle {vehicle_id} assigned {len(assigned_tasks)} tasks"

    def test_fallback_large_scenario(self, mip_solver, large_scenario_tasks, large_scenario_vehicles, warehouse_position):
        """测试后备求解器在 10 任务 3 车辆场景下的行为。"""
        solution = mip_solver._fallback_solve(large_scenario_tasks, large_scenario_vehicles, [], warehouse_position)
        
        assert solution is not None
        assert solution.vehicle_assignments is not None
        
        # 检查解是否可行
        total_assigned = sum(len(tasks) for tasks in solution.vehicle_assignments.values())
        assert total_assigned > 0, "No tasks assigned in large scenario"
        
        # 验证每辆车最多 1 个任务
        for vehicle_id, assigned_tasks in solution.vehicle_assignments.items():
            assert len(assigned_tasks) <= 1
        
        # 验证总距离已计算
        assert solution.total_distance > 0


class TestMIPSolverWithGurobi:
    """测试 Gurobi 求解器（可用时）。"""

    @pytest.mark.skip(reason="Gurobi might not be installed")
    def test_gurobi_basic_assignment(self, mip_solver, simple_tasks, simple_vehicles, warehouse_position):
        """测试 Gurobi 在简单场景下的分配。"""
        solution = mip_solver.solve_with_gurobi(simple_tasks, simple_vehicles, [], warehouse_position)
        
        if solution is not None:
            assert solution.vehicle_assignments is not None
            total_assigned = sum(len(tasks) for tasks in solution.vehicle_assignments.values())
            assert total_assigned >= 1

    @pytest.mark.skip(reason="Gurobi might not be installed")
    def test_gurobi_large_scenario(self, mip_solver, large_scenario_tasks, large_scenario_vehicles, warehouse_position):
        """测试 Gurobi 在 10 任务 3 车辆场景下的行为。"""
        solution = mip_solver.solve_with_gurobi(large_scenario_tasks, large_scenario_vehicles, [], warehouse_position)
        
        if solution is not None:
            assert solution.vehicle_assignments is not None
            total_assigned = sum(len(tasks) for tasks in solution.vehicle_assignments.values())
            assert total_assigned > 0
            
            # 验证解质量
            assert solution.total_distance > 0
            # 至少应分配 30% 的任务
            assert total_assigned >= len(large_scenario_tasks) * 0.3


class TestMIPSolverConstraints:
    """测试约束有效性。"""

    def test_no_impossible_assignments(self, mip_solver, warehouse_position):
        """验证求解器会拒绝不可能分配（低电量 + 远任务）。"""
        # 远距离任务
        tasks = [
            Task(id=1, position=Position(x=1000, y=1000), weight=5.0,
                 create_time=int(time.time()), deadline=int(time.time()) + 3600,
                 priority=1, status=TaskStatus.PENDING)
        ]
        
        # 电量不足车辆
        vehicles = [
            Vehicle(id=1, position=Position(x=0, y=0), battery=50.0, max_battery=50.0,
                   current_load=0.0, max_load=100.0, unit_energy_consumption=0.1,
                   status=VehicleStatus.IDLE)
        ]
        
        solution = mip_solver._fallback_solve(tasks, vehicles, [], warehouse_position)
        assert sum(len(tasks) for tasks in solution.vehicle_assignments.values()) == 0

    def test_feasible_assignment_detection(self, mip_solver, warehouse_position):
        """验证求解器可识别并执行可行分配。"""
        # 近距离任务
        tasks = [
            Task(id=1, position=Position(x=50, y=50), weight=20.0,
                 create_time=int(time.time()), deadline=int(time.time()) + 3600,
                 priority=1, status=TaskStatus.PENDING)
        ]
        
        # 资源充足车辆
        vehicles = [
            Vehicle(id=1, position=Position(x=0, y=0), battery=100.0, max_battery=100.0,
                   current_load=0.0, max_load=100.0, unit_energy_consumption=0.1,
                   status=VehicleStatus.IDLE)
        ]
        
        solution = mip_solver._fallback_solve(tasks, vehicles, [], warehouse_position)
        assert sum(len(tasks) for tasks in solution.vehicle_assignments.values()) == 1


class TestMIPSolverObjective:
    """测试目标函数行为。"""

    def test_solution_returns_valid_metrics(self, mip_solver, simple_tasks, simple_vehicles, warehouse_position):
        """验证解中包含全部必要指标。"""
        solution = mip_solver._fallback_solve(simple_tasks, simple_vehicles, [], warehouse_position)
        
        assert hasattr(solution, 'objective_value')
        assert hasattr(solution, 'vehicle_assignments')
        assert hasattr(solution, 'total_distance')
        assert hasattr(solution, 'total_time')
        assert solution.objective_value >= 0
        assert solution.total_distance >= 0
