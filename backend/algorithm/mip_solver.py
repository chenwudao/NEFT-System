from typing import List, Dict, Optional
from backend.data.task import Task
from backend.data.vehicle import Vehicle
from backend.data.charging_station import ChargingStation
from backend.data.position import Position
from backend.data.path_calculator import PathCalculator
from .solution import Solution

class MIPSolver:
    def __init__(self, path_calculator: Optional[PathCalculator] = None):
        self.model = None
        self.solver = None
        self.path_calculator = path_calculator

    def set_path_calculator(self, path_calculator: PathCalculator):
        self.path_calculator = path_calculator

    def calculate_distance(self, pos1: tuple, pos2: tuple) -> float:
        """计算两点间距离 - 使用图路径距离（基于OSM道路网络）
        
        注意：MIP求解器强制使用图路径距离，确保规划结果符合实际道路情况。
        """
        if self.path_calculator is None:
            raise RuntimeError("PathCalculator is required for graph-based MIP distance.")
        return self.path_calculator.calculate_pair_distance(pos1, pos2)

    def build_model(self, tasks: List[Task], vehicles: List[Vehicle], 
                   charging_stations: List[ChargingStation], 
                   warehouse_position: tuple):
        """构建带增强约束的 MIP 模型。"""
        pass

    def solve(self) -> Solution:
        pass

    def get_objective_value(self) -> float:
        return 0.0

    def _check_gurobi_license(self) -> tuple[bool, str]:
        """检查 Gurobi 许可证状态
        
        Returns:
            (是否受限, 许可证信息)
        """
        try:
            import gurobipy as gp
            from gurobipy import GRB
            
            # 创建一个简单的测试模型
            test_model = gp.Model("license_check")
            test_model.setParam("OutputFlag", 0)
            
            # 添加超过受限版限制的变量（受限版最多2000变量）
            # 我们添加2500个变量来测试
            for i in range(2500):
                test_model.addVar(vtype=GRB.BINARY, name=f"test_var_{i}")
            test_model.update()
            
            try:
                test_model.optimize()
                # 如果能优化成功，说明是完整许可证
                return False, "Full license detected"
            except gp.GurobiError as e:
                if "LIMITS" in str(e) or "restricted" in str(e).lower():
                    return True, f"Restricted license: {e}"
                raise
        except Exception as e:
            return True, f"License check failed: {e}"

    def solve_with_gurobi(self, tasks: List[Task], vehicles: List[Vehicle],
                          charging_stations: List[ChargingStation],
                          warehouse_position: tuple) -> Optional[Solution]:
        """
        使用 Gurobi 求解（增强约束）：
        - 车辆载重约束
        - 电量/能耗约束
        - 任务分配约束（每个任务最多分配给一辆车）
        - 车辆单任务约束（简化为同一时刻最多执行一个任务）
        
        如果检测到受限许可证且问题规模过大，自动返回 None
        """
        try:
            from gurobipy import Model, GRB, quicksum
            import logging

            # 检查许可证
            is_restricted, license_info = self._check_gurobi_license()
            if is_restricted:
                # 受限版限制：2000变量，2000约束
                # 我们的模型：变量数 = 车辆数 × 任务数
                estimated_vars = len(vehicles) * len(tasks)
                if estimated_vars > 1800:  # 留一些余量
                    logging.warning(f"[MIP] {license_info}")
                    logging.warning(f"[MIP] Problem too large for restricted license: {estimated_vars} variables > 1800 limit")
                    return None
                logging.info(f"[MIP] Using restricted license with {estimated_vars} variables")

            model = Model("EVRPTW")
            model.setParam("OutputFlag", 0)  # 关闭求解器输出

            warehouse_pos = warehouse_position if isinstance(warehouse_position, tuple) else \
                           (warehouse_position.x, warehouse_position.y)

            # 决策变量：x[v,t] = 1 表示车辆 v 被分配任务 t
            x = {}
            for v in vehicles:
                for t in tasks:
                    x[v.id, t.id] = model.addVar(vtype=GRB.BINARY, name=f"x_{v.id}_{t.id}")

            # ===== 约束1：任务覆盖约束（每个任务最多分配给一辆车） =====
            for t in tasks:
                model.addConstr(quicksum(x[v.id, t.id] for v in vehicles) <= 1, 
                              name=f"task_coverage_{t.id}")

            # ===== 约束2：车辆载重约束（总重量 <= 最大载重） =====
            for v in vehicles:
                model.addConstr(quicksum(x[v.id, t.id] * t.weight for t in tasks) <= v.max_load, 
                              name=f"capacity_{v.id}")

            # ===== 约束3：车辆单任务约束（每车最多处理一个任务） =====
            for v in vehicles:
                model.addConstr(quicksum(x[v.id, t.id] for t in tasks) <= 1, 
                              name=f"single_task_{v.id}")

            # ===== 约束4：电量/能耗约束 =====
            # 对每个（车辆,任务）分配检查电量是否充足
            # 能耗 = 往返距离 * 单位能耗 <= 电池容量
            for v in vehicles:
                for t in tasks:
                    task_pos = (t.position.x, t.position.y)
                    # 往返路径：仓库 -> 任务点 -> 仓库
                    dist_to_task = self.calculate_distance(warehouse_pos, task_pos)
                    round_trip_distance = 2 * dist_to_task
                    energy_required = round_trip_distance * v.unit_energy_consumption
                    
                    # 若 x[v,t] = 1，则必须满足 energy_required <= battery
                    # 约束形式：energy_required * x[v,t] <= battery * x[v,t]
                    # 可化简为：(energy_required - battery) * x[v,t] <= 0
                    if energy_required > v.max_battery:
                        # 即便满电也无法完成该任务
                        model.addConstr(x[v.id, t.id] == 0, 
                                      name=f"battery_impossible_{v.id}_{t.id}")
                    else:
                        # 添加分配时电量充足约束
                        model.addConstr(energy_required * x[v.id, t.id] <= v.max_battery * x[v.id, t.id],
                                      name=f"battery_{v.id}_{t.id}")

            # ===== 约束5（可选）：时间窗约束 =====
            # 简化起见，这里不强制严格时间窗，
            # 但可在目标函数中对迟到完成进行惩罚

            # ===== 目标：优先最大化完成任务数，其次最小化总距离 =====
            # 目标1：最大化任务完成数
            completed_tasks = quicksum(x[v.id, t.id] for v in vehicles for t in tasks)
            
            # 目标2（加权）：最小化已分配任务的总路程
            total_distance = quicksum(
                x[v.id, t.id] * 2 * self.calculate_distance(warehouse_pos, (t.position.x, t.position.y))
                for v in vehicles for t in tasks
            )
            
            # 组合目标：先保完成数，再降距离
            model.setObjective(1000 * completed_tasks - total_distance, GRB.MAXIMIZE)

            model.optimize()

            # 提取求解结果
            if model.status == GRB.OPTIMAL or model.status == GRB.SUBOPTIMAL:
                vehicle_assignments = {}
                total_distance = 0.0
                assigned_task_count = 0

                for v in vehicles:
                    assigned_tasks = []
                    for t in tasks:
                        if x[v.id, t.id].X > 0.5:
                            assigned_tasks.append(t.id)
                            task_pos = (t.position.x, t.position.y)
                            dist = 2 * self.calculate_distance(warehouse_pos, task_pos)
                            total_distance += dist
                            assigned_task_count += 1

                    if assigned_tasks:
                        vehicle_assignments[v.id] = assigned_tasks

                return Solution(
                    objective_value=model.ObjVal,
                    routes=[],
                    vehicle_assignments=vehicle_assignments,
                    charging_stations_used=[],
                    total_distance=total_distance,
                    total_time=0.0
                )
            else:
                print(f"Gurobi status: {model.status}")
                return None

        except ImportError:
            print("Gurobi not installed, using fallback solver")
            return self._fallback_solve(tasks, vehicles, charging_stations, warehouse_position)
        except Exception as e:
            print(f"Gurobi error: {e}")
            return self._fallback_solve(tasks, vehicles, charging_stations, warehouse_position)

    def _fallback_solve(self, tasks: List[Task], vehicles: List[Vehicle],
                       charging_stations: List[ChargingStation],
                       warehouse_position: tuple) -> Solution:
        """
        Gurobi 不可用时的后备求解器。
        使用贪心分配：在载重与电量约束下将任务分配给车辆。
        """
        warehouse_pos = warehouse_position if isinstance(warehouse_position, tuple) else \
                       (warehouse_position.x, warehouse_position.y)
        
        vehicle_assignments = {}
        assigned_tasks = set()
        total_distance = 0.0

        # 按优先级（降序）和距离（升序）排序任务
        sorted_tasks = sorted(tasks, key=lambda t: (-t.priority, 
                                                    self.calculate_distance(warehouse_pos, (t.position.x, t.position.y))))

        # 按可用载重（降序）排序车辆
        sorted_vehicles = sorted(vehicles, key=lambda v: v.max_load - v.current_load, reverse=True)

        # 贪心分配
        for vehicle in sorted_vehicles:
            for task in sorted_tasks:
                if task.id in assigned_tasks:
                    continue

                # 检查载重约束
                if vehicle.current_load + task.weight > vehicle.max_load:
                    continue

                # 检查电量约束
                task_pos = (task.position.x, task.position.y)
                round_trip_distance = 2 * self.calculate_distance(warehouse_pos, task_pos)
                energy_required = round_trip_distance * vehicle.unit_energy_consumption

                if energy_required > vehicle.max_battery:
                    continue

                # 将任务分配给车辆
                if vehicle.id not in vehicle_assignments:
                    vehicle_assignments[vehicle.id] = []

                # 简化模型：每辆车同一时刻最多执行一个任务
                if len(vehicle_assignments[vehicle.id]) == 0:
                    vehicle_assignments[vehicle.id].append(task.id)
                    assigned_tasks.add(task.id)
                    total_distance += round_trip_distance

        return Solution(
            objective_value=len(assigned_tasks),
            routes=[],
            vehicle_assignments=vehicle_assignments,
            charging_stations_used=[],
            total_distance=total_distance,
            total_time=0.0
        )
