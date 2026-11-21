"""Quality of service: message priorities, deadlines and store-and-forward on top of the radio links.

The headline score counts every packet the same. A real mission does not: a channel-switch order or a
position report that arrives late is worth less than a telemetry sample that arrives at all. This layer
models the traffic a deployed network carries and how it is scheduled when the links lose capacity.

Traffic (per radio, towards the command post, plus orders from the command post to every radio)
  class       priority  rate            deadline   when the deadline passes
  command     0         2 Hz + each AI  0.05 s     kept (orders are buffered until delivered, up to 2 s)
                        decision
  position    1         10 Hz           0.2 s      dropped (a newer one is coming)
  battery     2         1 Hz            1.0 s      dropped
  telemetry   3         20 Hz           2.0 s      dropped

Capacity: a link carries LINK_CAPACITY packets per 10 ms slot when it delivers that slot, and every link
on the route must deliver. Relays share their uplink with everyone routed through them, so relaying and
jamming both create real contention.

Two schedulers, compared on identical link outcomes (tests/test_qos.py):
  fifo   oldest first, no buffering through outages (a message whose route is down that slot is lost)
  qos    strict priority (command first), deadline-aware dropping, store-and-forward: messages wait in a
         bounded buffer (BUFFER per radio) while the route is down and go out by priority when it returns;
         under overload the lowest class is dropped first
"""
from __future__ import annotations

import heapq
import itertools
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

CLASSES = ("command", "position", "battery", "telemetry")
PRIORITY = {c: i for i, c in enumerate(CLASSES)}
RATE_HZ = {"position": 10.0, "battery": 1.0, "telemetry": 20.0}
COMMAND_HEARTBEAT_HZ = 2.0
_GEN = [(c, 1 / hz) for c, hz in RATE_HZ.items()] + [("command", 1 / COMMAND_HEARTBEAT_HZ)]
_PER_NODE = len(_GEN)
DEADLINE_S = {"command": 0.05, "position": 0.2, "battery": 1.0, "telemetry": 2.0}
COMMAND_KEEP_S = 2.0
LINK_CAPACITY = 2
BUFFER = 300


@dataclass(order=True)
class Msg:
    key: tuple
    cls: str = field(compare=False)
    node: str = field(compare=False)
    born: float = field(compare=False)
    down: bool = field(compare=False, default=False)      # command post -> radio


class QoSLayer:
    def __init__(self, mode: str = "qos", seed: int = 0):
        assert mode in ("qos", "fifo")
        self.mode = mode
        self.rng = np.random.default_rng(seed + 5150)
        self.q: dict[str, list] = defaultdict(list)
        self.count = itertools.count()
        self.next_gen: dict[tuple[str, str], float] = {}
        self.stats = {c: {"sent": 0, "delivered": 0, "on_time": 0, "dropped": 0, "lat": []} for c in CLASSES}

    def order(self, cmd_from_ai: list[str]) -> None:
        """An AI decision becomes a command message to every radio that must apply it."""
        self._pending_orders = getattr(self, "_pending_orders", []) + list(cmd_from_ai)

    def _push(self, m: Msg) -> None:
        q = self.q[m.node]
        if len(q) >= BUFFER:
            if self.mode == "fifo":
                self._drop(m)
                return
            worst = max(q, key=lambda x: (PRIORITY[x.cls], -x.born))   # buffer full: drop the least important
            if PRIORITY[worst.cls] > PRIORITY[m.cls]:
                q.remove(worst)
                heapq.heapify(q)
                self._drop(worst)
            else:
                self._drop(m)
                return
        heapq.heappush(q, m)

    def _drop(self, m: Msg) -> None:
        self.stats[m.cls]["dropped"] += 1

    def _make(self, cls: str, node: str, t: float, down: bool = False) -> Msg:
        self.stats[cls]["sent"] += 1
        key = ((PRIORITY[cls], t, next(self.count)) if self.mode == "qos" else (t, next(self.count)))
        return Msg(key, cls, node, t, down)

    def slot(self, t: float, nodes: list[str], path_of, link_ok: np.ndarray, usable: set[str]) -> None:
        # 1) new traffic
        # one batched draw per slot: the same random numbers, in the same order, as one draw per (node, class)
        live = [n for n in nodes if n in usable]
        draws = self.rng.random(len(live) * _PER_NODE) if live else ()
        i = 0
        for n in live:
            for cls, period in _GEN:
                k = (n, cls)
                due = self.next_gen.get(k)
                if due is None:
                    due = float(draws[i]) * period
                i += 1
                if t >= due:
                    self.next_gen[k] = t + period
                    self._push(self._make(cls, n, t, down=(cls == "command")))
        for _ in getattr(self, "_pending_orders", []):
            for n in nodes:
                if n in usable:
                    self._push(self._make("command", n, t, down=True))
        self._pending_orders = []

        # 2) expire
        for n, q in self.q.items():
            keep = []
            for m in q:
                age = t - m.born
                if m.cls == "command":
                    limit = COMMAND_KEEP_S if self.mode == "qos" else DEADLINE_S["command"] * 4
                else:
                    limit = DEADLINE_S[m.cls]
                (keep.append(m) if age <= limit else self._drop(m))
            if len(keep) != len(q):
                heapq.heapify(keep)
                self.q[n] = keep

        # 3) send: each link carries LINK_CAPACITY packets this slot if it delivers; strict order across radios
        cap: dict[int, int] = defaultdict(lambda: LINK_CAPACITY)
        heads = []
        for n, q in self.q.items():
            if q:
                heads.append((q[0].key, n))
        heapq.heapify(heads)
        while heads:
            _, n = heapq.heappop(heads)
            q = self.q[n]
            if not q:
                continue
            path = path_of(n) if n in usable else None
            up = bool(path) and bool(np.all(link_ok[path]))
            if up and not all(cap[l] > 0 for l in path):
                continue                                  # links busy this slot: both schedulers wait for the next one
            if not up:
                if self.mode == "fifo":
                    # no store-and-forward: whatever this radio had to send this slot is lost
                    m = heapq.heappop(q)
                    self._drop(m)
                    if q:
                        heapq.heappush(heads, (q[0].key, n))
                continue                                  # qos: it waits in the buffer
            m = heapq.heappop(q)
            for l in path:
                cap[l] -= 1
            lat = t - m.born
            s = self.stats[m.cls]
            s["delivered"] += 1
            s["on_time"] += lat <= DEADLINE_S[m.cls]
            s["lat"].append(lat)
            if len(s["lat"]) > 5000:
                del s["lat"][:1000]
            if q:
                heapq.heappush(heads, (q[0].key, n))

    def summary(self) -> dict:
        out = {}
        for c, s in self.stats.items():
            lat = np.array(s["lat"]) if s["lat"] else None
            out[c] = {"sent": s["sent"], "delivered_pct": round(100 * s["delivered"] / s["sent"], 1) if s["sent"] else None,
                      "on_time_pct": round(100 * s["on_time"] / s["sent"], 1) if s["sent"] else None,
                      "latency_p50_ms": round(1000 * float(np.median(lat)), 1) if lat is not None else None,
                      "latency_p95_ms": round(1000 * float(np.percentile(lat, 95)), 1) if lat is not None else None}
        out["buffered"] = sum(len(q) for q in self.q.values())
        return out
