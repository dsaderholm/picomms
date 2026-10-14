"""In-band DTMF (touch-tone) decoder using the Goertzel algorithm.

Why custom code here: the decoder must sit *in the live path* of one endpoint
(the rotary phone) so that command tones can be gated out before they are
broadcast, and so the detection thresholds can be tuned against real
Cell2Jack audio. The algorithm is textbook (Goertzel per DTMF frequency,
dominance + twist + harmonic checks, minimum duration); no audio plumbing is
re-implemented -- samples arrive from PipeWire via ``pw-cat``.

Events produced (times are seconds of *stream* time):

* ``gate_on``   first frame that looks like a DTMF tone (suppress TX now)
* ``digit``     a tone lasted at least ``min_tone_ms``: a real key press
* ``gate_off``  tone ended and ``gate_hold_ms`` has elapsed

False-trigger ("talk-off") behaviour on speech is measured in
``tests/test_dtmf.py`` and ``docs/04-validation-plan.md``. This decoder is
unverified against real Cell2Jack audio until test T4 is run.
"""

from __future__ import annotations

import math
from array import array
from dataclasses import dataclass

ROWS = (697.0, 770.0, 852.0, 941.0)
COLS = (1209.0, 1336.0, 1477.0, 1633.0)
KEYS = (
    ("1", "2", "3", "A"),
    ("4", "5", "6", "B"),
    ("7", "8", "9", "C"),
    ("*", "0", "#", "D"),
)


@dataclass(frozen=True)
class DtmfEvent:
    kind: str            # "gate_on" | "digit" | "gate_off"
    t: float             # stream time in seconds
    digit: str = ""
    duration: float = 0.0


def _goertzel_power(samples: list[float], coeff: float) -> float:
    s1 = s2 = 0.0
    for x in samples:
        s0 = x + coeff * s1 - s2
        s2 = s1
        s1 = s0
    return s1 * s1 + s2 * s2 - coeff * s1 * s2


class DtmfDecoder:
    def __init__(
        self,
        rate: int = 16000,
        frame_ms: int = 20,
        min_tone_ms: int = 40,
        gate_hold_ms: int = 150,
        min_level: float = 0.003,        # per-frame RMS (0..1 full scale) below which we skip
        dominance: float = 4.0,          # winning bin vs runner-up in its group (power ratio)
        purity: float = 0.55,            # (row+col power) / total frame power -- speech is broadband
        max_normal_twist_db: float = 8.0,
        max_reverse_twist_db: float = 4.0,
        max_harmonic_ratio: float = 0.25,  # 2nd-harmonic power / fundamental power
        release_frames: int = 2,
    ) -> None:
        self.rate = rate
        self.frame = rate * frame_ms // 1000
        self.frame_s = self.frame / rate
        self.min_frames = max(1, math.ceil(min_tone_ms / frame_ms))
        self.hold_frames = math.ceil(gate_hold_ms / frame_ms)
        self.min_level = min_level
        self.dominance = dominance
        self.purity = purity
        self.max_normal = 10 ** (max_normal_twist_db / 10)
        self.max_reverse = 10 ** (max_reverse_twist_db / 10)
        self.max_harm = max_harmonic_ratio
        self.release_frames = release_frames

        self._coef = {f: 2 * math.cos(2 * math.pi * f / rate) for f in ROWS + COLS}
        self._coef2 = {f: 2 * math.cos(2 * math.pi * 2 * f / rate) for f in ROWS + COLS}

        self._buf = array("h")
        self._frame_idx = 0          # frames processed so far
        # tone state machine
        self._cand: str | None = None
        self._cand_frames = 0
        self._cand_start_frame = 0
        self._emitted = False
        self._miss = 0
        self._gate = False
        self._gate_release_at = -1   # frame index at which gate drops
        self._last_tone_frame = -1
        # Optional diagnostics: called with a dict for every non-silent frame.
        # Used by `picomms-probe dtmf-scan` to tune thresholds on real audio.
        self.on_frame = None

    @property
    def gate_active(self) -> bool:
        return self._gate

    # -- per-frame classification ------------------------------------------
    def _classify(self, frame: list[float]) -> str | None:
        n = len(frame)
        total = sum(x * x for x in frame)
        # Mean-square in full-scale units, and skip silence cheaply.
        if total / n < (self.min_level * 32768.0) ** 2:
            return None
        pw_r = [_goertzel_power(frame, self._coef[f]) for f in ROWS]
        pw_c = [_goertzel_power(frame, self._coef[f]) for f in COLS]
        ri = max(range(4), key=pw_r.__getitem__)
        ci = max(range(4), key=pw_c.__getitem__)
        pr, pc = pw_r[ri], pw_c[ci]
        r2 = max(p for i, p in enumerate(pw_r) if i != ri)
        c2 = max(p for i, p in enumerate(pw_c) if i != ci)
        info = None
        if self.on_frame is not None:
            info = {
                "frame": self._frame_idx, "t": self._t(self._frame_idx),
                "rms_db": 10 * math.log10(max(1e-12, total / n / 32768.0 ** 2)),
                "row_hz": ROWS[ri], "col_hz": COLS[ci],
                "row_dom_db": 10 * math.log10(max(1e-12, pr / max(r2, 1e-12))),
                "col_dom_db": 10 * math.log10(max(1e-12, pc / max(c2, 1e-12))),
                "twist_db": 10 * math.log10(max(1e-12, pr) / max(1e-12, pc)),
                "purity": 2.0 * (pr + pc) / n / max(total, 1e-12), "result": "", "digit": "",
            }

        def reject(why: str):
            if info is not None:
                info["result"] = why
                self.on_frame(info)
            return None

        # Dominance inside each group.
        if pr < self.dominance * r2 or pc < self.dominance * c2:
            return reject("not-dominant")
        # Purity: the two tones must carry most of the frame's energy.
        # A sinusoid of amplitude A over n samples has Goertzel power
        # (A*n/2)^2 and time-domain energy A^2*n/2, i.e. energy = 2*power/n.
        tone_energy = 2.0 * (pr + pc) / n
        if tone_energy < self.purity * total:
            return reject("impure")
        # Twist: normal = row (low group) stronger than column; reverse = the opposite.
        if pc / pr > self.max_reverse:
            return reject("reverse-twist")
        if pr / pc > self.max_normal:
            return reject("normal-twist")
        # Second-harmonic rejection: pure tones have none; voiced speech does.
        if _goertzel_power(frame, self._coef2[ROWS[ri]]) > self.max_harm * pr:
            return reject("harmonic")
        if _goertzel_power(frame, self._coef2[COLS[ci]]) > self.max_harm * pc:
            return reject("harmonic")
        d = KEYS[ri][ci]
        if info is not None:
            info["result"], info["digit"] = "ok", d
            self.on_frame(info)
        return d

    # -- streaming interface -------------------------------------------------
    def feed(self, pcm: bytes) -> list[DtmfEvent]:
        """Feed little-endian signed 16-bit mono PCM; return new events."""
        chunk = array("h")
        chunk.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
        self._buf.extend(chunk)
        events: list[DtmfEvent] = []
        while len(self._buf) >= self.frame:
            frame = [float(x) for x in self._buf[: self.frame]]
            del self._buf[: self.frame]
            events.extend(self._step(self._classify(frame)))
        return events

    def _t(self, frame_idx: int) -> float:
        return frame_idx * self.frame_s

    def _step(self, digit: str | None) -> list[DtmfEvent]:
        ev: list[DtmfEvent] = []
        idx = self._frame_idx
        self._frame_idx += 1

        if digit is not None:
            self._last_tone_frame = idx
            self._miss = 0
            if digit == self._cand:
                self._cand_frames += 1
            else:
                # A changed digit without a gap restarts the candidate.
                if self._cand is not None and self._emitted:
                    ev.extend(self._end_tone(idx))
                self._cand = digit
                self._cand_frames = 1
                self._cand_start_frame = idx
                self._emitted = False
            if not self._gate:
                self._gate = True
                ev.append(DtmfEvent("gate_on", self._t(idx)))
            self._gate_release_at = idx + self.hold_frames + 1
            if not self._emitted and self._cand_frames >= self.min_frames:
                self._emitted = True
                ev.append(DtmfEvent("digit", self._t(self._cand_start_frame), digit))
        else:
            if self._cand is not None:
                self._miss += 1
                if self._miss >= self.release_frames:
                    ev.extend(self._end_tone(idx))
            if self._gate and idx >= self._gate_release_at:
                self._gate = False
                ev.append(DtmfEvent("gate_off", self._t(idx)))
        return ev

    def _end_tone(self, idx: int) -> list[DtmfEvent]:
        self._cand = None
        self._cand_frames = 0
        self._emitted = False
        self._miss = 0
        return []
