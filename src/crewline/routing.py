"""Pure routing: which microphone must be linked to which earpiece.

The audio engine is PipeWire itself. A "route" is a PipeWire link from the
source node of endpoint A (its microphone) to the sink node of endpoint B (its
earpiece). PipeWire mixes multiple links arriving at one sink port (UNVERIFIED
on the target hardware -- validation test T3), so this gives a mix-minus for
free: B hears every permitted talker except itself.

This module only computes the desired set of links from config + runtime
state. It has no I/O, which is what makes routing and permissions testable
without Bluetooth hardware.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import Config, Endpoint


@dataclass
class EndpointState:
    """Runtime state of one endpoint (never persisted, except by choice)."""

    connected: bool = False          # ACL link up
    audio_up: bool = False           # both PipeWire source and sink nodes exist
    muted: bool = False              # self-service software mute
    ptt_down: bool = False
    latched_on: bool = False
    tone_gate: bool = False          # DTMF tone currently suppressing TX
    listen: set[str] = field(default_factory=set)
    talk: set[str] = field(default_factory=set)
    allcall: bool = False            # this endpoint is currently all-calling
    allcall_deadline: float | None = None
    private_to: str | None = None    # id of the one endpoint this endpoint is whispering to
    private_deadline: float | None = None


@dataclass(frozen=True)
class Link:
    src: str      # endpoint id whose microphone is the source
    dst: str      # endpoint id whose earpiece receives it
    reason: str   # "group:<id>" or "allcall"


def init_state(cfg: Config) -> dict[str, EndpointState]:
    return {
        e.id: EndpointState(listen=set(e.listen), talk=set(e.talk))
        for e in cfg.endpoints
    }


def is_transmitting(ep: Endpoint, st: EndpointState) -> bool:
    """Is this endpoint's microphone allowed onto the intercom right now?"""
    if not ep.enabled or ep.forced_mute or st.muted or st.tone_gate:
        return False
    if not (st.connected and st.audio_up):
        return False
    if st.allcall:
        return True
    if ep.talk_mode == "open":
        return True
    if ep.talk_mode == "latched":
        return st.latched_on
    if ep.talk_mode == "ptt":
        return st.ptt_down
    return False


def can_receive(ep: Endpoint, st: EndpointState) -> bool:
    return ep.enabled and st.connected and st.audio_up


def compute_links(cfg: Config, state: dict[str, EndpointState]) -> set[Link]:
    links: set[Link] = set()
    by_id = {e.id: e for e in cfg.endpoints}
    for src_id, src in by_id.items():
        sst = state.get(src_id)
        if sst is None or not is_transmitting(src, sst):
            continue
        for dst_id, dst in by_id.items():
            if dst_id == src_id:
                continue
            dst_state = state.get(dst_id)
            if dst_state is None or not can_receive(dst, dst_state):
                continue
            pt = by_id.get(sst.private_to) if sst.private_to else None
            if pt is not None and pt.enabled and src.can_private:
                if dst_id == sst.private_to:      # a private line goes to exactly one person
                    links.add(Link(src_id, dst_id, "private"))
                continue
            if sst.allcall and src.can_allcall:
                links.add(Link(src_id, dst_id, "allcall"))
                continue
            shared = sorted(sst.talk & dst_state.listen)
            if shared:
                links.add(Link(src_id, dst_id, f"group:{shared[0]}"))
    return links


def explain(cfg: Config, state: dict[str, EndpointState], src_id: str, dst_id: str) -> str:
    """Human-readable reason why ``dst`` can or cannot hear ``src``.

    Used by the diagnostics page so that "I can't hear Alex" has a concrete
    answer rather than a guess.
    """
    src = cfg.endpoint(src_id)
    dst = cfg.endpoint(dst_id)
    if src is None or dst is None:
        return "unknown endpoint"
    s, d = state[src_id], state[dst_id]
    if src_id == dst_id:
        return "an endpoint never hears itself (no sidetone)"
    if not src.enabled:
        return f"{src.name} is disabled by an administrator"
    if not dst.enabled:
        return f"{dst.name} is disabled by an administrator"
    if not s.connected:
        return f"{src.name} is not connected"
    if not s.audio_up:
        return f"{src.name} is connected but has no active two-way audio session"
    if not d.connected:
        return f"{dst.name} is not connected"
    if not d.audio_up:
        return f"{dst.name} is connected but has no active two-way audio session"
    if src.forced_mute:
        return f"{src.name} is muted by an administrator"
    if s.muted:
        return f"{src.name} has muted their microphone"
    if s.tone_gate:
        return f"{src.name} is momentarily gated while a command tone is present"
    if not s.allcall:
        if src.talk_mode == "latched" and not s.latched_on:
            return f"{src.name} is in latched-talk mode and is not transmitting"
        if src.talk_mode == "ptt" and not s.ptt_down:
            return f"{src.name} is in push-to-talk mode and is not pressing talk"
    if s.private_to and src.can_private:
        if s.private_to == dst_id:
            return f"{src.name} has a private line open to {dst.name}"
        other = cfg.endpoint(s.private_to)
        return f"{src.name} has a private line open to {other.name if other else s.private_to}, so nobody else hears them"
    if s.allcall and src.can_allcall:
        return f"{src.name} is making an all-call; {dst.name} hears it"
    shared = s.talk & d.listen
    if not shared:
        return (
            f"{src.name} talks to {sorted(s.talk) or 'no group'} but "
            f"{dst.name} listens to {sorted(d.listen) or 'no group'}"
        )
    return f"{dst.name} hears {src.name} via group {sorted(shared)[0]}"
