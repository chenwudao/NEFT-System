from typing import List, Dict, Optional
from backend.data.task import Task
from backend.data.vehicle import Vehicle
from backend.data.charging_station import ChargingStation
from .solution import Solution

class MIPSolver:
    def __init__(self):
        self.model = None
        self.solver = None

    def build_model(self, tasks: List[Task], vehicles: List[Vehicle], 
                   charging_stations: List[ChargingStation], 
                   warehouse_position: tuple):
        pass

    def solve(self) -> Solution:
        pass

    def get_objective_value(self) -> float:
        return 0.0

    def solve_with_gurobi(self, tasks: List[Task], vehicles: List[Vehicle],
                          charging_stations: List[ChargingStation],
                          warehouse_position: tuple) -> Optional[Solution]:
        try:
            from gurobipy import Model, GRB, quicksum

            model = Model("EVRPTW")

            x = {}
            for v in vehicles:
                for t in tasks:
                    x[v.id, t.id] = model.addVar(vtype=GRB.BINARY, name=f"x_{v.id}_{t.id}")

            for v in vehicles:
                model.addConstr(quicksum(x[v.id, t.id] * t.weight for t in tasks) <= v.max_load, 
                              name=f"capacity_{v.id}")

            for t in tasks:
                model.addConstr(quicksum(x[v.id, t.id] for v in vehicles) == 1, 
                              name=f"task_{t.id}")

            model.setObjective(quicksum(x[v.id, t.id] for v in vehicles for t in tasks), 
                            GRB.MINIMIZE)

            model.optimize()

            if model.status == GRB.OPTIMAL:
                vehicle_assignments = {}
                for v in vehicles:
                    assigned_tasks = [t.id for t in tasks if x[v.id, t.id].X > 0.5]
                    if assigned_tasks:
                        vehicle_assignments[v.id] = assigned_tasks

                return Solution(
                    objective_value=model.ObjVal,
                    routes=[],
                    vehicle_assignments=vehicle_assignments,
                    charging_stations_used=[],
                    total_distance=0.0,
                    total_time=0.0
                )
            else:
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
        vehicle_assignments = {}
        task_index = 0

        for vehicle in vehicles:
            assigned_tasks = []
            current_load = 0

            while task_index < len(tasks) and current_load < vehicle.max_load:
                task = tasks[task_index]
                if current_load + task.weight <= vehicle.max_load:
                    assigned_tasks.append(task.id)
                    current_load += task.weight
                    task_index += 1
                else:
                    break

            if assigned_tasks:
                vehicle_assignments[vehicle.id] = assigned_tasks

        return Solution(
            objective_value=len(tasks),
            routes=[],
            vehicle_assignments=vehicle_assignments,
            charging_stations_used=[],
            total_distance=0.0,
            total_time=0.0
        )
