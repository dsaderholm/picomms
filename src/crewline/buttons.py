"""Headset button events -> intercom actions.

Principles (from the requirements):

* **Only mappings proven on the actual device are offered.** The hub records
  which button events were *observed* from each endpoint ("learn" mode, or
  simply seen during use). The UI offers only observed events for mapping.
* Audio compatibility does not imply button compatibility. Nothing here is
  assumed for any model; ``PROFILES`` holds *hypotheses* that stay labelled
  "unverified" until observed.
* Essential functions never depend on buttons (web remote, dial codes).

Event sources (each independent, each optional):

``hfp-at``   AT commands the headset sends over its HFP/HSP RFCOMM channel
             (call button, redial, voice-assistant, volume gain). Per device,
             so identical headset models are distinguishable. Captured by
             ``crewline-btsniff`` from ``btmon``. NOT YET VERIFIED on hardware.
``avrcp``    Media keys via BlueZ's uinput device "<device name> (AVRCP)".
             BlueZ sets the device's PHYS field to the *adapter* address, so
             identical models on one adapter cannot be told apart by this source
             alone (see attribute_avrcp()). NOT YET VERIFIED on hardware.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator

from .control import ControlEvent

# Normalised event names a mapping can refer to.
BUTTON_EVENTS = {
    "vol_up", "vol_down", "play_pause", "play", "pause", "next", "prev", "mute_key",
    "call_button",      # AT+CKPD=200 (HSP) / ATA / AT+CHUP depending on call state
    "redial",           # AT+BLDN, commonly the headset's "double press"
    "voice_assist",     # AT+BVRA=1
    "hangup",           # AT+CHUP
    "answer",           # ATA
}
LONG_SUFFIX = ":long"

# Human text for the cheat sheet. Wording is deliberately about the *signal*
# the headset sends, not about what a manufacturer printed on the button.
EVENT_LABELS = {
    "vol_up": "Volume up", "vol_down": "Volume down", "play_pause": "Play/pause key",
    "play": "Play key", "pause": "Pause key", "next": "Next-track key", "prev": "Previous-track key",
    "mute_key": "Mute key", "call_button": "Call/multi-function button", "redial": "Double-press (redial)",
    "voice_assist": "Voice-assistant button", "hangup": "End-call", "answer": "Answer",
}

ACTION_LABELS = {
    "mute:toggle": "Mute / unmute my microphone",
    "talk:toggle": "Start / stop talking (latched)",
    "ptt": "Push-to-talk (hold)",
    "attention": "Call Sound (raises an alert)",
    "allcall:toggle": "All-call on / off",
    "status": "Play my status beep",
}

# Hypotheses for models we know of. These are NOT claims; they are shown as
# "unverified" until the unit is observed.
PROFILES = {
    "jlab-go-work": {
        "title": "JLab GO Work (on-ear headset with boom)",
        "known_local": [
            "Quick Mute button with mic LED: mutes the microphone INSIDE the headset. The intercom "
            "cannot see this press (it just hears silence).",
        ],
        "expected_unverified": ["vol_up", "vol_down", "call_button"],
        "source": "manufacturer product page (feature list); signals to the host not documented",
    },
}


@dataclass
class Observed:
    count: int = 0
    last: float = 0.0
    source: str = ""


@dataclass
class ButtonEvent:
    endpoint: str
    event: str                     # normalised name or "raw:<text>"
    phase: str = "tap"             # "press" | "release" | "tap"
    source: str = ""               # "hfp-at" | "avrcp" | "web" ...
    raw: str = ""


# --------------------------------------------------------------------------- AT -> events
_AT_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^AT\+CKPD=200"), "call_button"),
    (re.compile(r"^AT\+BLDN"), "redial"),
    (re.compile(r"^AT\+BVRA=1"), "voice_assist"),
    (re.compile(r"^AT\+CHUP"), "hangup"),
    (re.compile(r"^ATA\b"), "answer"),
]
_VGS = re.compile(r"^AT\+VGS=(\d+)")


class AtTranslator:
    """Turns HFP AT strings into normalised button events (stateful for volume)."""

    def __init__(self) -> None:
        self._vgs: dict[str, int] = {}

    def translate(self, address: str, at: str) -> list[tuple[str, str]]:
        """Return [(event, raw)]. Unknown commands are returned as raw:<at> so learn
        mode can show them to the administrator without guessing a meaning."""
        at = at.strip()
        if not at or at.startswith(("AT+BRSF", "AT+BAC", "AT+CIND", "AT+CMER", "AT+CHLD=?",
                                    "AT+BIND", "AT+BIEV", "AT+XAPL", "AT+IPHONEACCEV", "AT+XEVENT",
                                    "AT+NREC", "AT+CLIP", "AT+CCWA", "AT+CMEE", "AT+COPS", "AT+CNUM",
                                    "AT+BCS", "AT+BCC", "AT+BIA", "AT+CLCC", "AT+VGM")):
            return []                       # connection housekeeping, not buttons
        m = _VGS.match(at)
        if m:
            v = int(m.group(1))
            prev = self._vgs.get(address)
            self._vgs[address] = v
            if prev is None or v == prev:
                return []                   # first report after connect / no change
            return [("vol_up" if v > prev else "vol_down", at)]
        for pat, name in _AT_MAP:
            if pat.match(at):
                return [(name, at)]
        return [(f"raw:{at[:40]}", at)]


# --------------------------------------------------------------------------- btmon parsing
_HANDLE_ADDR = re.compile(r"Handle:\s*(\d+)\s+Address:\s*([0-9A-Fa-f:]{17})")
_ACL_HANDLE = re.compile(r"ACL Data (?:RX|TX):\s*Handle\s+(\d+)")
_HEXLINE = re.compile(r"^\s+((?:[0-9a-f]{2} )+)\s*(.*)$")


class BtmonParser:
    """Incremental parser: feed btmon text lines, get (address, AT command) tuples.

    btmon marks host-received ACL as ``> ACL Data RX``. The ASCII column of a
    hex dump line carries the AT command. Handle->address is learned from
    connection-complete events. FORMAT FROM MEMORY OF BTMON'S TEXT OUTPUT:
    validate against real captures (validation test T5) before relying on it.
    """

    def __init__(self) -> None:
        self.handles: dict[str, str] = {}
        self.cur: str | None = None
        self.buf = ""

    def feed(self, line: str) -> list[tuple[str, str]]:
        m = _HANDLE_ADDR.search(line)
        if m:
            self.handles[m.group(1)] = m.group(2).upper()
        m = _ACL_HANDLE.search(line)
        if m and line.lstrip().startswith(">"):
            self.cur, self.buf = self.handles.get(m.group(1)), ""
            return []
        if line.lstrip().startswith(("<", ">", "@", "=")) and "ACL Data" not in line:
            self.cur, self.buf = None, ""
            return []
        if self.cur is None:
            return []
        hm = _HEXLINE.match(line)
        if not hm:
            return []
        self.buf += hm.group(2)
        out = []
        for cmd in re.findall(r"(AT[+A-Za-z0-9=,?;*#\-\. ]+?)(?:\.|\r|$)", self.buf):
            if cmd.startswith("AT"):
                out.append((self.cur, cmd))
                self.buf = ""
                break
        return out


def parse_btmon(lines: Iterable[str]) -> Iterator[tuple[str, str]]:
    p = BtmonParser()
    for line in lines:
        yield from p.feed(line)


# --------------------------------------------------------------------------- AVRCP evdev attribution
KEY_TO_EVENT = {
    "KEY_VOLUMEUP": "vol_up", "KEY_VOLUMEDOWN": "vol_down", "KEY_PLAYCD": "play",
    "KEY_PAUSECD": "pause", "KEY_PLAYPAUSE": "play_pause", "KEY_NEXTSONG": "next",
    "KEY_PREVIOUSSONG": "prev", "KEY_MUTE": "mute_key",
}


def attribute_avrcp(device_name: str, adapter: str, candidates: list[dict]) -> str | None:
    """Pick the endpoint id an AVRCP uinput device belongs to.

    ``candidates``: [{"id", "name" (BlueZ remote name), "adapter"}] of connected
    endpoints. Returns an id only if (name, adapter) identifies exactly one;
    otherwise None -- we refuse to guess between identical headsets.
    """
    base = device_name.removesuffix(" (AVRCP)")
    match = [c for c in candidates if c["name"] == base and (not adapter or c.get("adapter") == adapter)]
    return match[0]["id"] if len(match) == 1 else None


# --------------------------------------------------------------------------- hub
class ButtonHub:
    LONG_PRESS_S = 0.7

    def __init__(self, cfg_get, apply: Callable[[ControlEvent], None], clock=time.monotonic) -> None:
        self._cfg = cfg_get
        self._apply = apply
        self._clock = clock
        self.observed: dict[str, dict[str, Observed]] = {}
        self.learning: dict[str, float] = {}          # endpoint -> until
        self._down: dict[tuple[str, str], float] = {}
        self._ptt_held: set[str] = set()

    def start_learning(self, eid: str, seconds: float = 30.0) -> None:
        self.learning[eid] = self._clock() + seconds

    def learning_left(self, eid: str) -> float:
        return max(0.0, self.learning.get(eid, 0) - self._clock())

    def observed_list(self, eid: str) -> list[dict]:
        return [{"event": k, "count": v.count, "source": v.source}
                for k, v in sorted(self.observed.get(eid, {}).items())]

    def feed(self, ev: ButtonEvent) -> list[ControlEvent]:
        """Record the event (always) and, outside learn mode, run its mapped action."""
        obs = self.observed.setdefault(ev.endpoint, {}).setdefault(ev.event, Observed())
        if ev.phase in ("press", "tap"):
            obs.count += 1
        obs.last, obs.source = self._clock(), ev.source
        key = (ev.endpoint, ev.event)
        held_s = 0.0
        if ev.phase == "press":
            self._down[key] = self._clock()
        elif ev.phase == "release":
            t0 = self._down.pop(key, None)
            held_s = (self._clock() - t0) if t0 is not None else 0.0

        ep = self._cfg().endpoint(ev.endpoint)
        if ep is None or not ep.enabled or self.learning.get(ep.id, 0) > self._clock():
            return []                       # while learning, real actions are suppressed
        short = ep.buttons.get(ev.event)
        long_ = ep.buttons.get(ev.event + LONG_SUFFIX)
        out: list[ControlEvent] = []

        def run(action: str) -> None:
            out.append(ControlEvent(ep.id, action, "button"))

        if short == "ptt":
            if ev.phase == "press":
                run("ptt:down")
            elif ev.phase == "release":
                run("ptt:up")
        elif ev.phase == "tap":
            if short:
                run(short)
        elif ev.phase == "press":
            if short and not long_:
                run(short)                  # no long mapping: act immediately
        elif ev.phase == "release":
            if long_:
                if held_s >= self.LONG_PRESS_S:
                    run(long_)
                elif short:
                    run(short)
        for c in out:
            self._apply(c)
        return out
