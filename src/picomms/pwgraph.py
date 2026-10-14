"""PipeWire graph adapter: the only place that touches the live audio graph.

PipeWire (with WirePlumber and BlueZ) *is* the real-time audio engine. This
module only asks it to create/remove links, play short cues and open capture
taps, through the stock command-line tools (``pw-dump``, ``pw-link``,
``pw-cat``, ``wpctl``). That keeps the supported, upstream-maintained code on
the audio path.

Facts checked against PipeWire source (master, 1.6.0 era):
* ``pw-link`` links *linger* (survive the process that created them) unless
  ``-m`` is used -- so a crashed/restarted engine does not cut audio.
* ``pw-dump`` link objects carry ``info.output-port-id`` / ``info.input-port-id``
  and bluez nodes carry ``api.bluez5.address`` / ``api.bluez5.profile``.

UNVERIFIED on hardware: node/port naming for two simultaneous HFP headsets
(validation tests T1-T3). The code matches by Bluetooth address property and
falls back to parsing the address out of ``node.name``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from dataclasses import dataclass, field
from typing import Protocol

log = logging.getLogger("picomms.pw")

_MAC_IN_NAME = re.compile(r"((?:[0-9A-Fa-f]{2}[_:]){5}[0-9A-Fa-f]{2})")


@dataclass
class BtNode:
    id: int
    name: str
    address: str            # AA:BB:CC:DD:EE:FF
    direction: str          # "source" (microphone) | "sink" (earpiece)
    profile: str = ""       # api.bluez5.profile (e.g. headset-head-unit)
    codec: str = ""         # api.bluez5.codec (cvsd / msbc)
    state: str = ""
    in_ports: list[int] = field(default_factory=list)
    out_ports: list[int] = field(default_factory=list)


@dataclass
class BtCard:
    id: int
    address: str
    active_profile: str = ""
    profiles: dict[str, int] = field(default_factory=dict)   # name -> index


@dataclass
class GraphSnapshot:
    sources: dict[str, BtNode] = field(default_factory=dict)   # address -> node
    sinks: dict[str, BtNode] = field(default_factory=dict)
    cards: dict[str, BtCard] = field(default_factory=dict)
    # link id -> (src address, dst address, ports)
    links: dict[int, tuple[str, str]] = field(default_factory=dict)

    def audio_up(self, address: str) -> bool:
        """Both a microphone and an earpiece node exist in the HFP profile."""
        s, k = self.sources.get(address), self.sinks.get(address)
        return bool(s and k and s.profile.startswith("headset-head-unit")
                    and k.profile.startswith("headset-head-unit"))


def _addr_from(props: dict) -> str | None:
    a = props.get("api.bluez5.address")
    if a:
        return a.upper()
    m = _MAC_IN_NAME.search(props.get("node.name", "") or props.get("device.name", ""))
    return m.group(1).replace("_", ":").upper() if m else None


def parse_dump(objs: list[dict]) -> GraphSnapshot:
    """Turn ``pw-dump`` JSON into a snapshot of Bluetooth voice nodes and links."""
    snap = GraphSnapshot()
    nodes: dict[int, BtNode] = {}
    ports: dict[int, tuple[int, str]] = {}   # port id -> (node id, direction)
    for o in objs:
        t = o.get("type", "")
        info = o.get("info") or {}
        props = info.get("props") or {}
        if t == "PipeWire:Interface:Node":
            cls = props.get("media.class", "")
            if cls not in ("Audio/Source", "Audio/Sink"):
                continue
            addr = _addr_from(props)
            name = props.get("node.name", "")
            if not addr or not name.startswith("bluez_"):
                continue
            n = BtNode(
                id=o["id"], name=name, address=addr,
                direction="source" if cls == "Audio/Source" else "sink",
                profile=props.get("api.bluez5.profile", ""),
                codec=props.get("api.bluez5.codec", ""),
                state=info.get("state", ""),
            )
            nodes[n.id] = n
            (snap.sources if n.direction == "source" else snap.sinks)[addr] = n
        elif t == "PipeWire:Interface:Port":
            nid = props.get("node.id")
            if nid is not None:
                ports[o["id"]] = (int(nid), info.get("direction", ""))
        elif t == "PipeWire:Interface:Device":
            addr = _addr_from(props)
            if not addr or "bluez" not in (props.get("device.api", "") + props.get("device.name", "")):
                continue
            card = BtCard(id=o["id"], address=addr)
            params = info.get("params") or {}
            for p in params.get("EnumProfile", []) or []:
                if p.get("available", "yes") != "no":
                    card.profiles[p.get("name", "")] = p.get("index", -1)
            cur = params.get("Profile") or []
            if cur:
                card.active_profile = cur[0].get("name", "")
            snap.cards[addr] = card
    for pid, (nid, direction) in ports.items():
        n = nodes.get(nid)
        if n is None:
            continue
        (n.in_ports if direction == "input" else n.out_ports).append(pid)
    for n in nodes.values():
        n.in_ports.sort()
        n.out_ports.sort()
    for o in objs:
        if o.get("type") != "PipeWire:Interface:Link":
            continue
        info = o.get("info") or {}
        a, b = nodes.get(info.get("output-node-id")), nodes.get(info.get("input-node-id"))
        if a and b and a.direction == "source" and b.direction == "sink":
            snap.links[o["id"]] = (a.address, b.address)
    return snap


class GraphBackend(Protocol):
    async def snapshot(self) -> GraphSnapshot: ...
    async def reconcile(self, desired: set[tuple[str, str]], snap: GraphSnapshot | None = None) -> tuple[int, int]: ...
    async def ensure_hfp_profile(self, snap: GraphSnapshot) -> list[str]: ...
    async def play_cue(self, address: str, wav_path: str) -> None:
        """Play a short WAV into one endpoint's earpiece only."""
        snap = await self.snapshot()
        sink = snap.sinks.get(address)
        if not sink:
            return
        proc = await asyncio.create_subprocess_exec(
            "pw-cat", "--playback", "--target", sink.name, "--media-role", "Notification",
            wav_path,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(proc.wait(), 5.0)
        except asyncio.TimeoutError:
            proc.kill()

    async def start_tap(self, node_name: str, rate: int = 16000) -> asyncio.subprocess.Process:
        """Open an extra *consumer* of a microphone node, streaming raw s16 mono PCM.

        A tap does not alter routing links. It feeds the activity meter, DTMF
        decoder and caption forwarder, and keeps the endpoint's voice link in use.
        """
        return await asyncio.create_subprocess_exec(
            "pw-cat", "--record", "--target", node_name,
            "--rate", str(rate), "--channels", "1", "--format", "s16",
            "--latency", self.tap_latency, "--raw", "-",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
