"""Control events -> state changes, permissions and audible cues.

Every control input (DTMF from the rotary phone, a verified headset button, a
web "talk page", a GPIO pedal later) is translated into a ``ControlEvent`` and
applied here. The controller is pure: it mutates the runtime state it is given
and returns what happened, including which audible cues must be played *to the
affected endpoint only*.

Nothing in here can remove somebody's ability to hear; that is a deliberate
design rule (see model.py docstring).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from .model import Config, Endpoint
from .routing import EndpointState


@dataclass(frozen=True)
class ControlEvent:
    endpoint: str
    # An action string from model.validate_action, or one of:
    #   "ptt:down" | "ptt:up"
    action: str
    source: str = "unknown"   # "dtmf" | "button" | "web" | ...


@dataclass(frozen=True)
class Cue:
    endpoint: str          # who hears it (only this endpoint)
    kind: str              # "group" | "mute_on" | "mute_off" | "allcall_on" |
                           # "allcall_off" | "talk_on" | "talk_off" | "denied" | "status"
    group: str | None = None


@dataclass
class Attention:
    id: int
    source: str            # endpoint id
    via: str               # "dtmf" | "button" | "web" | "voice"
    created: float
    target: str
    acked_by: str | None = None
    acked_at: float | None = None

    @property
    def active(self) -> bool:
        return self.acked_at is None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "source": self.source, "via": self.via,
            "created": self.created, "target": self.target,
            "acked_by": self.acked_by, "acked_at": self.acked_at,
            "active": self.active,
        }


@dataclass
class Outcome:
    accepted: bool = True
    reason: str = ""
    changed: bool = False
    cues: list[Cue] = field(default_factory=list)
    attention: Attention | None = None


class Controller:
    def __init__(
        self,
        cfg_get: Callable[[], Config],
        state: dict[str, EndpointState],
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self._cfg = cfg_get
        self.state = state
        self._clock = clock
        self._wall = wall
        self.attention: list[Attention] = []
        self._next_att = 1

    # -- helpers ------------------------------------------------------------
    def _deny(self, ep: str, reason: str) -> Outcome:
        return Outcome(False, reason, False, [Cue(ep, "denied")])

    def _talk_target_cue(self, ep: Endpoint, st: EndpointState) -> Cue:
        if len(st.talk) == 1:
            return Cue(ep.id, "group", next(iter(st.talk)))
        return Cue(ep.id, "status")

    # -- main entry ---------------------------------------------------------
    def apply(self, ev: ControlEvent) -> Outcome:
        cfg = self._cfg()
        ep = cfg.endpoint(ev.endpoint)
        st = self.state.get(ev.endpoint)
        if ep is None or st is None:
            return Outcome(False, "unknown endpoint")
        if not ep.enabled:
            return Outcome(False, "endpoint disabled")

        action = ev.action
        kind, _, arg = action.partition(":")

        if action == "ptt:down":
            changed = not st.ptt_down
            st.ptt_down = True
            return Outcome(changed=changed)
        if action == "ptt:up":
            changed = st.ptt_down
            st.ptt_down = False
            return Outcome(changed=changed)

        if kind == "select":
            return self._select(cfg, ep, st, arg)
        if kind == "listen":
            return self._listen(cfg, ep, st, arg)
        if kind == "mute":
            return self._mute(ep, st, arg)
        if kind == "talk" and arg == "toggle":
            return self._talk_toggle(ep, st)
        if kind == "allcall":
            return self._allcall(cfg, ep, st, arg)
        if kind == "private":
            return self._private(cfg, ep, st, arg)
        if action == "attention":
            return self._attention(cfg, ep, ev)
        if action == "status":
            return Outcome(cues=[self._status_cue(ep, st)])
        return Outcome(False, f"unknown action {action!r}")

    # -- actions ------------------------------------------------------------
    def _select(self, cfg: Config, ep: Endpoint, st: EndpointState, gid: str) -> Outcome:
        if not ep.can_select:
            return self._deny(ep.id, "this endpoint may not change groups")
        if cfg.group(gid) is None:
            return self._deny(ep.id, f"unknown group {gid}")
        if gid not in ep.talk_allowed:
            return self._deny(ep.id, f"not permitted to talk to {gid}")
        before = (set(st.talk), set(st.listen))
        st.talk = {gid}
        if ep.select_scope == "both":
            if gid not in ep.listen_allowed:
                st.talk = before[0]
                return self._deny(ep.id, f"not permitted to listen to {gid}")
            st.listen = {gid}
        # Selecting a group ends an all-call or private line: the user chose somewhere to talk.
        st.allcall = False
        st.allcall_deadline = None
        st.private_to = st.private_deadline = None
        changed = before != (st.talk, st.listen)
        return Outcome(changed=changed, cues=[Cue(ep.id, "group", gid)])

    def _listen(self, cfg: Config, ep: Endpoint, st: EndpointState, gid: str) -> Outcome:
        if not ep.can_select:
            return self._deny(ep.id, "this endpoint may not change groups")
        if cfg.group(gid) is None or gid not in ep.listen_allowed:
            return self._deny(ep.id, f"not permitted to listen to {gid}")
        if gid in st.listen:
            # Never allow a user to end up hearing nothing by accident.
            if len(st.listen) == 1:
                return self._deny(ep.id, "at least one listen group must remain")
            st.listen.discard(gid)
        else:
            st.listen.add(gid)
        return Outcome(changed=True, cues=[Cue(ep.id, "group", gid)])

    def _mute(self, ep: Endpoint, st: EndpointState, arg: str) -> Outcome:
        if ep.forced_mute:
            return self._deny(ep.id, "muted by an administrator")
        new = (not st.muted) if arg == "toggle" else (arg == "on")
        changed = new != st.muted
        st.muted = new
        if new:
            # Muting ends an all-call so it cannot silently resume on unmute.
            st.allcall = False
            st.allcall_deadline = None
            st.private_to = st.private_deadline = None
        return Outcome(changed=changed, cues=[Cue(ep.id, "mute_on" if new else "mute_off")])

    def _talk_toggle(self, ep: Endpoint, st: EndpointState) -> Outcome:
        if ep.talk_mode != "latched":
            return self._deny(ep.id, "endpoint is not in latched-talk mode")
        st.latched_on = not st.latched_on
        return Outcome(changed=True, cues=[Cue(ep.id, "talk_on" if st.latched_on else "talk_off")])

    def _allcall(self, cfg: Config, ep: Endpoint, st: EndpointState, arg: str) -> Outcome:
        if not ep.can_allcall:
            return self._deny(ep.id, "not permitted to make all-calls")
        if st.muted or ep.forced_mute:
            return self._deny(ep.id, "cannot all-call while muted")
        new = (not st.allcall) if arg == "toggle" else (arg == "on")
        changed = new != st.allcall
        st.allcall = new
        if new:
            st.private_to = st.private_deadline = None      # one special mode at a time
        timeout = cfg.dtmf.allcall_timeout_s
        st.allcall_deadline = (self._clock() + timeout) if (new and timeout > 0) else None
        return Outcome(changed=changed, cues=[Cue(ep.id, "allcall_on" if new else "allcall_off")])

    def _private(self, cfg: Config, ep: Endpoint, st: EndpointState, arg: str) -> Outcome:
        """Open or close a private one-to-one line ("whisper"): only the chosen person hears you."""
        if not ep.can_private:
            return self._deny(ep.id, "not permitted to open private lines")
        if arg == "off" or (arg == st.private_to):
            changed = st.private_to is not None
            st.private_to = st.private_deadline = None
            return Outcome(changed=changed, cues=[Cue(ep.id, "private_off")])
        target = cfg.endpoint(arg)
        if target is None or target.id == ep.id or not target.enabled:
            return self._deny(ep.id, "that person is not available for a private line")
        if st.muted or ep.forced_mute:
            return self._deny(ep.id, "cannot open a private line while muted")
        st.private_to = target.id
        st.allcall, st.allcall_deadline = False, None
        timeout = cfg.dtmf.private_timeout_s
        st.private_deadline = (self._clock() + timeout) if timeout > 0 else None
        return Outcome(changed=True, cues=[Cue(ep.id, "private_on")])

    def _attention(self, cfg: Config, ep: Endpoint, ev: ControlEvent) -> Outcome:
        target = cfg.attention_target
        if not target:
            return self._deny(ep.id, "no attention target configured")
        # Collapse repeated presses by the same endpoint into one live alert.
        for a in self.attention:
            if a.active and a.source == ep.id:
                return Outcome(changed=False, attention=a)
        att = Attention(self._next_att, ep.id, ev.source, self._wall(), target)
        self._next_att += 1
        self.attention.append(att)
        return Outcome(changed=True, attention=att)

    def _status_cue(self, ep: Endpoint, st: EndpointState) -> Cue:
        if st.allcall:
            return Cue(ep.id, "allcall_on")
        if st.muted:
            return Cue(ep.id, "mute_on")
        return self._talk_target_cue(ep, st)

    # -- attention management (admin / dashboard) ----------------------------
    def ack_attention(self, att_id: int, by: str) -> bool:
        for a in self.attention:
            if a.id == att_id and a.active:
                a.acked_by, a.acked_at = by, self._wall()
                return True
        return False

    def ack_all_attention(self, by: str) -> int:
        n = 0
        for a in self.attention:
            if a.active:
                a.acked_by, a.acked_at = by, self._wall()
                n += 1
        return n

    def active_attention(self) -> list[Attention]:
        return [a for a in self.attention if a.active]

    # -- time-based housekeeping ---------------------------------------------
    def tick(self) -> list[Cue]:
        """Expire all-calls and private lines. Returns cues to play for expired ones."""
        cues: list[Cue] = []
        now = self._clock()
        for eid, st in self.state.items():
            if st.allcall and st.allcall_deadline is not None and now >= st.allcall_deadline:
                st.allcall = False
                st.allcall_deadline = None
                cues.append(Cue(eid, "allcall_off"))
            if st.private_to and st.private_deadline is not None and now >= st.private_deadline:
                st.private_to = st.private_deadline = None
                cues.append(Cue(eid, "private_off"))
        # Keep the attention history bounded.
        if len(self.attention) > 200:
            keep = {a.id for a in self.attention if a.active}
            keep |= {a.id for a in self.attention[-100:]}
            self.attention = [a for a in self.attention if a.id in keep]
        return cues
