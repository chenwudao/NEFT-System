"""RL 装批调度器：nearest 定候选池，cap 后 DFS 取得分最高的最大可行装批。

- nearest 贪心前缀得到候选；超过 nearest_rl_cap（默认 7）只保留前 N 个
- 在 rl_pool 上用与 dfs_score_search 相同的 DFS（最大可行 + 最高分）
- Q 表仍记录 (state, dfs动作) 供送完后学习；装批选择由 DFS 决定
- |P|<=1 时直接装单，不走 DFS
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set, Tuple

from backend.algorithm import utils
from backend.algorithm.scheduler import Command, Scheduler
from backend.algorithm.schedulers.dfs_score_search import find_best_maximal_batch_dfs
from backend.algorithm.scoring_config import calculate_batch_chain_score
from backend.algorithm.snapshot import Snapshot
from backend.config import config
from backend.data.task import Task, TaskStatus
from backend.data.vehicle import Vehicle


def _rl_cfg() -> Dict:
    return dict(config.get_scheduling_config().get("rl_batch") or {})


def _nearest_rl_cap() -> int:
    return max(2, int(_rl_cfg().get("nearest_rl_cap", 7)))


def _cap_nearest_for_rl(nearest_list: List[Task]) -> Tuple[List[Task], int]:
    raw = len(nearest_list)
    cap = _nearest_rl_cap()
    if raw <= cap:
        return nearest_list, raw
    return nearest_list[:cap], raw


def _battery_tier(pct: float) -> str:
    if pct < 30.0:
        return "low"
    if pct < 60.0:
        return "mid"
    return "high"


def _state_key(nearest_count: int, bat: str) -> str:
    return f"n:{nearest_count}|bat:{bat}"


def _dfs_action_key(task_ids: List[int]) -> str:
    return "dfs:" + ",".join(str(i) for i in sorted(task_ids))


@dataclass
class _PendingBatch:
    batch_id: str
    state_key: str
    action_key: str
    task_ids: List[int]
    predicted_score: float


class RlBatchScheduler(Scheduler):
    name = "rl_batch"

    def __init__(self) -> None:
        cfg = _rl_cfg()
        self._alpha = float(cfg.get("learning_rate", 0.1))
        self._epsilon = float(cfg.get("epsilon", 0.15))
        self._epsilon_min = float(cfg.get("epsilon_min", 0.05))
        self._epsilon_decay = float(cfg.get("epsilon_decay", 0.999))
        self._reward_shaping_beta = float(cfg.get("reward_shaping_beta", 0.25))
        self._timeout_penalty = float(cfg.get("timeout_penalty", 50.0))
        self._policy_path = Path(str(cfg.get("policy_path", "data/rl_batch_policy.json")))
        self._q_table: Dict[str, Dict[str, float]] = {}
        self._pending: List[_PendingBatch] = []
        self._batch_seq = 0
        self._load_policy()

    def _load_policy(self) -> None:
        if not self._policy_path.is_file():
            return
        try:
            raw = json.loads(self._policy_path.read_text(encoding="utf-8"))
            self._q_table = {
                str(s): {str(a): float(v) for a, v in row.items()}
                for s, row in (raw.get("q_table") or {}).items()
            }
            self._epsilon = float(raw.get("epsilon", self._epsilon))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    def _save_policy(self) -> None:
        self._policy_path.parent.mkdir(parents=True, exist_ok=True)
        self._policy_path.write_text(
            json.dumps(
                {"q_table": self._q_table, "epsilon": self._epsilon},
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def _q_get(self, s: str, a: str) -> float:
        return float(self._q_table.get(s, {}).get(a, 0.0))

    def _q_update(self, s: str, a: str, reward: float) -> float:
        old = self._q_get(s, a)
        new = old + self._alpha * (reward - old)
        self._q_table.setdefault(s, {})[a] = new
        return new

    def _settle_pending(self, task_by_id: Dict[int, Task]) -> None:
        terminal = {TaskStatus.COMPLETED, TaskStatus.TIMEOUT}
        still: List[_PendingBatch] = []
        for pb in self._pending:
            statuses: List[TaskStatus] = []
            for tid in pb.task_ids:
                t = task_by_id.get(tid)
                statuses.append(
                    TaskStatus.TIMEOUT if t is None else t.status
                )
            if not statuses or any(st not in terminal for st in statuses):
                still.append(pb)
                continue

            r_real = 0.0
            n_timeout = 0
            for tid in pb.task_ids:
                t = task_by_id.get(tid)
                if t is None or t.status == TaskStatus.TIMEOUT:
                    n_timeout += 1
                elif t.status == TaskStatus.COMPLETED:
                    r_real += float(getattr(t, "score", 0.0) or 0.0)
            r_real -= n_timeout * self._timeout_penalty
            r = r_real + self._reward_shaping_beta * pb.predicted_score
            old_q = self._q_get(pb.state_key, pb.action_key)
            new_q = self._q_update(pb.state_key, pb.action_key, r)
            print(
                f"[RL settle] batch={pb.batch_id} state={pb.state_key} "
                f"action={pb.action_key} reward={r:.2f} Q:{old_q:.2f}->{new_q:.2f}"
            )
        self._pending = still

    def schedule(self, snapshot: Snapshot) -> List[Command]:
        task_by_id = {t.id: t for t in snapshot.tasks}
        self._settle_pending(task_by_id)

        commands: List[Command] = []
        claimed: Set[int] = set()
        available = list(snapshot.available_tasks())

        for v in snapshot.idle_vehicles_not_at_warehouse():
            commands.append(utils.decide_en_route(v, snapshot))

        for v in snapshot.idle_vehicles_at_warehouse():
            idle_cmd = utils.try_idle_at_warehouse(v, snapshot)
            if idle_cmd is not None:
                commands.append(idle_cmd)
                continue

            cmd = self._warehouse_pick(v, available, snapshot, claimed)
            commands.append(cmd)
            if cmd.action == "deliver" and cmd.assigned_tasks:
                claimed.update(cmd.assigned_tasks)

        self._epsilon = max(self._epsilon_min, self._epsilon * self._epsilon_decay)
        self._save_policy()
        return commands

    def _warehouse_pick(
        self,
        vehicle: Vehicle,
        available: List[Task],
        snapshot: Snapshot,
        claimed: Set[int],
    ) -> Command:
        nearest_list = _pick_nearest_batch(vehicle, available, snapshot, claimed)
        if not nearest_list:
            on_board = snapshot.vehicle_undelivered_tasks(vehicle)
            if on_board:
                return utils.command_for_warehouse_batch(vehicle, snapshot, on_board)
            return utils.make_idle_command(vehicle)

        rl_pool, nearest_raw_count = _cap_nearest_for_rl(nearest_list)
        nearest_count = len(rl_pool)
        if nearest_raw_count > nearest_count:
            dropped = nearest_list[nearest_count:]
            print(
                f"[RL cap] vehicle={vehicle.id} nearest_raw={nearest_raw_count} "
                f"rl_pool={nearest_count} cap={_nearest_rl_cap()} "
                f"dropped_task_ids={[t.id for t in dropped]}"
            )

        if nearest_count <= 1:
            return utils.command_for_warehouse_batch(vehicle, snapshot, rl_pool)

        picked = find_best_maximal_batch_dfs(vehicle, rl_pool, snapshot)
        if not picked:
            print(
                f"[RL dfs] vehicle={vehicle.id} no maximal feasible batch in rl_pool="
                f"{[t.id for t in rl_pool]}, fallback"
            )
            return self._fallback_nearest_batch(vehicle, rl_pool, snapshot)

        now_ts = int(snapshot.timestamp or 0)
        predicted = float(
            calculate_batch_chain_score(picked, vehicle, snapshot, now_ts)
        )
        kept_ids = [t.id for t in picked]
        removed_ids = [t.id for t in rl_pool if t.id not in set(kept_ids)]
        bat = _battery_tier(float(vehicle.get_battery_percentage()))
        s = _state_key(nearest_count, bat)
        a_key = _dfs_action_key(kept_ids)

        print(
            f"[RL dfs] vehicle={vehicle.id} state={s} action={a_key} "
            f"nearest_raw={nearest_raw_count} rl_pool={nearest_count} "
            f"final_count={len(picked)} score={predicted:.2f} "
            f"kept_ids={kept_ids} removed_from_pool={removed_ids}"
        )

        self._batch_seq += 1
        self._pending.append(
            _PendingBatch(
                batch_id=f"b{self._batch_seq}",
                state_key=s,
                action_key=a_key,
                task_ids=kept_ids,
                predicted_score=predicted,
            )
        )

        return utils.command_for_warehouse_batch(vehicle, snapshot, picked)

    def _fallback_nearest_batch(
        self,
        vehicle: Vehicle,
        rl_pool: List[Task],
        snapshot: Snapshot,
    ) -> Command:
        if _batch_feasible(vehicle, rl_pool, snapshot):
            print(
                f"[RL fallback] vehicle={vehicle.id} deliver rl_pool="
                f"{[t.id for t in rl_pool]}"
            )
            return utils.command_for_warehouse_batch(vehicle, snapshot, rl_pool)

        for k in range(len(rl_pool), 0, -1):
            sub = rl_pool[:k]
            if _batch_feasible(vehicle, sub, snapshot):
                print(
                    f"[RL fallback] vehicle={vehicle.id} deliver prefix k={k} "
                    f"ids={[t.id for t in sub]}"
                )
                return utils.command_for_warehouse_batch(vehicle, snapshot, sub)

        for t in rl_pool:
            if _batch_feasible(vehicle, [t], snapshot):
                print(
                    f"[RL fallback] vehicle={vehicle.id} deliver single id={t.id}"
                )
                return utils.command_for_warehouse_batch(vehicle, snapshot, [t])

        print(f"[RL fallback] vehicle={vehicle.id} no feasible subset in rl_pool")
        return utils.make_idle_command(vehicle)


def _pick_nearest_batch(
    vehicle: Vehicle,
    tasks: List[Task],
    snapshot: Snapshot,
    claimed: Set[int],
) -> List[Task]:
    unclaimed = [t for t in tasks if t.id not in claimed]
    unclaimed = utils.feasible_tasks_for(vehicle, unclaimed)
    if not unclaimed:
        return []

    start_xy = (vehicle.position.x, vehicle.position.y)
    unclaimed.sort(key=lambda t: snapshot.distance(vehicle.position, t.position))

    chosen: List[Task] = []
    for t in unclaimed:
        cand = chosen + [t]
        ordered = utils.greedy_chain(
            start_xy,
            [(x.position.x, x.position.y) for x in cand],
            snapshot,
        )
        if not ordered:
            break
        dist = utils.estimate_chain_distance_with_recharge(
            vehicle,
            ordered,
            snapshot,
            require_final_station_buffer=True,
        )
        if dist == float("inf"):
            break
        chosen = cand

    if not chosen:
        for t in unclaimed:
            ordered = utils.greedy_chain(
                start_xy,
                [(t.position.x, t.position.y)],
                snapshot,
            )
            if not ordered:
                continue
            dist = utils.estimate_chain_distance_with_recharge(
                vehicle,
                ordered,
                snapshot,
                require_final_station_buffer=True,
            )
            if dist != float("inf"):
                return [t]
    return chosen


def _batch_feasible(
    vehicle: Vehicle,
    tasks: List[Task],
    snapshot: Snapshot,
) -> bool:
    if not tasks:
        return False
    ordered = utils.greedy_chain(
        (vehicle.position.x, vehicle.position.y),
        [(t.position.x, t.position.y) for t in tasks],
        snapshot,
    )
    if not ordered or len(ordered) != len(tasks):
        return False
    if sum(float(t.weight) for t in tasks) > float(vehicle.get_remaining_load()) + 1e-9:
        return False
    dist = utils.estimate_chain_distance_with_recharge(
        vehicle,
        ordered,
        snapshot,
        require_final_station_buffer=True,
    )
    return dist != float("inf")
