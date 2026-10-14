"""DTMF events -> control events (prefix handling, mapping, timeouts)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from .control import ControlEvent
from .dtmf import DtmfEvent
from .model import Config


@dataclass
class DtmfResult:
    # True/False when the tone gate (suppress this endpoint's TX) should change.
    gate: bool | None = None
    controls: list[ControlEvent] | None = None


class DtmfCommandHandler:
    """Per-endpoint interpreter. One instance per tone-controlled endpoint."""

    def __init__(
        self,
        endpoint_id: str,
        cfg_get: Callable[[], Config],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.endpoint_id = endpoint_id
        self._cfg = cfg_get
        self._clock = clock
        self._armed_until = 0.0
        self._buf = ""
        self._buf_t = 0.0

    def handle(self, ev: DtmfEvent) -> DtmfResult:
        if ev.kind == "gate_on":
            return DtmfResult(gate=True)
        if ev.kind == "gate_off":
            return DtmfResult(gate=False)
        if ev.kind != "digit":
            return DtmfResult()

        d = self._cfg().dtmf
        digit = ev.digit
        now = self._clock()
        if self._buf and now - self._buf_t > d.digit_timeout_s:
            self._buf = ""
        if d.prefix and not self._buf:
            if digit == d.prefix and now >= self._armed_until:
                self._armed_until = now + d.prefix_timeout_s
                return DtmfResult()
            if now >= self._armed_until:
                return DtmfResult()      # unarmed digit: ignore (speech talk-off guard)
            if digit == d.prefix:
                self._armed_until = 0.0
                return DtmfResult()
        code = self._buf + digit
        action = d.commands.get(code)
        if action:                       # no code is the start of another, so a match is final
            self._buf, self._armed_until = "", 0.0
            return DtmfResult(controls=[ControlEvent(self.endpoint_id, action, "dtmf")])
        if any(c.startswith(code) for c in d.commands):
            self._buf, self._buf_t = code, now          # wait for the rest of the code
            if d.prefix:
                self._armed_until = now + d.digit_timeout_s
            return DtmfResult()
        self._buf, self._armed_until = "", 0.0
        return DtmfResult()
