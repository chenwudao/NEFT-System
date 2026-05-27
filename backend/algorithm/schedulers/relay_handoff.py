"""多车接力调度：支持 source->target 货物交接。

策略要点：
1) 先维护已有接力计划（会合 -> handoff）；
2) 若无计划，尝试为"外场空闲且载货"车辆找一个接力接收车；
3) 若不适合接力，则退化为常规配送决策。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.snapshot import Snapshot


class RelayHandoffScheduler(Scheduler):
    name = "relay_handoff"

    def __init__(self) -> None:
        # source_vid -> relay state
        self._active_relays: Dict[int, Dict] = {}

    def _vehicle_map(self, snapshot: Snapshot):
        return {v.id: v for v in snapshot.vehicles}

    def _task_map(self, snapshot: Snapshot):
        return {t.id: t for t in snapshot.tasks}

    def _select_transfer_tasks(self, source, target, snapshot: Snapshot) -> List[int]:
        """挑选值得交接的一批任务。"""
        undelivered = snapshot.vehicle_undelivered_tasks(source)
        if not undelivered:
            return []

        picked: List[int] = []
        rem = float(target.get_remaining_load())
        # 优先：接收车离任务更近 + 截止更紧
        ordered = sorted(
            undelivered,
            key=lambda t: (
                float(t.deadline),
                snapshot.distance(target.position, t.position)
                - snapshot.distance(source.position, t.position),
            ),
        )
        for t in ordered:
            if float(t.weight) > rem + 1e-9:
                continue
            src_d = snapshot.distance(source.position, t.position)
            dst_d = snapshot.distance(target.position, t.position)
            # 只有当目标车明显更合适时才接力，避免无意义搬运
            if dst_d + 80.0 <= src_d:
                picked.append(int(t.id))
                rem -= float(t.weight)
        return picked

    def _try_create_relay(self, snapshot: Snapshot, handled: set[int]) -> Optional[Tuple[int, Dict]]:
        """尝试创建一个新接力计划。"""
        idle_out = [v for v in snapshot.idle_vehicles_not_at_warehouse() if v.id not in handled]
        if not idle_out:
            return None
        candidates_target = [v for v in snapshot.vehicles_need_decision() if v.id not in handled]
        if not candidates_target:
            return None

        # source：外场、载货且电量偏低的车优先
        idle_out.sort(
            key=lambda v: (
                len(snapshot.vehicle_undelivered_tasks(v)) == 0,
                v.get_battery_percentage(),
            )
        )
        for src in idle_out:
            src_tasks = snapshot.vehicle_undelivered_tasks(src)
            if not src_tasks:
                continue
            best_target = None
            best_task_ids: List[int] = []
            best_cost = float("inf")
            for tgt in candidates_target:
                if tgt.id == src.id:
                    continue
                if float(tgt.get_remaining_load()) <= 1e-9:
                    continue
                task_ids = self._select_transfer_tasks(src, tgt, snapshot)
                if not task_ids:
                    continue
                d = snapshot.distance(tgt.position, src.position)
                if d < best_cost:
                    best_cost = d
                    best_target = tgt
                    best_task_ids = task_ids
            if best_target is None:
                continue
            rv_xy = (float(src.position.x), float(src.position.y))
            return src.id, {
                "source_id": int(src.id),
                "target_id": int(best_target.id),
                "task_ids": list(best_task_ids),
                "rv_xy": rv_xy,
            }
        return None

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        commands: List[Command] = []
        handled: set[int] = set()
        vmap = self._vehicle_map(snapshot)
        tmap = self._task_map(snapshot)

        # 1) 维护已有接力计划
        stale_sources = []
        for source_id, relay in list(self._active_relays.items()):
            src = vmap.get(source_id)
            tgt = vmap.get(int(relay.get("target_id", -1)))
            task_ids = [tid for tid in relay.get("task_ids", []) if tid in tmap]
            if src is None or tgt is None or not task_ids:
                stale_sources.append(source_id)
                continue

            # 只保留仍在 source 车上的任务
            task_ids = [tid for tid in task_ids if tid in set(src.assigned_task_ids)]
            if not task_ids:
                stale_sources.append(source_id)
                continue
            relay["task_ids"] = task_ids

            src_needs = src in snapshot.vehicles_need_decision()
            tgt_needs = tgt in snapshot.vehicles_need_decision()
            same_pos = utils.same_position(src, tgt)

            if src_needs and tgt_needs and same_pos:
                # 原地交接
                commands.append(utils.make_handoff_command(src, tgt, task_ids))
                handled.add(src.id)
                handled.add(tgt.id)
                stale_sources.append(source_id)
                continue

            rv_xy = tuple(relay.get("rv_xy", (src.position.x, src.position.y)))
            if tgt_needs and tgt.id not in handled and not same_pos:
                commands.append(utils.make_goto_node_command(tgt, rv_xy))
                handled.add(tgt.id)
            if src_needs and src.id not in handled:
                # source 在会合点等待；若不在会合点则先回到会合点
                if abs(src.position.x - rv_xy[0]) > 1e-4 or abs(src.position.y - rv_xy[1]) > 1e-4:
                    commands.append(utils.make_goto_node_command(src, rv_xy))
                else:
                    commands.append(utils.make_idle_command(src))
                handled.add(src.id)

        for sid in stale_sources:
            self._active_relays.pop(sid, None)

        # 2) 如当前无可执行接力，尝试新建一个接力任务
        if len(self._active_relays) < 3:  # 限制并发接力数量，避免震荡
            created = self._try_create_relay(snapshot, handled)
            if created is not None:
                sid, relay = created
                self._active_relays[sid] = relay
                src = vmap.get(relay["source_id"])
                tgt = vmap.get(relay["target_id"])
                rv_xy = relay["rv_xy"]
                if src is not None and src.id not in handled and src in snapshot.vehicles_need_decision():
                    commands.append(utils.make_idle_command(src))
                    handled.add(src.id)
                if tgt is not None and tgt.id not in handled and tgt in snapshot.vehicles_need_decision():
                    commands.append(utils.make_goto_node_command(tgt, rv_xy))
                    handled.add(tgt.id)

        # 3) 未参与接力的车辆按常规规则
        for v in snapshot.idle_vehicles_not_at_warehouse():
            if v.id in handled:
                continue
            commands.append(utils.decide_en_route(v, snapshot))
            handled.add(v.id)

        claimed = set()

        def pick_batch(vehicle, tasks, snap):
            unclaimed = [t for t in tasks if t.id not in claimed]
            unclaimed = utils.feasible_tasks_for(vehicle, unclaimed)
            if not unclaimed:
                return []
            unclaimed.sort(key=lambda t: (float(t.deadline), snap.distance(vehicle.position, t.position)))
            chosen = []
            for t in unclaimed:
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

        for v in snapshot.idle_vehicles_at_warehouse():
            if v.id in handled:
                continue
            cmd = utils.decide_at_warehouse(v, snapshot, pick_batch)
            if cmd.action == "deliver":
                claimed.update(cmd.assigned_tasks)
            commands.append(cmd)

        return commands

