import math
import random
import struct
import wave
from pathlib import Path

import pytest

DATA = Path(__file__).parent / "data"
RATE = 16000


def tone_pcm(freqs, dur_s, amp=0.3, rate=RATE):
    n = int(dur_s * rate)
    out = []
    for i in range(n):
        v = sum(math.sin(2 * math.pi * f * i / rate) for f in freqs) / len(freqs)
        out.append(int(max(-1, min(1, v * amp)) * 32767))
    return struct.pack(f"<{n}h", *out)


def silence_pcm(dur_s, rate=RATE):
    return b"\x00\x00" * int(dur_s * rate)


def noise_pcm(dur_s, amp=0.01, seed=1, rate=RATE):
    r = random.Random(seed)
    n = int(dur_s * rate)
    return struct.pack(f"<{n}h", *[int(r.gauss(0, amp) * 32767) for _ in range(n)])


def mix_pcm(a: bytes, b: bytes) -> bytes:
    n = min(len(a), len(b)) // 2
    xa = struct.unpack(f"<{n}h", a[: 2 * n])
    xb = struct.unpack(f"<{n}h", b[: 2 * n])
    return struct.pack(f"<{n}h", *[max(-32768, min(32767, x + y)) for x, y in zip(xa, xb)])


DTMF = {
    "1": (697, 1209), "2": (697, 1336), "3": (697, 1477), "A": (697, 1633),
    "4": (770, 1209), "5": (770, 1336), "6": (770, 1477), "B": (770, 1633),
    "7": (852, 1209), "8": (852, 1336), "9": (852, 1477), "C": (852, 1633),
    "*": (941, 1209), "0": (941, 1336), "#": (941, 1477), "D": (941, 1633),
}


def dtmf_pcm(digit, dur_s=0.1, amp=0.3, twist_db=0.0):
    """twist_db > 0 makes the high tone quieter than the low tone (normal twist)."""
    lo, hi = DTMF[digit]
    n = int(dur_s * RATE)
    g = 10 ** (-twist_db / 20)
    out = [
        int((math.sin(2 * math.pi * lo * i / RATE) * 0.5 + g * math.sin(2 * math.pi * hi * i / RATE) * 0.5) * amp * 32767)
        for i in range(n)
    ]
    return struct.pack(f"<{n}h", *out)


@pytest.fixture(scope="session")
def jfk_pcm() -> bytes:
    with wave.open(str(DATA / "jfk_16k.wav")) as w:
        assert w.getframerate() == RATE and w.getnchannels() == 1
        return w.readframes(w.getnframes())
