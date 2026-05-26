"""多智能体拍卖策略（Multi-agent Auction）。

流程：
1) 每辆车对每个任务计算 bid（收益 - 成本）；
2) 按任务维度选择最高 bid 的车辆；
3) 得到初始分配后，每辆车内部做路径排序并做可行性裁剪；
4) 产出批量 deliver 指令。
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Dict, List

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.snapshot import Snapshot


class MultiAgentAuctionScheduler(Scheduler):
    name = "multi_agent_auction"

    def _bid(self, vehicle, task, snap: Snapshot, now_ts: int) -> float:
        d = snap.distance(vehicle.position, task.position)
        if d == float("inf"):
            return float("-inf")
        deadline_left = float(task.deadline) - float(now_ts)
        urgency = 1.0 if deadline_left <= 0 else 1.0 / max(1.0, deadline_left / 600.0)
        load_fit = 1.0 - (float(task.weight) / max(1.0, float(vehicle.max_load)))
        return float(task.priority) * 40.0 + urgency * 60.0 + load_fit * 20.0 - (d / 150.0)

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        commands: List[Command] = []

        for v in snapshot.idle_vehicles_not_at_warehouse():
            commands.append(utils.decide_en_route(v, snapshot))

        vehicles = list(snapshot.idle_vehicles_at_warehouse())
        tasks = list(snapshot.available_tasks())
        if not vehicles:
            return commands
        if not tasks:
            for v in vehicles:
                commands.append(utils.make_idle_command(v))
            return commands

        now_ts = int(snapshot.timestamp or time.time())
        vehicle_by_id = {v.id: v for v in vehicles}
        assignment: Dict[int, List] = defaultdict(list)

        # 任务拍卖：每个任务选 bid 最高且能装下的车
        rem_cap = {v.id: float(v.get_remaining_load()) for v in vehicles}
        for t in tasks:
            best_vid = None
            best_bid = float("-inf")
            for v in vehicles:
                if float(t.weight) > rem_cap[v.id] + 1e-9:
                    continue
                b = self._bid(v, t, snapshot, now_ts)
                if b > best_bid:
                    best_bid = b
                    best_vid = v.id
            if best_vid is not None:
                assignment[best_vid].append(t)
                rem_cap[best_vid] -= float(t.weight)

        # 每辆车路径内排序 + 可行性裁剪
        for v in vehicles:
            allocated = assignment.get(v.id, [])
            if not allocated:
                commands.append(utils.make_idle_command(v))
                continue

            ordered_xy = utils.greedy_chain(
                (v.position.x, v.position.y),
                [(t.position.x, t.position.y) for t in allocated],
                snapshot,
            )
            id_by_xy = {(t.position.x, t.position.y): t for t in allocated}
            ordered = [id_by_xy[xy] for xy in ordered_xy if xy in id_by_xy]

            feasible = []
            for t in ordered:
                cand = feasible + [t]
                dist = utils.estimate_chain_distance_with_recharge(
                    v,
                    [(x.position.x, x.position.y) for x in cand],
                    snapshot,
                    require_final_station_buffer=True,
                )
                if dist == float("inf"):
                    break
                feasible = cand

            if not feasible:
                cmd = utils.decide_at_warehouse(v, snapshot, lambda *_: [])
                commands.append(cmd)
                continue

            cmd = utils.make_deliver_command(v, feasible[0], [x.id for x in feasible])
            commands.append(cmd)

        return commands

