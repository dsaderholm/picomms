"""Simulated graph/Bluetooth backends.

For unit tests, UI development and demos only. Nothing produced here is
hardware evidence; every number a user sees from a simulated run is labelled
"SIMULATION" in the UI.
"""

from __future__ import annotations

import asyncio
import math
import random
import struct
from dataclasses import dataclass, field

from .pwgraph import BtCard, BtNode, GraphSnapshot


@dataclass
class SimDevice:
    address: str
    name: str
    paired: bool = True
    connected: bool = True
    sco_ok: bool = True           # False simulates "pairs fine, no two-way audio"
    battery: int | None = None    # None = unknown
    rssi: int | None = None
    adapter: str = "00:00:00:00:00:01"


class SimGraph:
    """In-memory GraphBackend."""

    def __init__(self) -> None:
        self.devices: dict[str, SimDevice] = {}
        self.links: set[tuple[str, str]] = set()
        self.cues: list[tuple[str, str]] = []
        self.profile_switches: list[str] = []
        self._next = 100
        self.hfp_profile_active: dict[str, bool] = {}
        self.taps: dict[str, "SimTap"] = {}

    def add_device(self, d: SimDevice) -> None:
        self.devices[d.address] = d
        self.hfp_profile_active[d.address] = True

    def remove_device(self, address: str) -> None:
        self.devices.pop(address, None)
        self.links = {l for l in self.links if address not in l}

    async def snapshot(self) -> GraphSnapshot:
        snap = GraphSnapshot()
        i = 1
        for addr, d in self.devices.items():
            if not (d.connected and d.sco_ok):
                continue
            prof = "headset-head-unit" if self.hfp_profile_active.get(addr, True) else "a2dp-sink"
            mac = addr.replace(":", "_")
            snap.sources[addr] = BtNode(i, f"bluez_input.{mac}.0", addr, "source", prof, "msbc", "running", [], [i + 1])
            snap.sinks[addr] = BtNode(i + 2, f"bluez_output.{mac}.1", addr, "sink", prof, "msbc", "running", [i + 3], [])
            snap.cards[addr] = BtCard(i + 4, addr, prof, {"headset-head-unit": 2, "a2dp-sink": 1, "off": 0})
            i += 10
        for k, pair in enumerate(sorted(self.links)):
            if pair[0] in snap.sources and pair[1] in snap.sinks:
                snap.links[1000 + k] = pair
        return snap

    async def reconcile(self, desired: set[tuple[str, str]], snap=None) -> tuple[int, int]:
        snap = snap or await self.snapshot()
        valid = {p for p in desired if p[0] in snap.sources and p[1] in snap.sinks}
        added = len(valid - self.links)
        removed = len(self.links - valid)
        self.links = valid
        return added, removed

    async def ensure_hfp_profile(self, snap: GraphSnapshot) -> list[str]:
        out = []
        for addr, card in snap.cards.items():
            if not card.active_profile.startswith("headset-head-unit"):
                self.hfp_profile_active[addr] = True
                self.profile_switches.append(addr)
                out.append(addr)
        return out

    async def play_cue(self, address: str, wav_path: str) -> None:
        self.cues.append((address, wav_path))

    async def start_tap(self, node_name: str, rate: int = 16000):
        addr = node_name.split(".")[1].replace("_", ":")
        tap = SimTap(addr, rate)
        self.taps[addr] = tap
        return tap


class _Reader:
    def __init__(self) -> None:
        self.q: asyncio.Queue[bytes] = asyncio.Queue()
        self.closed = False

    async def read(self, n: int) -> bytes:
        if self.closed and self.q.empty():
            return b""
        return await self.q.get()


class SimTap:
    """Looks like an asyncio subprocess with a .stdout reader fed by tests/demos."""

    def __init__(self, address: str, rate: int) -> None:
        self.address = address
        self.rate = rate
        self.stdout = _Reader()
        self.returncode: int | None = None

    def push(self, pcm: bytes) -> None:
        self.stdout.q.put_nowait(pcm)

    def kill(self) -> None:
        self.returncode = -9
        self.stdout.closed = True
        self.stdout.q.put_nowait(b"")

    terminate = kill

    async def wait(self) -> int:
        return self.returncode or 0


def speech_like(dur_s: float, rate: int = 16000, amp: float = 0.2, seed: int = 0) -> bytes:
    """Syllable-modulated harmonic noise burst: a stand-in for speech in demos."""
    r = random.Random(seed)
    n = int(dur_s * rate)
    out = []
    f0 = 120 + r.random() * 60
    for i in range(n):
        t = i / rate
        env = max(0.0, math.sin(2 * math.pi * 3.5 * t)) ** 0.5
        v = sum(math.sin(2 * math.pi * f0 * k * t) / k for k in range(1, 8))
        out.append(int(max(-1, min(1, v * amp * env * 0.4)) * 32767))
    return struct.pack(f"<{n}h", *out)
