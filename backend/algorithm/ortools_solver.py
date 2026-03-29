"""
OR-Tools + CBC 开源求解器实现

完全免费，无变量/约束限制
安装: pip install ortools

使用与实时调度统一的评分机制：
- 任务分配奖励: 120分/任务
- 优先级奖励: 30分/优先级点
- 距离惩罚: -0.02/米
- 能耗惩罚: -0.2/单位
- 逾期惩罚: -50分/分钟
"""

from typing import List, Optional, Tuple, Dict
from backend.data.task import Task
from backend.data.vehicle import Vehicle
from backend.data.charging_station import ChargingStation
from backend.algorithm.solution import Solution
from backend.algorithm.scoring_config import (
    TASK_ASSIGN_REWARD,
    PRIORITY_REWARD,
    DISTANCE_PENALTY,
    ENERGY_PENALTY,
    OVERDUE_PENALTY_PER_MIN,
    ASSUMED_SPEED_MPS,
    calculate_assignment_score
)


class ORToolsSolver:
    """使用 OR-Tools + CBC 求解器（完全开源免费）"""
    
    def __init__(self, path_calculator=None):
        self.path_calculator = path_calculator
    
    def set_path_calculator(self, path_calculator):
        self.path_calculator = path_calculator
    
    def calculate_distance(self, pos1: tuple, pos2: tuple) -> float:
        """计算两点间距离 - 使用图路径距离（更精确）"""
        if self.path_calculator:
            try:
                # 优先使用图路径距离（基于OSM道路网络）
                return self.path_calculator.calculate_pair_distance(pos1, pos2)
            except Exception as e:
                # 图路径计算失败时回退到欧氏距离
                self.path_calculator.logger.warning(f"Graph distance failed, fallback to Euclidean: {e}")
                pass
        # 回退到欧氏距离
        import math
        return math.sqrt((pos1[0] - pos2[0])**2 + (pos1[1] - pos2[1])**2)
    
    def solve(self, tasks: List[Task], vehicles: List[Vehicle],
              charging_stations: List[ChargingStation],
              warehouse_position: tuple) -> Optional[Solution]:
        """
        使用 OR-Tools + CBC 求解
        
        优势：
        - 完全免费开源
        - 无变量/约束数量限制
        - 支持大规模问题
        """
        try:
            from ortools.linear_solver import pywraplp
            
            # 创建 CBC 求解器
            solver = pywraplp.Solver.CreateSolver('CBC')
            if not solver:
                print("[ORTools] Failed to create CBC solver")
                return None
            
            print(f"[ORTools] Solving with CBC: {len(tasks)} tasks, {len(vehicles)} vehicles")
            
            warehouse_pos = warehouse_position if isinstance(warehouse_position, tuple) else \
                           (warehouse_position.x, warehouse_position.y)
            
            # 预计算距离矩阵，处理不可达情况
            distance_matrix = {}
            reachable_tasks = set()
            vehicle_task_feasible = {}  # 记录每辆车可以执行哪些任务
            
            for v in vehicles:
                feasible_tasks = []
                for t in tasks:
                    task_pos = (t.position.x, t.position.y)
                    try:
                        dist = self.calculate_distance(warehouse_pos, task_pos)
                        distance_matrix[(v.id, t.id)] = dist
                        reachable_tasks.add(t.id)
                        
                        # 检查电量是否足够（往返）
                        round_trip_distance = 2 * dist
                        energy_required = round_trip_distance * v.unit_energy_consumption
                        
                        if energy_required <= v.battery:
                            feasible_tasks.append(t.id)
                            vehicle_task_feasible[(v.id, t.id)] = True
                        else:
                            vehicle_task_feasible[(v.id, t.id)] = False
                            
                    except Exception:
                        # 路径不可达，标记为不可分配
                        distance_matrix[(v.id, t.id)] = float('inf')
                        vehicle_task_feasible[(v.id, t.id)] = False
                
                if len(feasible_tasks) < len(tasks):
                    print(f"[ORTools] Vehicle {v.id} ({v.vehicle_type}): {len(feasible_tasks)}/{len(tasks)} tasks feasible")
            
            if not reachable_tasks:
                print("[ORTools] No reachable tasks found")
                return None
            
            print(f"[ORTools] {len(reachable_tasks)}/{len(tasks)} tasks are reachable from warehouse")
            
            # 决策变量：x[v,t] = 1 表示车辆 v 被分配任务 t
            x = {}
            for v in vehicles:
                for t in tasks:
                    x[v.id, t.id] = solver.BoolVar(f'x_{v.id}_{t.id}')
            
            # 约束1：每个任务最多分配给一辆车（<=1，不要求所有任务都被分配）
            # 这样当任务数 > 车辆数时，求解器会选择最优的子集
            for t in tasks:
                solver.Add(sum(x[v.id, t.id] for v in vehicles) <= 1)
            
            # 约束2：车辆载重约束（一辆车可以执行多个任务，但总重量不超过载重）
            for v in vehicles:
                solver.Add(sum(x[v.id, t.id] * t.weight for t in tasks) <= v.max_load)
            
            # 注：不限制每车最多处理的任务数量（与实时调度对齐）
            # 实时调度支持一辆车执行多个顺路任务（最多3个）
            
            # 约束4：不可达或电量不足的任务禁止分配
            infeasible_count = 0
            for v in vehicles:
                for t in tasks:
                    if not vehicle_task_feasible.get((v.id, t.id), False):
                        solver.Add(x[v.id, t.id] == 0)
                        infeasible_count += 1
            
            if infeasible_count > 0:
                print(f"[ORTools] {infeasible_count} vehicle-task pairs are infeasible (filtered)")
            
            # 目标函数：使用与实时调度统一的评分机制（最大化）
            # 参考 MetaStrategySelector._score_commands 的评分公式
            objective = solver.Objective()
            
            current_timestamp = int(__import__('time').time())
            
            for v in vehicles:
                for t in tasks:
                    if vehicle_task_feasible.get((v.id, t.id), False):
                        dist = distance_matrix[(v.id, t.id)]
                        
                        # 使用统一的评分函数计算得分
                        score = calculate_assignment_score(t, v, dist, current_timestamp)
                        
                        # OR-Tools 默认最小化，所以取负值
                        objective.SetCoefficient(x[v.id, t.id], -score)
            
            objective.SetMinimization()
            
            # 求解
            status = solver.Solve()
            
            # 打印求解状态
            status_names = {
                pywraplp.Solver.OPTIMAL: "OPTIMAL",
                pywraplp.Solver.FEASIBLE: "FEASIBLE",
                pywraplp.Solver.INFEASIBLE: "INFEASIBLE",
                pywraplp.Solver.UNBOUNDED: "UNBOUNDED",
                pywraplp.Solver.ABNORMAL: "ABNORMAL",
                pywraplp.Solver.NOT_SOLVED: "NOT_SOLVED",
                pywraplp.Solver.MODEL_INVALID: "MODEL_INVALID"
            }
            status_name = status_names.get(status, f"UNKNOWN({status})")
            print(f"[ORTools] Solver status: {status_name}")
            
            if status == pywraplp.Solver.OPTIMAL or status == pywraplp.Solver.FEASIBLE:
                # 提取解
                vehicle_assignments = {}
                routes = []
                total_distance = 0.0
                total_score = 0.0  # 使用统一的评分
                charging_stations_used = []
                assigned_tasks_count = 0
                
                # 重新计算当前时间（与目标函数一致）
                current_timestamp = int(__import__('time').time())
                
                for v in vehicles:
                    assigned_tasks = []
                    route = [v.id]  # 路线从车辆ID开始
                    
                    for t in tasks:
                        if x[v.id, t.id].solution_value() > 0.5:
                            assigned_tasks.append(t.id)
                            route.append(t.id)
                            assigned_tasks_count += 1
                            dist = distance_matrix.get((v.id, t.id), 0)
                            if dist != float('inf'):
                                total_distance += dist
                                
                                # 使用统一的评分函数计算得分（与目标函数一致）
                                score = calculate_assignment_score(t, v, dist, current_timestamp)
                                total_score += score
                    
                    if assigned_tasks:
                        vehicle_assignments[v.id] = assigned_tasks
                        routes.append(route)
                
                print(f"[ORTools] Solution found: {len(vehicle_assignments)} vehicles assigned, "
                      f"{assigned_tasks_count} tasks assigned, total distance: {total_distance:.2f}, "
                      f"total score: {total_score:.2f}")
                
                # 调试：打印每个车辆的分配
                for v_id, task_ids in vehicle_assignments.items():
                    print(f"[ORTools]   Vehicle {v_id}: tasks {task_ids}")
                
                return Solution(
                    objective_value=total_score,  # 使用统一评分作为目标值
                    routes=routes,
                    vehicle_assignments=vehicle_assignments,
                    charging_stations_used=charging_stations_used,
                    total_distance=total_distance,
                    total_time=total_distance / 10.0  # 假设平均速度10m/s
                )
            else:
                print(f"[ORTools] No solution found")
                # 打印调试信息
                feasible_pairs = sum(1 for v in vehicles for t in tasks 
                                   if vehicle_task_feasible.get((v.id, t.id), False))
                print(f"[ORTools] Debug: {feasible_pairs} feasible vehicle-task pairs, "
                      f"{len(tasks)} tasks, {len(vehicles)} vehicles")
                
                return None
                
        except ImportError:
            print("[ORTools] OR-Tools not installed. Install with: pip install ortools")
            return None
        except Exception as e:
            print(f"[ORTools] Solver error: {e}")
            import traceback
            traceback.print_exc()
            return None
