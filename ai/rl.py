"""A small reinforcement-learning hopping agent (tabular Q-learning), trained in the simulator.

It is the "learn it from scratch" alternative to the CNN defender, and one more row in the benchmark.
It sees only what a real radio measures: packet loss and the energy on each channel. No CNN, no
jammer labels. Every 100 ms it picks one of five moves:

  stay      do nothing
  hop       blacklist the busy channels for 3 s and hop to the quietest one
  keyed     secret keyed fast hopping (HMAC sequence), avoiding busy channels
  power     +3 dB, or drop to BPSK once power is at its cap
  calm      undo the last escalation (power down, back to QPSK, or back to a fixed channel)

State (256): loss bucket x busy-channel count x our channel busy x "re-found after we hopped"
x keyed mode x escalated (power up or BPSK). Reward: share of packets delivered in the next
100 ms, minus a small cost for each move (moving is not free in a real network).

    python -m ai.rl --train          # ~3-6 min on a laptop; writes ai/weights/rl_q.json
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Optional

import numpy as np

from sim.defenders import Action, Decision, Defender, SlotObs
from sim.radio import N_CH, NOISE_INBAND_DBM

WEIGHTS = Path(__file__).resolve().parent / "weights" / "rl_q.json"
ACTIONS = ("stay", "hop", "keyed", "power", "calm")
COST = {"stay": 0.0, "hop": 0.03, "keyed": 0.03, "power": 0.01, "calm": 0.0}
HOT_DB = 10.0
DECIDE_EVERY = 10              # slots (100 ms)
FOLLOW_WINDOW_S = 0.3
POWER_CAP_DB = 9.0
N_STATES = 4 * 4 * 2 * 2 * 2 * 2


def _bucket(x: float, edges) -> int:
    return int(np.searchsorted(edges, x, side="right"))


class RLDefender(Defender):
    name = "rl"

    def __init__(self, rng: Optional[np.random.Generator] = None, q: Optional[np.ndarray] = None,
                 epsilon: float = 0.0, learn_log: Optional[list] = None):
        super().__init__(rng)
        self.q = q if q is not None else load_q()
        self.epsilon = epsilon
        self.log = learn_log                     # training: collects (s, a, r, s') transitions
        self.k = 0
        self.prev: Optional[tuple[int, int]] = None
        self.sent = self.deliv = 0
        self.last_hop_t = -9.0
        self.followed = False
        self.boost = 0.0
        self.bpsk = False

    # ---------------------------------------------------------------- observation -> state
    def _state(self, obs: SlotObs, hot: list[int]) -> int:
        lb = _bucket(obs.loss_recent, [0.05, 0.3, 0.7])
        hb = _bucket(len(hot), [0, 2, 5])
        our = int(obs.channel in hot)
        keyed = int(obs.hop_mode == "keyed")
        esc = int(obs.tx_boost_db > 0 or obs.modulation == "BPSK")
        return ((((lb * 4 + hb) * 2 + our) * 2 + int(self.followed)) * 2 + keyed) * 2 + esc

    def _cleanest(self, obs: SlotObs, exclude: set[int]) -> int:
        e = obs.energy_dbm.copy()
        for c in exclude | set(obs.blacklist):
            e[c] = np.inf
        if np.all(np.isinf(e)):
            e = obs.energy_dbm.copy()
            e[obs.channel] = np.inf
        return int(np.argmin(e))

    # ---------------------------------------------------------------- per slot
    def on_slot(self, obs: SlotObs) -> Optional[Decision]:
        self.sent += obs.sent
        self.deliv += obs.delivered
        hot = [c for c in range(N_CH) if obs.energy_dbm[c] > NOISE_INBAND_DBM + HOT_DB]
        if obs.t - self.last_hop_t < FOLLOW_WINDOW_S and obs.channel in hot and obs.loss_recent > 0.3:
            self.followed = True                  # the interference found our new channel almost at once
        self.k += 1
        if self.k % DECIDE_EVERY or obs.control_pending:
            return None
        s = self._state(obs, hot)
        if self.prev is not None and self.log is not None:
            ps, pa = self.prev
            r = (self.deliv / self.sent if self.sent else 1.0) - COST[ACTIONS[pa]]
            self.log.append((ps, pa, float(r), s))
        self.sent = self.deliv = 0
        if self.epsilon and self.rng.random() < self.epsilon:
            a = int(self.rng.integers(len(ACTIONS)))
        else:
            a = int(np.argmax(self.q[s]))
        self.prev = (s, a)
        return self._act(ACTIONS[a], obs, hot, float(self.q[s, a]))

    def _act(self, name: str, obs: SlotObs, hot: list[int], qv: float) -> Optional[Decision]:
        ch = obs.channel
        why = f"RL agent (Q = {qv:.2f}): "
        if name == "stay":
            return None
        if name == "hop":
            to = self._cleanest(obs, set(hot) | {ch})
            self.last_hop_t = obs.t
            acts = [Action("blacklist", channels=tuple(sorted(set(hot) | {ch})), ttl_s=3.0)] if hot else []
            acts.append(Action("mode", mode="dwell", channel=to) if obs.hop_mode == "keyed" else Action("hop", channel=to))
            return Decision("unknown", 0.0, "hop", why + f"loss {obs.loss_recent:.0%}, {len(hot)} busy channels: hop {ch} → {to}.", acts, ch, to)
        if name == "keyed":
            if obs.hop_mode == "keyed" and not hot:
                return None
            self.last_hop_t = obs.t
            acts = [] if obs.hop_mode == "keyed" else [Action("mode", mode="keyed", anti_follow=self.followed)]
            if hot:
                acts.append(Action("blacklist", channels=tuple(sorted(hot)), ttl_s=3.0))
            return Decision("unknown", 0.0, "fast_hop", why + f"keyed fast hopping, avoiding {len(hot)} busy channels.", acts, ch, None)
        if name == "power":
            if obs.tx_boost_db < POWER_CAP_DB:
                return Decision("unknown", 0.0, "raise_power", why + f"loss {obs.loss_recent:.0%}: +3 dB.", [Action("power", delta_db=3.0)])
            if obs.modulation != "BPSK":
                return Decision("unknown", 0.0, "lower_rate", why + "power at maximum: QPSK → BPSK.", [Action("rate", modulation="BPSK")])
            return None
        # calm: undo one escalation
        if obs.tx_boost_db > 0:
            return Decision("unknown", 0.0, "raise_power", why + "calmer: power −3 dB.", [Action("power", delta_db=-3.0)])
        if obs.modulation == "BPSK":
            return Decision("unknown", 0.0, "lower_rate", why + "calmer: back to QPSK.", [Action("rate", modulation="QPSK")])
        if obs.hop_mode == "keyed":
            self.followed = False
            to = self._cleanest(obs, set(hot))
            return Decision("unknown", 0.0, "hop", why + f"calmer: leave keyed mode, settle on channel {to}.", [Action("mode", mode="dwell", channel=to)], ch, to)
        return None


def load_q() -> np.ndarray:
    if WEIGHTS.exists():
        return np.array(json.loads(WEIGHTS.read_text())["q"], dtype=float)
    q = np.zeros((N_STATES, len(ACTIONS)))
    q[:, 0] = 0.01                                   # untrained: prefer to stay put
    return q


# ---------------------------------------------------------------------------------------- training
TRAIN_JAMMERS = ["barrage", "random", "sweep", "reactive", "deceptive", "accidental", "follower", "smart", None]


def _episode(job) -> list:
    q, jammer, seed, eps = job
    from sim.experiment import run_episode
    from sim import world as W
    log: list = []
    orig = W.make_defender
    W.make_defender = lambda name, rng: RLDefender(rng, q=q, epsilon=eps, learn_log=log)   # noqa: E731
    try:
        rng = np.random.default_rng(seed)
        pos = (float(rng.uniform(-100, 700)), float(rng.uniform(-200, 500)))
        run_episode(jammer, "rl", seed=seed, duration_s=12.0, jam_at_s=1.0, pos=pos)
    finally:
        W.make_defender = orig
    return log


def train(iterations: int = 10, seeds_per: int = 2, workers: Optional[int] = None, verbose: bool = True) -> np.ndarray:
    q = load_q() if WEIGHTS.exists() and False else np.zeros((N_STATES, len(ACTIONS)))
    q[:, 0] = 0.01
    alpha, gamma = 0.15, 0.8
    t0 = time.time()
    buffer: list = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for it in range(iterations):
            eps = max(0.05, 0.4 * (1 - it / max(iterations - 1, 1)))
            jobs = [(q.copy(), j, 1000 + it * 50 + k * 7 + n, eps) for k, j in enumerate(TRAIN_JAMMERS) for n in range(seeds_per)]
            logs = list(ex.map(_episode, jobs))
            new = [tr for lg in logs for tr in lg]
            buffer = (buffer + new)[-60000:]
            for _ in range(3):                       # replay the recent experience a few times
                for i in np.random.default_rng(it).permutation(len(buffer)):
                    s, a, r, s2 = buffer[i]
                    q[s, a] += alpha * (r + gamma * q[s2].max() - q[s, a])
            if verbose:
                mean_r = np.mean([tr[2] for tr in new]) if new else 0
                print(f"iteration {it + 1}/{iterations}: eps {eps:.2f}, {len(new)} decisions, mean reward {mean_r:.3f}, "
                      f"{time.time() - t0:.0f} s", flush=True)
    return q


def save_q(q: np.ndarray) -> None:
    WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
    visited = int((np.abs(q).sum(axis=1) > 0.011).sum())
    WEIGHTS.write_text(json.dumps({"actions": ACTIONS, "states": N_STATES, "visited_states": visited,
                                   "q": np.round(q, 4).tolist()}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--iterations", type=int, default=10)
    ap.add_argument("--workers", type=int, default=None)
    a = ap.parse_args()
    if a.train:
        q = train(a.iterations, workers=a.workers)
        save_q(q)
        print(f"saved {WEIGHTS}")
