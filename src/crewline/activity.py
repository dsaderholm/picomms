"""Speaking-activity detection and caption segmentation.

*These never alter or gate the audio that crew members hear.* They look at a
tap (a copy) of each microphone to drive the "who is speaking" indicators and
to cut speech segments for the caption service. Because whispers matter, the
detector is relative to a tracked noise floor with a very low absolute floor,
and the segmenter keeps a pre-roll so sentence onsets are not clipped.
"""

from __future__ import annotations

import math
from array import array
from collections import deque
from dataclasses import dataclass


def rms_dbfs(samples: array) -> float:
    if not samples:
        return -120.0
    acc = 0
    for s in samples:
        acc += s * s
    ms = acc / len(samples)
    if ms <= 0:
        return -120.0
    return 10 * math.log10(ms / (32768.0 ** 2))


class ActivityMeter:
    """Noise-floor-relative voice activity with hysteresis. Frame based (20 ms)."""

    def __init__(
        self,
        rate: int = 16000,
        frame_ms: int = 20,
        on_margin_db: float = 9.0,
        off_margin_db: float = 5.0,
        abs_floor_db: float = -62.0,       # quieter than this is never "speech"
        hangover_ms: int = 400,
        floor_rise_db_per_s: float = 6.0,      # floor adaptation while idle
        speaking_rise_db_per_s: float = 1.0,   # slower while speaking, but never stuck
        calibrate_ms: int = 300,
    ) -> None:
        self.frame = rate * frame_ms // 1000
        self.frame_s = frame_ms / 1000
        self.on_margin = on_margin_db
        self.off_margin = off_margin_db
        self.abs_floor = abs_floor_db
        self.hang_frames = hangover_ms // frame_ms
        self.rise = floor_rise_db_per_s * self.frame_s
        self.rise_speaking = speaking_rise_db_per_s * self.frame_s
        self.calibrate_frames = calibrate_ms // frame_ms
        self.noise_floor = -70.0
        self.level = -120.0
        self.speaking = False
        self._hang = 0
        self._buf = array("h")
        self.frames = 0

    def feed_frames(self, pcm: bytes) -> list[tuple[array, float, bool]]:
        """Return a list of (frame, level_db, speaking) for each complete frame."""
        chunk = array("h")
        chunk.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
        self._buf.extend(chunk)
        out = []
        while len(self._buf) >= self.frame:
            frame = array("h", self._buf[: self.frame])
            del self._buf[: self.frame]
            out.append((frame, *self._step(frame)))
        return out

    def _step(self, frame: array) -> tuple[float, bool]:
        lvl = rms_dbfs(frame)
        self.level = lvl
        self.frames += 1
        # Noise floor: snaps to the level during a short start-up calibration,
        # then follows quiet passages down immediately and creeps up slowly, so
        # steady room noise can never leave the detector stuck on.
        if self.frames <= self.calibrate_frames or lvl < self.noise_floor:
            self.noise_floor = lvl
        else:
            step = self.rise_speaking if self.speaking else self.rise
            self.noise_floor = min(lvl, self.noise_floor + step)
        thr_on = max(self.noise_floor + self.on_margin, self.abs_floor)
        thr_off = max(self.noise_floor + self.off_margin, self.abs_floor - 3)
        if self.speaking:
            if lvl >= thr_off:
                self._hang = self.hang_frames
            elif self._hang > 0:
                self._hang -= 1
            else:
                self.speaking = False
        elif lvl >= thr_on:
            self.speaking = True
            self._hang = self.hang_frames
        return lvl, self.speaking


@dataclass
class SegmentEvent:
    kind: str            # "start" | "audio" | "end"
    pcm: bytes = b""


class Segmenter:
    """Cuts speech segments (with pre-roll) out of a frame stream for captioning."""

    def __init__(self, preroll_ms: int = 500, frame_ms: int = 20, max_segment_s: float = 25.0) -> None:
        self.preroll: deque[bytes] = deque(maxlen=max(1, preroll_ms // frame_ms))
        self.in_segment = False
        self.max_frames = int(max_segment_s * 1000 / frame_ms)
        self._count = 0

    def push(self, frame: bytes, speaking: bool) -> list[SegmentEvent]:
        ev: list[SegmentEvent] = []
        if speaking and not self.in_segment:
            self.in_segment = True
            self._count = 0
            ev.append(SegmentEvent("start"))
            if self.preroll:
                ev.append(SegmentEvent("audio", b"".join(self.preroll)))
            self.preroll.clear()
            ev.append(SegmentEvent("audio", frame))
            self._count = 1
        elif self.in_segment:
            ev.append(SegmentEvent("audio", frame))
            self._count += 1
            if not speaking or self._count >= self.max_frames:
                self.in_segment = False
                ev.append(SegmentEvent("end"))
        else:
            self.preroll.append(frame)
        return ev
