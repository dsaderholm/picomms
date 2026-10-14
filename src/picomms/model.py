"""Configuration model: groups, endpoints, permissions, show-mode lock.

This module is pure data + validation. Nothing here touches Bluetooth or
audio, so it can be unit-tested and reused by every process (engine, web,
tools).

Vocabulary (these three are deliberately different things):

* **Config lock ("show mode")** -- blocks *configuration* changes (pairing,
  renaming, group membership, permissions, button mappings). It never stops
  anyone from hearing or from using their normal talk controls.
* **Mute** -- an endpoint's *transmission* is suppressed. Self-service
  (software mute) or admin-enforced (``forced_mute``). A muted endpoint still
  hears everything it is entitled to hear.
* **Lockout** -- intentionally NOT implemented as "stop hearing". The
  strongest thing an admin can do from the UI is ``forced_mute`` or
  ``enabled = False`` (which is explicit and visible on the dashboard).
  Removing someone's ability to hear essential communications is never a side
  effect of a lock.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any

SCHEMA_VERSION = 1

MAC_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")

TALK_MODES = ("open", "latched", "ptt")
KINDS = ("headset", "rotary", "other")
SELECT_SCOPES = ("talk", "both")

# The ceiling on what "all-call" may be, kept as a tiny enum-like tuple so the
# UI can offer it. "latched" = stays on until switched off or timeout.
ALLCALL_STYLES = ("latched", "momentary")


class ConfigError(ValueError):
    """Raised when a configuration value is invalid."""


class ConfigLocked(PermissionError):
    """Raised when a configuration change is attempted in show mode."""


def normalize_mac(mac: str) -> str:
    m = mac.strip().upper().replace("-", ":").replace("_", ":")
    if not MAC_RE.match(m):
        raise ConfigError(f"invalid Bluetooth address: {mac!r}")
    return m


@dataclass
class Group:
    id: str
    name: str
    # Number of short beeps used as the audible group cue (language-free).
    cue_beeps: int = 1

    def validate(self) -> None:
        if not ID_RE.match(self.id):
            raise ConfigError(f"invalid group id {self.id!r}")
        if not self.name.strip():
            raise ConfigError("group name is empty")
        if not 1 <= self.cue_beeps <= 5:
            raise ConfigError("cue_beeps must be 1..5")


@dataclass
class Endpoint:
    id: str
    name: str
    kind: str = "headset"
    # Bluetooth address. None for endpoints that are not Bluetooth (reserved).
    address: str | None = None
    # Address of the adapter this endpoint is bonded to (informational and
    # used by the pairing UI so the same adapter is always used).
    adapter: str | None = None
    enabled: bool = True

    # Group membership at boot ("home" selection) ...
    listen: list[str] = field(default_factory=list)
    talk: list[str] = field(default_factory=list)
    # ... and the permission ceiling: what the endpoint may *select* at run time.
    listen_allowed: list[str] = field(default_factory=list)
    talk_allowed: list[str] = field(default_factory=list)

    can_allcall: bool = False
    # May this endpoint change its own group selection with its controls?
    can_select: bool = True
    # What does "select group X" change when the endpoint issues it?
    select_scope: str = "talk"

    talk_mode: str = "open"
    # Administrator-enforced transmit mute (explicit, visible, reversible).
    forced_mute: bool = False

    # Does this endpoint carry DTMF commands in-band (rotary phone)?
    tone_control: bool = False
    # Verified button -> action mapping. Empty unless proven on the hardware.
    buttons: dict[str, str] = field(default_factory=dict)

    # Should this endpoint's microphone be sent to the caption service?
    captions: bool = True

    def validate(self, group_ids: set[str]) -> None:
        if not ID_RE.match(self.id):
            raise ConfigError(f"invalid endpoint id {self.id!r}")
        if not self.name.strip():
            raise ConfigError("endpoint name is empty")
        if self.kind not in KINDS:
            raise ConfigError(f"unknown kind {self.kind!r}")
        if self.address is not None:
            self.address = normalize_mac(self.address)
        if self.adapter is not None:
            self.adapter = normalize_mac(self.adapter)
        if self.talk_mode not in TALK_MODES:
            raise ConfigError(f"unknown talk mode {self.talk_mode!r}")
        if self.select_scope not in SELECT_SCOPES:
            raise ConfigError(f"unknown select scope {self.select_scope!r}")
        for label, ids in (
            ("listen", self.listen),
            ("talk", self.talk),
            ("listen_allowed", self.listen_allowed),
            ("talk_allowed", self.talk_allowed),
        ):
            unknown = set(ids) - group_ids
            if unknown:
                raise ConfigError(f"{self.id}: {label} references unknown groups {sorted(unknown)}")
        if not set(self.listen) <= set(self.listen_allowed):
            raise ConfigError(f"{self.id}: default listen groups exceed listen_allowed")
        if not set(self.talk) <= set(self.talk_allowed):
            raise ConfigError(f"{self.id}: default talk groups exceed talk_allowed")


@dataclass
class DtmfSettings:
    """Tone-command settings. All values are tunables to be set from tests."""

    # Single-digit commands map straight to actions. When ``prefix`` is set the
    # command is only accepted as prefix + digit (e.g. "*1"), which makes
    # accidental activation by speech very unlikely.
    prefix: str = ""
    # Seconds a prefix stays armed.
    prefix_timeout_s: float = 3.0
    # Minimum tone duration (ms) before a digit counts.
    min_tone_ms: int = 40
    # Hold the endpoint's transmission closed while a tone is present (and for
    # this many ms afterwards) so command tones are not broadcast.
    gate_hold_ms: int = 150
    # digit -> action string. Proposals only; to be confirmed by the user.
    commands: dict[str, str] = field(
        default_factory=lambda: {
            "1": "select:tech",
            "2": "select:stage",
            "0": "allcall:toggle",
            "7": "mute:toggle",
            "8": "status",
        }
    )
    # All-call auto-expiry (s). 0 disables expiry.
    allcall_timeout_s: float = 20.0
    allcall_style: str = "latched"


@dataclass
class CaptionSettings:
    # Host:port of the caption server (may be a different computer). Empty =
    # captions disabled; audio is unaffected either way.
    server: str = ""
    # Highlight these words in captions (supplementary only).
    highlight_terms: list[str] = field(default_factory=lambda: ["DJ"])
    # Retention is OFF unless explicitly enabled. Both flags default False.
    retain_transcripts: bool = False
    retain_audio: bool = False


@dataclass
class Config:
    schema: int = SCHEMA_VERSION
    show_mode: bool = False
    groups: list[Group] = field(default_factory=list)
    endpoints: list[Endpoint] = field(default_factory=list)
    dtmf: DtmfSettings = field(default_factory=DtmfSettings)
    captions: CaptionSettings = field(default_factory=CaptionSettings)
    # Attention target: which endpoint id is "Sound" (the one alerts are for).
    attention_target: str = ""

    # --- helpers -----------------------------------------------------------
    def group(self, gid: str) -> Group | None:
        return next((g for g in self.groups if g.id == gid), None)

    def endpoint(self, eid: str) -> Endpoint | None:
        return next((e for e in self.endpoints if e.id == eid), None)

    def endpoint_by_address(self, addr: str) -> Endpoint | None:
        addr = normalize_mac(addr)
        return next((e for e in self.endpoints if e.address == addr), None)

    def validate(self) -> None:
        if self.schema != SCHEMA_VERSION:
            raise ConfigError(f"unsupported schema {self.schema}")
        gids = [g.id for g in self.groups]
        if len(set(gids)) != len(gids):
            raise ConfigError("duplicate group ids")
        for g in self.groups:
            g.validate()
        eids = [e.id for e in self.endpoints]
        if len(set(eids)) != len(eids):
            raise ConfigError("duplicate endpoint ids")
        names = [e.name.strip().lower() for e in self.endpoints]
        if len(set(names)) != len(names):
            raise ConfigError("duplicate endpoint names")
        for e in self.endpoints:
            e.validate(set(gids))
        addrs = [e.address for e in self.endpoints if e.address]
        if len(set(addrs)) != len(addrs):
            raise ConfigError("duplicate Bluetooth addresses")
        if self.attention_target and self.attention_target not in eids:
            raise ConfigError("attention_target is not a known endpoint")
        if self.captions.retain_audio:
            raise ConfigError("audio retention is not implemented in this version")
        if self.dtmf.allcall_style not in ALLCALL_STYLES:
            raise ConfigError("unknown allcall_style")
        if self.dtmf.prefix and self.dtmf.prefix not in "0123456789*#ABCD":
            raise ConfigError("invalid DTMF prefix")
        for digit, action in self.dtmf.commands.items():
            if digit not in "0123456789*#ABCD" or len(digit) != 1:
                raise ConfigError(f"invalid DTMF digit {digit!r}")
            validate_action(action, set(gids))

    # --- (de)serialisation -------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Config":
        cfg = cls(
            schema=d.get("schema", SCHEMA_VERSION),
            show_mode=bool(d.get("show_mode", False)),
            groups=[Group(**g) for g in d.get("groups", [])],
            endpoints=[Endpoint(**e) for e in d.get("endpoints", [])],
            dtmf=DtmfSettings(**d.get("dtmf", {})),
            captions=CaptionSettings(**d.get("captions", {})),
            attention_target=d.get("attention_target", ""),
        )
        cfg.validate()
        return cfg


# Actions understood by the controller. Kept as strings so they can live in
# JSON config and be shown in the UI.
#   select:<group>        pick talk group (or both, per endpoint select_scope)
#   listen:<group>        toggle listening to a group
#   allcall:on|off|toggle
#   mute:on|off|toggle
#   talk:toggle           latched talk toggle
#   attention             raise a "calling Sound" alert
#   status                play the audible status cue
_SIMPLE_ACTIONS = {
    "allcall:on", "allcall:off", "allcall:toggle",
    "mute:on", "mute:off", "mute:toggle",
    "talk:toggle", "attention", "status",
}


def validate_action(action: str, group_ids: set[str]) -> None:
    if action in _SIMPLE_ACTIONS:
        return
    kind, _, arg = action.partition(":")
    if kind in ("select", "listen") and arg in group_ids:
        return
    raise ConfigError(f"unknown action {action!r}")


def default_config() -> Config:
    """Factory defaults: Tech + Stage, one rotary endpoint named Sound."""
    cfg = Config(
        groups=[
            Group(id="tech", name="Tech", cue_beeps=1),
            Group(id="stage", name="Stage", cue_beeps=2),
        ],
        endpoints=[
            Endpoint(
                id="sound",
                name="Sound",
                kind="rotary",
                listen=["tech", "stage"],
                talk=["tech"],
                listen_allowed=["tech", "stage"],
                talk_allowed=["tech", "stage"],
                can_allcall=True,
                tone_control=True,
                talk_mode="open",
            )
        ],
        attention_target="sound",
    )
    cfg.validate()
    return cfg
