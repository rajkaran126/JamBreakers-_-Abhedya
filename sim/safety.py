"""Safety guard: every AI decision is checked before it is sent, and undone if it made things worse.

The AI (CNN + rules, the RL agent, or both) proposes actions. It can be wrong: a misread jammer, a stale
spectrum, a policy that never saw this situation. So nothing it proposes reaches the radios unchecked:

  1. Canonical order   blacklist -> mode -> hop -> power -> rate -> relay, one action of each kind
  2. No contradictions a hop and a hop-mode change in one decision: the mode change wins
  3. Sane targets      never hop onto a channel that is blacklisted or visibly jammed when a cleaner one
                       exists (the target is corrected); never blacklist so much that < 4 channels remain
  4. Limits            power stays within 0..cap, only known modulations, at most MAX_PER_S decisions a second
  5. Undo              ~1 s after an action, if delivery got clearly worse (and no new jammer appeared),
                       the previous radio settings are restored and the step is logged

All of it is plain deterministic code, so it can be tested and explained.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from typing import Optional

import numpy as np

from .defenders import Action, Decision
from .radio import N_CH, NOISE_INBAND_DBM

ORDER = {"blacklist": 0, "mode": 1, "hop": 2, "power": 3, "rate": 4, "relay": 5}
MODULATIONS = ("QPSK", "BPSK", "BPSK_R2")
HOT_DB = 10.0
MIN_FREE_CHANNELS = 4
MAX_PER_S = 6
UNDO_AFTER_S = 1.0
UNDO_WORSE_BY = 0.25          # delivery must fall by this much (absolute) ...
UNDO_BELOW = 0.5              # ... and end below this, to count as "clearly worse"
UNDO_COOLDOWN_S = 5.0


@dataclass
class Snapshot:
    t: float
    slot: int
    hop_mode: str
    dwell_channel: int
    anti_follow: bool
    boost_db: float
    modulation: str
    delivery_before: float
    jammers_before: frozenset
    decision: Decision


class SafetyGuard:
    def __init__(self, power_cap_db: float):
        self.power_cap_db = power_cap_db
        self.recent_decisions: deque[float] = deque()
        self.watch: Optional[Snapshot] = None
        self.last_undo_t = -99.0
        self.fixes = 0                # actions corrected or dropped
        self.undos = 0
        self.notes: list[str] = []    # plain-English log of what the guard did (shown in the decision log)

    # ------------------------------------------------------------------ before sending
    def check(self, d: Decision, w) -> Optional[Decision]:
        """Return a safe version of the decision (or None to drop it)."""
        t = w.t
        while self.recent_decisions and t - self.recent_decisions[0] > 1.0:
            self.recent_decisions.popleft()
        if d.actions and len(self.recent_decisions) >= MAX_PER_S:
            self._note(f"dropped '{d.action}': more than {MAX_PER_S} radio changes in one second")
            return None
        fixed: list[str] = []
        energy = w.net.fused_energy_dbm(w.jammers)
        hot = {c for c in range(N_CH) if energy[c] > NOISE_INBAND_DBM + HOT_DB}
        bl = set(w.active_blacklist())

        # 1 + 2: one action per kind, canonical order, mode beats hop
        by_kind: dict[str, Action] = {}
        for a in d.actions:
            if a.kind not in ORDER:
                fixed.append(f"removed unknown action '{a.kind}'")
                continue
            if a.kind in by_kind:
                fixed.append(f"merged duplicate '{a.kind}'")
            by_kind[a.kind] = a
        if "mode" in by_kind and "hop" in by_kind:
            fixed.append("dropped a hop that contradicted the hop-mode change")
            del by_kind["hop"]
        acts = sorted(by_kind.values(), key=lambda a: ORDER[a.kind])

        out: list[Action] = []
        for a in acts:
            if a.kind == "blacklist":
                chans = tuple(c for c in a.channels if 0 <= c < N_CH)
                if len(chans) != len(a.channels):
                    fixed.append("removed channel numbers that do not exist")
                if chans:
                    out.append(replace(a, channels=chans))
                    # the world keeps only the newest entries (at least MIN_FREE_CHANNELS stay usable)
                    keep = N_CH - MIN_FREE_CHANNELS
                    old = sorted(bl - set(chans), key=lambda c: w.blacklist.get(c, 0), reverse=True)
                    bl = set(chans[:keep]) | set(old[:max(0, keep - len(chans))])
            elif a.kind in ("hop",) or (a.kind == "mode" and a.mode == "dwell" and a.channel is not None):
                target = a.channel
                bad = target is None or not (0 <= target < N_CH) or target in bl or target in hot
                if bad:
                    options = [c for c in range(N_CH) if c not in bl and c != w.channel]
                    clean = [c for c in options if c not in hot]
                    better = min(clean or options or [w.channel], key=lambda c: energy[c])
                    if better != target and (target is None or target in bl or not (0 <= target < N_CH)
                                             or energy[better] < energy[target] - 3):
                        fixed.append(f"hop target {target} was {'blocked' if target in bl else 'jammed'}: corrected to {better}")
                        a = replace(a, channel=better)
                if a.kind == "hop" and a.channel == w.channel and w.hop_mode == "dwell":
                    fixed.append("dropped a hop to the channel we are already on")
                    continue
                out.append(a)
            elif a.kind == "power":
                new = float(np.clip(w.net.tx_boost_db + a.delta_db, 0.0, self.power_cap_db))
                if new == w.net.tx_boost_db:
                    fixed.append("dropped a power change beyond the limits")
                    continue
                out.append(replace(a, delta_db=new - w.net.tx_boost_db))
            elif a.kind == "rate":
                if a.modulation not in MODULATIONS:
                    fixed.append(f"removed unknown modulation '{a.modulation}'")
                    continue
                if a.modulation == w.net.modulation:
                    continue
                out.append(a)
            else:
                out.append(a)

        if fixed:
            self.fixes += len(fixed)
            self._note("; ".join(fixed))
        if not out and d.actions:
            return None if fixed else d
        if d.actions:
            self.recent_decisions.append(t)
        reason = d.reason + (f" [Safety guard: {'; '.join(fixed)}.]" if fixed else "")
        to = next((a.channel for a in out if a.kind in ("hop", "mode") and a.channel is not None), d.to_channel)
        return replace(d, actions=out, reason=reason, to_channel=to)

    # ------------------------------------------------------------------ after it took effect
    def applied(self, d: Decision, w, before: dict) -> None:
        if not any(a.kind in ("hop", "mode", "power", "rate") for a in d.actions):
            return
        self.watch = Snapshot(w.t, w.slot, before["hop_mode"], before["dwell_channel"], before["anti_follow"],
                              before["boost_db"], before["modulation"], before["delivery"], frozenset(j.id for j in w.jammers), d)

    def maybe_undo(self, w, delivery_now: float) -> Optional[Decision]:
        s = self.watch
        if s is None or w.t - s.t < UNDO_AFTER_S:
            return None
        self.watch = None
        if frozenset(j.id for j in w.jammers) != s.jammers_before:
            return None                               # the attack changed: not the action's fault
        if w.t - self.last_undo_t < UNDO_COOLDOWN_S:
            return None
        if not (delivery_now < s.delivery_before - UNDO_WORSE_BY and delivery_now < UNDO_BELOW):
            return None
        self.last_undo_t = w.t
        self.undos += 1
        acts = []
        if w.hop_mode != s.hop_mode or (s.hop_mode == "dwell" and w.channel != s.dwell_channel):
            acts.append(Action("mode", mode=s.hop_mode, channel=s.dwell_channel if s.hop_mode == "dwell" else None,
                               anti_follow=s.anti_follow))
        if abs(w.net.tx_boost_db - s.boost_db) > 0.1:
            acts.append(Action("power", delta_db=s.boost_db - w.net.tx_boost_db))
        if w.net.modulation != s.modulation:
            acts.append(Action("rate", modulation=s.modulation))
        if not acts:
            return None
        msg = (f"Safety guard: the last action ('{s.decision.action}') made delivery worse "
               f"({s.delivery_before:.0%} → {delivery_now:.0%}) with the same jammers on the air: undone.")
        self._note(msg)
        return Decision(s.decision.cls, s.decision.confidence, "undo", msg, acts, w.channel,
                        s.dwell_channel if s.hop_mode == "dwell" else None)

    def _note(self, text: str) -> None:
        self.notes.append(text)
        self.notes = self.notes[-20:]
