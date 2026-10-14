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

from .network import NetworkSettings, validate_network

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


CUE_PITCHES = ("low", "mid", "high")
DTMF_KEYS = "0123456789*#ABCD"
MAX_CODE_LEN = 4


@dataclass
class Group:
    id: str
    name: str
    # Number of short beeps used as the audible group cue (language-free).
    cue_beeps: int = 1
    # Pitch of those beeps: beeps x pitch gives 15 distinguishable group cues, not just 5.
    cue_pitch: str = "mid"

    def validate(self) -> None:
        if not ID_RE.match(self.id):
            raise ConfigError(f"invalid group id {self.id!r}")
        if not self.name.strip():
            raise ConfigError("group name is empty")
        if not 1 <= self.cue_beeps <= 5:
            raise ConfigError("cue_beeps must be 1..5")
        if self.cue_pitch not in CUE_PITCHES:
            raise ConfigError(f"cue_pitch must be one of {CUE_PITCHES}")


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
    # May this endpoint open a private one-to-one line to another endpoint ("whisper")?
    can_private: bool = False
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

    # Words that mean "this person is being talked about" (e.g. "DJ"). Short acronyms
    # are expanded to their spoken forms automatically (see mentions.py). Supplementary
    # to the explicit "Calling" alert, never a replacement for it.
    mention_terms: list[str] = field(default_factory=list)
    # Play a short cue in this endpoint's own earpiece when a term is heard (useful for
    # people on a handset or rotary phone who are not looking at a screen).
    mention_cue: bool = True

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
        if len(self.mention_terms) > 8 or any(not t.strip() or len(t) > 40 for t in self.mention_terms):
            raise ConfigError(f"{self.id}: mention terms must be 1-40 characters, at most 8")
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
    # Longest pause (s) between the keys of a multi-key code such as "21" or "305".
    digit_timeout_s: float = 2.0
    # Minimum tone duration (ms) before a digit counts.
    min_tone_ms: int = 40
    # Hold the endpoint's transmission closed while a tone is present (and for
    # this many ms afterwards) so command tones are not broadcast.
    gate_hold_ms: int = 150
    # code -> action string. A code is 1-4 keys (0-9 * # A-D); no code may be the beginning of a longer one.
    # So one phone can reach far more than 12 actions, e.g. "21" -> talk to a third group.
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
    # A private line ends by itself after this many seconds (0 = never).
    private_timeout_s: float = 60.0


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
    # Minimum seconds between earpiece mention cues for one person (visual alerts are not limited).
    mention_cooldown_s: float = 8.0


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
    network: NetworkSettings = field(default_factory=NetworkSettings)
    # Shown on the dashboard and printed join sheet.
    site_name: str = ""

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
        validate_network(self.network)
        if len(self.site_name) > 60:
            raise ConfigError("site name is too long")
        if self.captions.retain_audio:
            raise ConfigError("audio retention is not implemented in this version")
        if self.dtmf.allcall_style not in ALLCALL_STYLES:
            raise ConfigError("unknown allcall_style")
        if self.dtmf.prefix and self.dtmf.prefix not in "0123456789*#ABCD":
            raise ConfigError("invalid DTMF prefix")
        from .buttons import BUTTON_EVENTS, LONG_SUFFIX
        for e in self.endpoints:
            for ev, action in e.buttons.items():
                base = ev.removesuffix(LONG_SUFFIX)
                if base not in BUTTON_EVENTS:
                    raise ConfigError(f"{e.id}: unknown button event {ev!r}")
                if action != "ptt":
                    validate_action(action, set(gids), set(eids))
        if not 0 <= self.dtmf.private_timeout_s <= 3600:
            raise ConfigError("private_timeout_s must be between 0 and 3600 seconds")
        if not 0.3 <= self.dtmf.digit_timeout_s <= 10:
            raise ConfigError("digit_timeout_s must be between 0.3 and 10 seconds")
        codes = list(self.dtmf.commands)
        for code, action in self.dtmf.commands.items():
            if not 1 <= len(code) <= MAX_CODE_LEN or any(ch not in DTMF_KEYS for ch in code):
                raise ConfigError(f"invalid dial code {code!r}: use 1-{MAX_CODE_LEN} keys from {DTMF_KEYS}")
            validate_action(action, set(gids), set(eids))
        for a in codes:
            for b in codes:
                if a != b and b.startswith(a):
                    raise ConfigError(f"dial code {a!r} is the start of {b!r}: the phone could not tell them apart. "
                                      "Remove one, or make them the same length.")

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
            network=NetworkSettings(**d.get("network", {})),
            site_name=d.get("site_name", ""),
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


def validate_action(action: str, group_ids: set[str], endpoint_ids: set[str] | None = None) -> None:
    if action in _SIMPLE_ACTIONS:
        return
    kind, _, arg = action.partition(":")
    if kind in ("select", "listen") and arg in group_ids:
        return
    if kind == "private" and (arg == "off" or endpoint_ids is None or arg in endpoint_ids):
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
                mention_terms=["DJ"],
            )
        ],
        attention_target="sound",
    )
    cfg.validate()
    return cfg
