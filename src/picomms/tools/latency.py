"""Latency measurement helpers.

Measurement method (see docs/04-validation-plan.md T10): record TWO channels on
one device with one clock -- channel 1 is a direct electrical copy of a click
train, channel 2 is a microphone placed against the *listening* headset's ear
cup. The click train is played into the *talking* headset's microphone
(speaker next to its boom mic). The delay between channel-1 clicks and the
channel-2 clicks is the end-to-end mouth-to-ear latency, including both
Bluetooth hops, minus the fixed acoustic paths (calibrate those with a
reference run, see the doc).
"""

from __future__ import annotations

import math
import statistics
import struct
import wave


def click_train_wav(path: str, count: int = 20, interval_s: float = 1.0, rate: int = 16000) -> None:
    """A train of short, band-limited clicks (2 ms, 1 kHz burst) that survive 8 kHz codecs."""
    n = int(interval_s * rate) * count + rate
    pcm = [0] * n
    burst = int(0.004 * rate)
    for k in range(count):
        start = int((0.5 + k * interval_s) * rate)
        for i in range(burst):
            env = math.sin(math.pi * i / burst)
            pcm[start + i] = int(0.8 * 32767 * env * math.sin(2 * math.pi * 1000 * i / rate))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{n}h", *pcm))


def _onsets(x: list[float], rate: int, min_gap_s: float = 0.3, rel_thresh: float = 0.35) -> list[float]:
    """Times (s) where the smoothed envelope first exceeds a fraction of its peak."""
    win = max(1, rate // 1000)               # 1 ms smoothing
    env = []
    acc = 0.0
    q = [0.0] * win
    for i, v in enumerate(x):
        a = abs(v)
        acc += a - q[i % win]
        q[i % win] = a
        env.append(acc / win)
    peak = max(env) if env else 0.0
    if peak <= 0:
        return []
    thr = peak * rel_thresh
    out: list[float] = []
    last = -1e9
    for i, e in enumerate(env):
        if e >= thr and i / rate - last >= min_gap_s:
            out.append(i / rate)
            last = i / rate
    return out


def analyze_stereo(path: str) -> dict:
    """Return per-click delays (ms) between channel 1 (reference) and channel 2 (captured)."""
    with wave.open(path) as w:
        assert w.getnchannels() == 2 and w.getsampwidth() == 2, "need a 16-bit stereo WAV"
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
    data = struct.unpack(f"<{len(raw) // 2}h", raw)
    ref = [float(v) for v in data[0::2]]
    cap = [float(v) for v in data[1::2]]
    t_ref, t_cap = _onsets(ref, rate), _onsets(cap, rate)
    delays = []
    for t in t_ref:
        later = [c for c in t_cap if c >= t - 0.001]
        if later and later[0] - t < 1.5:
            delays.append((later[0] - t) * 1000.0)
    if not delays:
        return {"clicks_ref": len(t_ref), "clicks_cap": len(t_cap), "matched": 0}
    delays.sort()
    return {
        "clicks_ref": len(t_ref), "clicks_cap": len(t_cap), "matched": len(delays),
        "median_ms": round(statistics.median(delays), 1),
        "p95_ms": round(delays[min(len(delays) - 1, int(0.95 * len(delays)))], 1),
        "min_ms": round(delays[0], 1), "max_ms": round(delays[-1], 1),
        "jitter_ms": round(statistics.pstdev(delays), 1) if len(delays) > 1 else 0.0,
        "note": "subtract the calibrated fixed path (reference run) before quoting",
    }
