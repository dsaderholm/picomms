"""Scripted activity for ``picomms-engine --sim`` (UI development and demos only)."""

from __future__ import annotations

import asyncio
import random

from .control import ControlEvent
from .sim import speech_like

PHRASES = [
    "[simulated] can I get a mic check on stage left",
    "[simulated] standby for cue twelve",
    "[simulated] DJ the spotlight is flickering again",
    "[simulated] copy that, going to black",
]


def _tone(digit: str, dur: float = 0.12) -> bytes:
    import math
    import struct
    rows = {"1": (697, 1209), "2": (697, 1336), "0": (941, 1336), "7": (852, 1209)}
    lo, hi = rows[digit]
    n = int(dur * 16000)
    return struct.pack(f"<{n}h", *[
        int((math.sin(2 * math.pi * lo * i / 16000) + math.sin(2 * math.pi * hi * i / 16000)) * 0.2 * 32767)
        for i in range(n)])


async def run_demo(eng, graph, bt) -> None:
    await asyncio.sleep(0.5)
    cfg = eng.store.config
    if not any(e.address for e in cfg.endpoints):
        eng.store.upsert_endpoint(cfg.endpoint("sound").__dict__ | {"address": "AA:BB:CC:00:00:01"})
        eng.store.upsert_endpoint({
            "id": "alex", "name": "Alex (Stage)", "address": "AA:BB:CC:00:00:02",
            "listen": ["stage"], "talk": ["stage"], "listen_allowed": ["stage", "tech"],
            "talk_allowed": ["stage", "tech"], "talk_mode": "open"})
    rnd = random.Random(7)
    n = 0
    while True:
        await asyncio.sleep(rnd.uniform(2.5, 5))
        n += 1
        tap = graph.taps.get("AA:BB:CC:00:00:02")
        if tap:
            dur = rnd.uniform(1.0, 2.2)
            pcm = speech_like(dur, seed=n)
            for i in range(0, len(pcm), 640):
                tap.push(pcm[i:i + 640])
                await asyncio.sleep(0.02)
            await asyncio.sleep(0.5)
            if eng.captions.enabled is False:
                eng._on_caption({"seg": 9000 + n, "endpoint": "alex", "name": "Alex (Stage)", "group": "stage",
                                 "text": rnd.choice(PHRASES), "final": True})
        if n % 4 == 0:
            tap = graph.taps.get("AA:BB:CC:00:00:01")
            if tap:
                d = rnd.choice("1207")
                pcm = b"\x00\x00" * 1600 + _tone(d) + b"\x00\x00" * 4800
                for i in range(0, len(pcm), 640):
                    tap.push(pcm[i:i + 640])
                    await asyncio.sleep(0.02)
        if n % 7 == 0:
            await eng.control(ControlEvent("alex", "attention", "web"))
