"""多智能体方法：Contract Net 协议风格分配。

机制：
1) 管理者广播候选任务；
2) 车辆作为 agent 对任务投标（bid）；
3) 每轮给当前最高 bid 的 agent 授标；
4) 重复直到无可授标任务；
5) 每车本地排序并做可行性裁剪。
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Dict, List, Tuple

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.snapshot import Snapshot


class MultiAgentContractNetScheduler(Scheduler):
    name = "multi_agent_contract_net"

    def _bid(self, vehicle, task, snap: Snapshot, now_ts: int) -> float:
        d = snap.distance(vehicle.position, task.position)
        if d == float("inf"):
            return float("-inf")
        overdue_risk = 1.0 if float(task.deadline) < float(now_ts) else 0.0
        return (
            float(task.priority) * 40.0
            - (d / 180.0)
            - overdue_risk * 90.0
            + max(0.0, 1.0 - float(task.weight) / max(1.0, float(vehicle.max_load))) * 15.0
        )

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
        rem_cap = {v.id: float(v.get_remaining_load()) for v in vehicles}
        assignment: Dict[int, List] = defaultdict(list)
        unassigned = list(tasks)

        # contract-net 迭代授标
        while unassigned:
            best_pair: Tuple[float, int, object] = (float("-inf"), -1, None)
            for t in unassigned:
                for v in vehicles:
                    if float(t.weight) > rem_cap[v.id] + 1e-9:
                        continue
                    b = self._bid(v, t, snapshot, now_ts)
                    if b > best_pair[0]:
                        best_pair = (b, v.id, t)
            score, vid, task = best_pair
            if task is None or vid < 0 or score == float("-inf"):
                break
            assignment[vid].append(task)
            rem_cap[vid] -= float(task.weight)
            unassigned = [t for t in unassigned if t.id != task.id]

        # 车内排序 + 可行性裁剪
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

            commands.append(utils.make_deliver_command(v, feasible[0], [x.id for x in feasible]))

        return commands

