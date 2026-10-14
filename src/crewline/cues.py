"""Audible confirmation cues ("earcons").

Language-free beep patterns, generated as 16-bit mono WAV so no audio assets
or text-to-speech engine are required. A cue is played into the earpiece sink
of the affected endpoint only (never into a group), by linking a short-lived
playback stream to that endpoint's sink node.

Design rules:
* Short (<~0.5 s) and moderate level so they do not startle or mask speech.
* Mention = two quick soft pings (someone said your name).
* Distinct *patterns* rather than distinct pitches, so they stay recognisable
  through the narrowband (8 kHz) HFP codec.
* Private line on = three equal low blips, off = one low tone.
* Group cue = N beeps (N = Group.cue_beeps) at a low/mid/high pitch (3 x 5 = 15 distinct cues). Mute on = descending pair, mute
  off = ascending pair, all-call on = rising triplet, all-call off = falling
  triplet, denied = low double buzz, talk on/off = single high/low blip.
"""

from __future__ import annotations

import io
import math
import struct
import wave

RATE = 16000


def _tone(freq: float, ms: int, level: float = 0.25) -> list[float]:
    n = RATE * ms // 1000
    fade = max(1, RATE * 4 // 1000)  # 4 ms fades avoid clicks
    out = []
    for i in range(n):
        env = min(1.0, i / fade, (n - 1 - i) / fade)
        out.append(math.sin(2 * math.pi * freq * i / RATE) * level * env)
    return out


def _gap(ms: int) -> list[float]:
    return [0.0] * (RATE * ms // 1000)


PITCH_HZ = {"low": 587.0, "mid": 880.0, "high": 1319.0}   # all inside the 300-3400 Hz phone band


def pattern(kind: str, beeps: int = 1, pitch: str = "mid") -> list[float]:
    s: list[float] = []
    if kind == "group":
        for i in range(max(1, beeps)):
            if i:
                s += _gap(70)
            s += _tone(PITCH_HZ[pitch], 90)
    elif kind == "mute_on":
        s = _tone(660, 90) + _gap(30) + _tone(440, 140)
    elif kind == "mute_off":
        s = _tone(440, 90) + _gap(30) + _tone(660, 140)
    elif kind == "allcall_on":
        s = _tone(660, 80) + _gap(20) + _tone(880, 80) + _gap(20) + _tone(1175, 120)
    elif kind == "allcall_off":
        s = _tone(1175, 80) + _gap(20) + _tone(880, 80) + _gap(20) + _tone(660, 120)
    elif kind == "private_on":      # three equal low blips (the all-call cue is a rising triplet)
        s = _tone(587, 70) + _gap(45) + _tone(587, 70) + _gap(45) + _tone(587, 70)
    elif kind == "private_off":
        s = _tone(587, 130)
    elif kind == "talk_on":
        s = _tone(1320, 70)
    elif kind == "talk_off":
        s = _tone(520, 70)
    elif kind == "denied":
        s = _tone(220, 90) + _gap(60) + _tone(220, 90)
    elif kind == "mention":
        # two soft, quick pings: noticeable without being alarming (a call is the urgent one)
        s = _tone(1568, 55, 0.18) + _gap(55) + _tone(1976, 85, 0.18)
    elif kind == "attention_ack":
        s = _tone(988, 60) + _gap(30) + _tone(1319, 120)
    elif kind == "ring":
        for _ in range(3):
            s += _tone(1000, 120, 0.2) + _gap(80) + _tone(1400, 120, 0.2) + _gap(200)
    elif kind == "status":
        s = _tone(740, 60) + _gap(40) + _tone(740, 60)
    else:
        raise ValueError(f"unknown cue kind {kind!r}")
    return s


def render_wav(kind: str, beeps: int = 1, pitch: str = "mid") -> bytes:
    samples = pattern(kind, beeps, pitch)
    pcm = b"".join(struct.pack("<h", int(max(-1.0, min(1.0, x)) * 32767)) for x in samples)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return buf.getvalue()


def duration_s(kind: str, beeps: int = 1) -> float:
    return len(pattern(kind, beeps)) / RATE
