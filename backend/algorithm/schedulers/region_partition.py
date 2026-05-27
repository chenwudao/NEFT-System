"""自动分区调度：车辆按区域负责任务。

思路：
1) 从当前可用任务自动提取 K 个区域中心（K=仓库待命车数量，至少1）；
2) 车辆按距离分配到区域中心；
3) 每辆车优先处理自己区域内任务，区域空缺时再回退到全局任务。
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.snapshot import Snapshot


class RegionPartitionScheduler(Scheduler):
    name = "region_partition"

    def _k_centers(self, points: List[Tuple[float, float]], k: int, snapshot: Snapshot) -> List[Tuple[float, float]]:
        """贪心 farthest-point 选中心。"""
        if not points:
            return []
        k = max(1, min(k, len(points)))
        centers = [points[0]]
        while len(centers) < k:
            best_p = None
            best_min_d = float("-inf")
            for p in points:
                min_d = min(snapshot.distance(p, c) for c in centers)
                if min_d > best_min_d:
                    best_min_d = min_d
                    best_p = p
            if best_p is None:
                break
            centers.append(best_p)
        return centers

    def _assign_vehicle_to_center(self, vehicles, centers, snapshot: Snapshot) -> Dict[int, int]:
        """车辆->中心贪心匹配（索引）。"""
        out: Dict[int, int] = {}
        free_centers = set(range(len(centers)))
        # 先给每辆车分配最近中心，尽量均匀覆盖
        for v in sorted(vehicles, key=lambda x: x.id):
            if not centers:
                out[v.id] = -1
                continue
            if free_centers:
                cid = min(free_centers, key=lambda c: snapshot.distance(v.position, centers[c]))
                free_centers.remove(cid)
                out[v.id] = cid
            else:
                cid = min(range(len(centers)), key=lambda c: snapshot.distance(v.position, centers[c]))
                out[v.id] = cid
        return out

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        commands: List[Command] = []

        # 非仓库车辆按常规送货
        for v in snapshot.idle_vehicles_not_at_warehouse():
            commands.append(utils.decide_en_route(v, snapshot))

        wh_vehicles = list(snapshot.idle_vehicles_at_warehouse())
        available = list(snapshot.available_tasks())
        if not wh_vehicles:
            return commands
        if not available:
            for v in wh_vehicles:
                commands.append(utils.make_idle_command(v))
            return commands

        points = [(float(t.position.x), float(t.position.y)) for t in available]
        centers = self._k_centers(points, len(wh_vehicles), snapshot)
        v2c = self._assign_vehicle_to_center(wh_vehicles, centers, snapshot)
        claimed = set()

        def pick_batch_factory(v):
            cid = v2c.get(v.id, -1)

            def pick_batch(vehicle, tasks, snap):
                unclaimed = [t for t in tasks if t.id not in claimed]
                unclaimed = utils.feasible_tasks_for(vehicle, unclaimed)
                if not unclaimed:
                    return []

                if cid >= 0 and cid < len(centers):
                    center = centers[cid]
                    local = sorted(
                        unclaimed,
                        key=lambda t: snap.distance((t.position.x, t.position.y), center),
                    )
                else:
                    local = list(unclaimed)

                # 区域任务不足时回退到全局最近
                if not local:
                    local = sorted(unclaimed, key=lambda t: snap.distance(vehicle.position, t.position))

                chosen = []
                for t in local:
                    cand = chosen + [t]
                    ordered = utils.greedy_chain(
                        (vehicle.position.x, vehicle.position.y),
                        [(x.position.x, x.position.y) for x in cand],
                        snap,
                    )
                    dist = utils.estimate_chain_distance_with_recharge(
                        vehicle, ordered, snap, require_final_station_buffer=True
                    )
                    if dist == float("inf"):
                        break
                    chosen = cand
                return chosen

            return pick_batch

        for v in wh_vehicles:
            cmd = utils.decide_at_warehouse(v, snapshot, pick_batch_factory(v))
            if cmd.action == "deliver":
                claimed.update(cmd.assigned_tasks)
            commands.append(cmd)

        return commands

