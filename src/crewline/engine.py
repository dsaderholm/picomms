"""The Crewline engine daemon.

The *real-time audio* is carried by PipeWire (BlueZ -> SCO -> PipeWire nodes ->
links). This daemon is the control plane around it:

* watches Bluetooth devices and the PipeWire graph,
* keeps the routing links equal to what config + runtime state say,
* reads a *copy* of each microphone ("tap") for activity meters, DTMF commands
  and captions,
* applies control events (tone commands, buttons, web remote), plays audible
  cues to the affected endpoint only,
* exposes everything to the web process over a local unix socket.

If this process dies, links created through ``pw-link`` linger, so people keep
talking; only control (tone commands, mute changes) is unavailable until
systemd restarts it (typically seconds).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import shutil
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from . import cues
from .activity import ActivityMeter, Segmenter
from .bluez import BtAdapter, BtDevice, BluezDbus, SimBluetooth
from .buttons import AtTranslator, ButtonEvent, ButtonHub, PROFILES
from .captions.client import CaptionClient
from .commands import DtmfCommandHandler
from .control import Controller, ControlEvent, Cue, Outcome
from .dtmf import DtmfDecoder, DtmfEvent
from .mentions import MentionBook, find_term
from .network import NetworkBackend, wifi_qr_payload
from .model import Config, ConfigError, ConfigLocked
from .pwgraph import GraphBackend, GraphSnapshot, PipeWireCli
from .routing import EndpointState, compute_links, explain, init_state
from .store import ConfigStore

log = logging.getLogger("crewline.engine")

TICK_S = 1.0               # slow reconcile cadence; control events trigger an immediate pass
BT_REFRESH_S = 2.0


class EventBus:
    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()
        self.recent_captions: deque[dict] = deque(maxlen=60)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def publish(self, ev: dict) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                # A slow viewer must never slow the engine: drop it; it reconnects.
                self._subs.discard(q)


@dataclass
class Runtime:
    """Per-endpoint live helpers (not config)."""
    meter: ActivityMeter = field(default_factory=ActivityMeter)
    segmenter: Segmenter = field(default_factory=Segmenter)
    seg_id: int | None = None
    dtmf: DtmfDecoder | None = None
    cmd: DtmfCommandHandler | None = None
    tap: object | None = None
    tap_task: asyncio.Task | None = None
    speaking: bool = False
    level: float = -120.0
    last_chunk: float = 0.0
    last_speech: float = 0.0
    peak_since_test: float = -120.0
    adapter: str = ""
    codec: str = ""
    profile: str = ""
    tone_gate_since: float = 0.0
    last_gate_ms: float | None = None


class Engine:
    def __init__(self, state_dir: Path, graph: GraphBackend, bt, simulated: bool = False,
                 net: NetworkBackend | None = None) -> None:
        self.state_dir = Path(state_dir)
        self.simulated = simulated
        self.graph = graph
        self.bt = bt
        self.store = ConfigStore(self.state_dir / "config.json")
        self.bus = EventBus()
        self.state: dict[str, EndpointState] = {}
        self.rt: dict[str, Runtime] = {}
        self.controller: Controller | None = None
        self.adapters: list[BtAdapter] = []
        self.devices: list[BtDevice] = []
        self.snap = GraphSnapshot()
        self.links_now: set[tuple[str, str]] = set()
        self.pw_ok = False
        self.bt_ok = False
        self._bt_known = False      # True after the first successful device refresh
        self._kick = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._last_published = ""
        self._last_bt = 0.0
        self.started = time.time()
        self.captions = CaptionClient(self._on_caption, token=os.environ.get("CREWLINE_CAPTION_TOKEN", ""))
        self.transcript_file: Path | None = None
        self._cue_dir = self.state_dir / "cues"
        self.log_events: deque[dict] = deque(maxlen=200)
        self.at = AtTranslator()
        self.mentions = MentionBook()
        self.net = net
        self.net_status: dict = {"available": False, "reason": "network control not configured"}
        self._passthrough_applied: tuple[str, bool] | None = None
        self.buttons = ButtonHub(lambda: self.store.config,
                                 lambda c: asyncio.get_running_loop().create_task(self.control(c)))

    # -- lifecycle -----------------------------------------------------------
    async def start(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        cfg = self.store.load()
        self.store.subscribe(self._on_config)
        self.state = init_state(cfg)
        self.controller = Controller(lambda: self.store.config, self.state)
        self._write_cues()
        self._on_config(cfg)
        self._tasks = [
            asyncio.create_task(self._bt_connect(), name="bluez-connect"),
            asyncio.create_task(self._loop(), name="reconcile"),
            asyncio.create_task(self._net_loop(), name="network"),
        ]
        self.note("engine started" + (" (SIMULATION)" if self.simulated else ""))

    # -- network (hotspot / internet passthrough) ----------------------------------
    async def _net_loop(self) -> None:
        """Poll network status (cheap, separate from the audio reconcile loop)."""
        while self.net is not None:
            try:
                await self.refresh_network()
                st = self.net_status
                ap, n = st.get("ap", {}), self.store.config.network
                # The nftables rule that blocks internet passthrough does not survive a reboot:
                # re-apply it once the hotspot is up.
                if st.get("available") and ap.get("active") and ap.get("interface"):
                    want = (ap["interface"], n.passthrough)
                    if self._passthrough_applied != want and not n.passthrough:
                        await self.net.set_passthrough(False, ap["interface"])
                    self._passthrough_applied = want
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("network status failed")
            await asyncio.sleep(10)

    async def refresh_network(self) -> dict:
        if self.net is None:
            return self.net_status
        old = json.dumps(self.net_status.get("ap"), sort_keys=True, default=str)
        self.net_status = await self.net.status()
        if json.dumps(self.net_status.get("ap"), sort_keys=True, default=str) != old:
            self.bus.publish({"type": "state"})
        return self.net_status

    def network_info(self) -> dict:
        n = self.store.config.network
        qr = wifi_qr_payload(n.ap_ssid, n.ap_password) if n.ap_ssid and n.ap_password else ""
        return {"status": self.net_status, "settings": n.__dict__, "wifi_qr": qr,
                "show_mode": self.store.config.show_mode}

    async def _bt_connect(self) -> None:
        """Connect to BlueZ, retrying forever: BlueZ may start after us at boot, and a
        missing BlueZ must never crash-loop the engine (links keep working)."""
        delay = 1.0
        while True:
            try:
                await self.bt.start()
                self.bt_ok = True
                self.note("connected to BlueZ")
                self.kick()
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.bt_ok = False
                log.warning("BlueZ not available yet (%s); retrying", exc)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 15.0)

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for rt in self.rt.values():
            if rt.tap_task:
                rt.tap_task.cancel()
        self.captions.configure("")

    def note(self, msg: str, level: str = "info") -> None:
        ev = {"type": "log", "t": time.time(), "level": level, "msg": msg}
        self.log_events.append(ev)
        self.bus.publish(ev)
        getattr(log, "warning" if level == "warn" else "info")(msg)

    # -- config changes ---------------------------------------------------------
    def _on_config(self, cfg: Config) -> None:
        # keep runtime state for existing endpoints, add new, drop removed
        for ep in cfg.endpoints:
            if ep.id not in self.state:
                self.state[ep.id] = EndpointState(listen=set(ep.listen), talk=set(ep.talk))
            else:
                st = self.state[ep.id]
                st.listen &= set(ep.listen_allowed)
                st.talk &= set(ep.talk_allowed)
                if not st.listen:
                    st.listen = set(ep.listen)
        for gone in set(self.state) - {e.id for e in cfg.endpoints}:
            self.state.pop(gone, None)
            rt = self.rt.pop(gone, None)
            if rt and rt.tap_task:
                rt.tap_task.cancel()
        for ep in cfg.endpoints:
            rt = self.rt.setdefault(ep.id, Runtime())
            if ep.tone_control and rt.dtmf is None:
                d = cfg.dtmf
                rt.dtmf = DtmfDecoder(min_tone_ms=d.min_tone_ms, gate_hold_ms=d.gate_hold_ms)
                rt.cmd = DtmfCommandHandler(ep.id, lambda: self.store.config)
            elif not ep.tone_control:
                rt.dtmf = rt.cmd = None
        self.captions.configure(cfg.captions.server)
        self.kick()
        self.bus.publish({"type": "config"})

    def kick(self) -> None:
        self._kick.set()

    # -- cues ----------------------------------------------------------------------
    def _write_cues(self) -> None:
        self._cue_dir.mkdir(parents=True, exist_ok=True)
        for kind in ("mute_on", "mute_off", "allcall_on", "allcall_off", "talk_on", "talk_off",
                     "denied", "status", "attention_ack", "ring", "mention"):
            (self._cue_dir / f"{kind}.wav").write_bytes(cues.render_wav(kind))
        for n in range(1, 6):
            (self._cue_dir / f"group-{n}.wav").write_bytes(cues.render_wav("group", n))

    def _cue_path(self, cue: Cue) -> str:
        if cue.kind == "group":
            g = self.store.config.group(cue.group or "")
            return str(self._cue_dir / f"group-{g.cue_beeps if g else 1}.wav")
        return str(self._cue_dir / f"{cue.kind}.wav")

    async def play(self, cue_list: list[Cue]) -> None:
        cfg = self.store.config
        for c in cue_list:
            ep = cfg.endpoint(c.endpoint)
            if not ep or not ep.address:
                continue
            try:
                await self.graph.play_cue(ep.address, self._cue_path(c))
            except Exception as exc:   # cue failures never matter to audio
                log.debug("cue failed: %s", exc)

    # -- control -----------------------------------------------------------------
    async def control(self, ev: ControlEvent) -> Outcome:
        out = self.controller.apply(ev)
        self.note(f"{ev.endpoint}: {ev.action} via {ev.source} -> "
                  f"{'ok' if out.accepted else 'denied: ' + out.reason}")
        if out.attention:
            self.bus.publish({"type": "attention", "alert": out.attention.to_dict()})
        if out.changed or out.accepted:
            self.kick()
        if out.cues:
            asyncio.create_task(self.play(out.cues))
        self.bus.publish({"type": "state"})
        return out

    # -- headset buttons / HFP AT commands -----------------------------------------
    def endpoint_for_address(self, address: str):
        return self.store.config.endpoint_by_address(address)

    def on_button(self, ev: ButtonEvent) -> None:
        self.buttons.feed(ev)
        self.bus.publish({"type": "button", "endpoint": ev.endpoint, "event": ev.event})

    def on_at(self, address: str, at: str) -> None:
        """An AT command was seen from a headset's HFP channel (via btsniff).

        For tone-control endpoints (the Cell2Jack) AT+VTS / ATD digits are also
        fed to the command handler: an alternative to in-band DTMF. UNVERIFIED
        until test T4 shows what the Cell2Jack actually sends."""
        ep = self.endpoint_for_address(address)
        if ep is None:
            return
        at = at.strip()
        if ep.tone_control:
            m = re.match(r"^AT\+VTS=([0-9A-D*#])", at) or re.match(r"^ATD([0-9A-D*#]+);?", at)
            if m:
                rt = self.rt.get(ep.id)
                for ch in m.group(1):
                    self.note(f"{ep.name}: digit {ch} seen as AT command (not audio)")
                    if rt and rt.cmd:
                        res = rt.cmd.handle(DtmfEvent("digit", 0.0, ch))
                        for c in res.controls or []:
                            asyncio.get_running_loop().create_task(self.control(c))
                self.bus.publish({"type": "button", "endpoint": ep.id, "event": f"raw:{at[:20]}"})
                return
        for name, raw in self.at.translate(address, at):
            self.on_button(ButtonEvent(ep.id, name, "tap", "hfp-at", raw))

    def buttons_info(self, eid: str) -> dict:
        ep = self.store.config.endpoint(eid)
        prof = None
        if ep and "jlab" in (ep.name + " " + ep.id).lower():
            prof = PROFILES["jlab-go-work"]
        return {
            "observed": self.buttons.observed_list(eid),
            "learning_left_s": round(self.buttons.learning_left(eid), 1),
            "mappings": ep.buttons if ep else {},
            "profile_hint": prof,
        }

    async def ack_attention(self, att_id: int | None, by: str) -> int:
        n = self.controller.ack_all_attention(by) if att_id is None else int(self.controller.ack_attention(att_id, by))
        if n:
            self.bus.publish({"type": "attention_ack"})
        return n

    # -- main reconcile loop -------------------------------------------------------
    async def _loop(self) -> None:
        while True:
            try:
                await self._cycle()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("reconcile cycle failed")
                self.pw_ok = False
            try:
                await asyncio.wait_for(self._kick.wait(), TICK_S)
            except asyncio.TimeoutError:
                pass
            self._kick.clear()

    async def _cycle(self) -> None:
        cfg = self.store.config
        now = time.monotonic()
        if self.bt_ok and now - self._last_bt >= BT_REFRESH_S:
            self._last_bt = now
            try:
                self.adapters, self.devices = await self.bt.refresh()
                self._bt_known = True
            except Exception as exc:
                log.debug("bt refresh failed: %s", exc)
        try:
            self.snap = await self.graph.snapshot()
            self.pw_ok = True
        except Exception as exc:
            self.pw_ok = False
            log.debug("graph snapshot failed: %s", exc)
            self._publish_if_changed()
            return

        devs = {d.address: d for d in self.devices}
        known_cards = {e.address for e in cfg.endpoints if e.address}
        # Put known, connected headsets into the HFP profile (A2DP has no microphone).
        if any(a in self.snap.cards for a in known_cards):
            switched = await self.graph.ensure_hfp_profile(
                GraphSnapshot(cards={a: c for a, c in self.snap.cards.items() if a in known_cards}))
            if switched:
                self.note(f"switched to HFP profile: {', '.join(switched)}")
                self.snap = await self.graph.snapshot()

        for ep in cfg.endpoints:
            st = self.state[ep.id]
            rt = self.rt[ep.id]
            if not ep.address:
                continue
            d = devs.get(ep.address)
            was = (st.connected, st.audio_up)
            if self._bt_known:
                st.connected = bool(d and d.connected)
            else:
                # Bluetooth state not read yet (engine just started, BlueZ slow). Trust the
                # PipeWire graph for now so that a restart never tears down live links.
                st.connected = self.snap.audio_up(ep.address)
            st.audio_up = st.connected and self.snap.audio_up(ep.address)
            n = self.snap.sources.get(ep.address)
            rt.codec = n.codec if n else ""
            rt.profile = n.profile if n else ""
            rt.adapter = d.adapter if d else ""
            if was != (st.connected, st.audio_up):
                self.note(f"{ep.name}: connected={st.connected} two-way-audio={st.audio_up}")
            if st.audio_up:
                await self._ensure_tap(ep.id, ep.address)
            elif rt.tap_task:
                rt.tap_task.cancel()
                rt.tap_task = None
                rt.speaking = False

        for c in self.controller.tick():
            asyncio.create_task(self.play([c]))

        # desired links by address
        desired = set()
        addr = {e.id: e.address for e in cfg.endpoints}
        for l in compute_links(cfg, self.state):
            if addr.get(l.src) and addr.get(l.dst):
                desired.add((addr[l.src], addr[l.dst]))
        try:
            added, removed = await self.graph.reconcile(desired, self.snap)
            self.links_now = desired
            if added or removed:
                log.info("links +%d -%d", added, removed)
        except Exception as exc:
            log.warning("reconcile failed: %s", exc)
        for rt in self.rt.values():
            if rt.tone_gate_since and rt.last_gate_ms is None:
                rt.last_gate_ms = (time.monotonic() - rt.tone_gate_since) * 1000
        self._publish_if_changed()

    # -- taps ---------------------------------------------------------------------
    async def _ensure_tap(self, eid: str, address: str) -> None:
        rt = self.rt[eid]
        if rt.tap_task and not rt.tap_task.done():
            return
        node = self.snap.sources.get(address)
        if not node:
            return
        try:
            rt.tap = await self.graph.start_tap(node.name)
        except Exception as exc:
            log.warning("tap start failed for %s: %s", eid, exc)
            return
        rt.meter = ActivityMeter()
        rt.segmenter = Segmenter()
        rt.tap_task = asyncio.create_task(self._read_tap(eid, rt.tap), name=f"tap-{eid}")

    async def _read_tap(self, eid: str, tap) -> None:
        rt = self.rt[eid]
        try:
            while True:
                chunk = await tap.stdout.read(640)
                if not chunk:
                    break
                rt.last_chunk = time.monotonic()
                self._process_audio(eid, chunk)
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("tap reader %s crashed", eid)
        finally:
            try:
                tap.kill()
            except Exception:
                pass
            if rt.speaking:
                rt.speaking = False
                self.bus.publish({"type": "speaking", "endpoint": eid, "speaking": False})

    def _process_audio(self, eid: str, chunk: bytes) -> None:
        rt = self.rt.get(eid)
        cfg = self.store.config
        ep = cfg.endpoint(eid)
        if not rt or not ep:
            return
        # Tone commands first: the gate must react as early as possible.
        if rt.dtmf is not None:
            for ev in rt.dtmf.feed(chunk):
                res = rt.cmd.handle(ev)
                if res.gate is not None:
                    st = self.state[eid]
                    if st.tone_gate != res.gate:
                        st.tone_gate = res.gate
                        rt.tone_gate_since = time.monotonic() if res.gate else 0.0
                        rt.last_gate_ms = None
                        self.kick()
                for c in res.controls or []:
                    asyncio.create_task(self.control(c))
        for frame, level, speaking in rt.meter.feed_frames(chunk):
            rt.level = level
            rt.peak_since_test = max(rt.peak_since_test, level)
            if speaking != rt.speaking:
                rt.speaking = speaking
                if speaking:
                    rt.last_speech = time.time()
                st = self.state[eid]
                self.bus.publish({
                    "type": "speaking", "endpoint": eid, "speaking": speaking,
                    "groups": sorted(st.talk), "allcall": st.allcall,
                    "transmitting": self._transmitting(eid),
                })
            if ep.captions and self.captions.enabled and not self.state[eid].tone_gate:
                for se in rt.segmenter.push(frame.tobytes(), speaking):
                    if se.kind == "start":
                        grp = ",".join(sorted(self.state[eid].talk))
                        rt.seg_id = self.captions.start_segment(eid, ep.name, grp)
                    elif se.kind == "audio" and rt.seg_id is not None:
                        self.captions.audio(rt.seg_id, se.pcm)
                    elif se.kind == "end" and rt.seg_id is not None:
                        self.captions.end_segment(rt.seg_id)
                        rt.seg_id = None

    def _transmitting(self, eid: str) -> bool:
        from .routing import is_transmitting
        ep = self.store.config.endpoint(eid)
        return bool(ep and is_transmitting(ep, self.state[eid]))

    # -- captions -------------------------------------------------------------------
    def _on_caption(self, msg: dict) -> None:
        cfg = self.store.config
        text = (msg.get("text") or "").strip()
        if not text:
            return
        source = msg.get("endpoint") or ""
        seg = msg.get("seg")
        # Who was mentioned? Each person can have their own words; the speaker is never
        # alerted about their own name.
        hits: list[tuple[str, str]] = []
        for e in cfg.endpoints:
            if e.id != source and e.mention_terms:
                term = find_term(text, e.mention_terms)
                if term:
                    hits.append((e.id, term))
        targets = []
        for target, term in hits:
            m = self.mentions.add(target, source, term, text, msg.get("group") or "", seg, time.time())
            if m is None:
                continue                      # same utterance already raised this mention
            targets.append(target)
            self.bus.publish({"type": "mention", "mention": m.to_dict()})
            self._mention_cue(target)
        glob = [t for t in cfg.captions.highlight_terms if t.strip()]
        highlighted = bool(hits) or (bool(glob) and find_term(text, glob) is not None)
        ev = {
            "type": "caption", "seg": seg, "endpoint": source,
            "name": msg.get("name"), "group": msg.get("group"), "text": text,
            "final": bool(msg.get("final")), "mention": highlighted,
            "mention_targets": [t for t, _ in hits], "t": time.time(),
        }
        # replace the interim line of the same segment, keep a short history
        rc = self.bus.recent_captions
        for i, old in enumerate(rc):
            if old.get("seg") == ev["seg"] and old.get("endpoint") == ev["endpoint"]:
                rc[i] = ev
                break
        else:
            rc.append(ev)
        self.bus.publish(ev)
        if ev["final"] and cfg.captions.retain_transcripts:
            d = self.state_dir / "transcripts"
            d.mkdir(exist_ok=True)
            with open(d / (time.strftime("%Y-%m-%d") + ".jsonl"), "a") as fh:
                fh.write(json.dumps(ev) + "\n")

    def _mention_cue(self, target: str, force: bool = False) -> None:
        """Play the mention cue in that person's own earpiece (rate-limited)."""
        cfg = self.store.config
        ep = cfg.endpoint(target)
        if not ep or not ep.mention_cue or not self.state.get(target) or not self.state[target].audio_up:
            return
        if force or self.mentions.cue_allowed(target, time.monotonic(), cfg.captions.mention_cooldown_s):
            asyncio.get_running_loop().create_task(self.play([Cue(target, "mention")]))

    def test_mention(self, target: str) -> bool:
        """Admin test: raise a visible, clearly-labelled test mention and play the cue."""
        ep = self.store.config.endpoint(target)
        if not ep:
            return False
        term = ep.mention_terms[0] if ep.mention_terms else ep.name
        m = self.mentions.add(target, "", term, f"(test) {term} was mentioned", "", None, time.time(), test=True)
        self.bus.publish({"type": "mention", "mention": m.to_dict()})
        self._mention_cue(target, force=True)
        return True

    def ack_mentions(self, mid: int | None) -> int:
        n = self.mentions.ack(mid, time.time())
        if n:
            self.bus.publish({"type": "mention_ack"})
        return n

    # -- published state ----------------------------------------------------------------
    def snapshot_state(self) -> dict:
        cfg = self.store.config
        eps = []
        devs = {d.address: d for d in self.devices}
        for e in cfg.endpoints:
            st, rt = self.state[e.id], self.rt[e.id]
            d = devs.get(e.address or "")
            eps.append({
                "id": e.id, "name": e.name, "kind": e.kind, "address": e.address,
                "enabled": e.enabled, "forced_mute": e.forced_mute,
                "talk_mode": e.talk_mode, "can_allcall": e.can_allcall, "can_select": e.can_select,
                "select_scope": e.select_scope, "tone_control": e.tone_control, "captions": e.captions,
                "listen_allowed": e.listen_allowed, "talk_allowed": e.talk_allowed,
                "mention_terms": e.mention_terms, "mention_cue": e.mention_cue,
                "home_listen": e.listen, "home_talk": e.talk, "buttons": e.buttons,
                "connected": st.connected, "audio_up": st.audio_up,
                "muted": st.muted, "latched_on": st.latched_on, "ptt_down": st.ptt_down,
                "allcall": st.allcall, "tone_gate": st.tone_gate,
                "listen": sorted(st.listen), "talk": sorted(st.talk),
                "transmitting": self._transmitting(e.id),
                "speaking": rt.speaking, "level_db": round(rt.level, 1),
                "codec": rt.codec or None, "profile": rt.profile or None,
                "adapter": rt.adapter or (d.adapter if d else None),
                # Unknown stays unknown: never invented.
                "battery": d.battery if d else None,
                "rssi": d.rssi if d else None,
                "hw_mute": None,
                "tap_age_s": round(time.monotonic() - rt.last_chunk, 1) if rt.last_chunk else None,
                "last_gate_ms": round(rt.last_gate_ms, 1) if rt.last_gate_ms is not None else None,
            })
        known = {e.address for e in cfg.endpoints if e.address}
        return {
            "simulated": self.simulated,
            "uptime_s": int(time.time() - self.started),
            "pipewire_ok": self.pw_ok,
            "show_mode": cfg.show_mode,
            "groups": [{"id": g.id, "name": g.name, "cue_beeps": g.cue_beeps} for g in cfg.groups],
            "endpoints": eps,
            "links": sorted([list(l) for l in self.links_now]),
            "adapters": [a.__dict__ for a in self.adapters],
            "unassigned_devices": [
                {"address": d.address, "name": d.alias or d.name, "paired": d.paired,
                 "connected": d.connected, "rssi": d.rssi, "adapter": d.adapter,
                 "supports_hfp": d.supports_hfp, "audio_like": d.is_audio_like}
                for d in self.devices if d.address not in known
            ],
            "pairing_open_s": max(0, int(self.bt.pairing_open_until - time.monotonic())),
            "attention": [a.to_dict() for a in self.controller.attention[-20:]],
            "attention_target": cfg.attention_target,
            "network": self._network_summary(),
            "mentions": [m.to_dict() for m in self.mentions.active(time.time())],
            "captions": {**self.captions.health(), "server_cfg": cfg.captions.server, "highlight_terms": cfg.captions.highlight_terms,
                         "retain_transcripts": cfg.captions.retain_transcripts,
                         "mention_cooldown_s": cfg.captions.mention_cooldown_s},
            "dtmf": {"prefix": cfg.dtmf.prefix, "commands": cfg.dtmf.commands,
                     "min_tone_ms": cfg.dtmf.min_tone_ms, "gate_hold_ms": cfg.dtmf.gate_hold_ms,
                     "allcall_timeout_s": cfg.dtmf.allcall_timeout_s},
        }

    def _network_summary(self) -> dict:
        st, n = self.net_status, self.store.config.network
        ap = st.get("ap", {}) if st.get("available") else {}
        return {"available": bool(st.get("available")), "ap_active": bool(ap.get("active")),
                "ap_ssid": n.ap_ssid if ap.get("active") else "", "clients": ap.get("clients"),
                "internet_ok": (st.get("internet") or {}).get("ok"),
                "band": n.ap_band if ap.get("active") else ""}

    def _publish_if_changed(self) -> None:
        # Level meters change constantly; compare without them to cut chatter.
        s = self.snapshot_state()
        key = json.dumps(
            {**s, "uptime_s": 0, "endpoints": [{k: v for k, v in e.items() if k not in ("level_db", "tap_age_s", "speaking")} for e in s["endpoints"]]},
            sort_keys=True, default=str)
        if key != self._last_published:
            self._last_published = key
            self.bus.publish({"type": "state"})

    # -- diagnostics ---------------------------------------------------------------------
    def why(self, src: str, dst: str) -> str:
        return explain(self.store.config, self.state, src, dst)

    def diagnose(self, eid: str) -> list[dict]:
        """Plain-language findings for one endpoint, most specific first."""
        cfg = self.store.config
        ep = cfg.endpoint(eid)
        if not ep:
            return [{"level": "fail", "msg": "unknown endpoint"}]
        st = self.state[eid]
        rt = self.rt[eid]
        out: list[dict] = []
        if not ep.address:
            return [{"level": "fail", "msg": "No Bluetooth device is assigned to this endpoint yet."}]
        d = next((x for x in self.devices if x.address == ep.address), None)
        if d is None:
            out.append({"level": "fail", "msg": "BlueZ does not know this device. Pair it again (open the pairing window)."})
            return out
        if not d.paired:
            out.append({"level": "fail", "msg": "Not paired."})
        if not d.connected:
            out.append({"level": "fail", "msg": "Paired but not connected. Switch the headset on / press Reconnect. "
                        "If it never connects, move it closer to its adapter."})
            return out
        if not d.supports_hfp:
            out.append({"level": "fail", "msg": "Device does not advertise the Hands-Free or Headset profile, "
                        "so it cannot provide a microphone to the intercom."})
        if not st.audio_up:
            n_src = ep.address in self.snap.sources
            n_snk = ep.address in self.snap.sinks
            if not (n_src or n_snk):
                out.append({"level": "fail", "msg": "Connected, but PipeWire has no voice nodes for it. "
                            "Typical causes: the headset connected only for music (A2DP) and was not switched "
                            "to the headset profile, the adapter cannot open another voice link, or the "
                            "voice link failed. Check 'Audio sessions per adapter' and the engine log."})
            else:
                out.append({"level": "fail", "msg": "Connected, but the voice profile is not active "
                            f"(profile: {rt.profile or 'none'})."})
        else:
            if rt.last_chunk and time.monotonic() - rt.last_chunk > 3:
                out.append({"level": "warn", "msg": "Voice link is up but no microphone audio is arriving."})
            out.append({"level": "ok", "msg": f"Two-way audio up ({rt.codec or 'codec unknown'})."})
        if d.battery is None:
            out.append({"level": "info", "msg": "Battery level: unknown (this headset does not report it)."})
        elif d.battery <= 20:
            out.append({"level": "warn", "msg": f"Battery low ({d.battery}%)."})
        return out

    def readiness(self) -> list[dict]:
        """Pre-show readiness checks. 'fail' = fix before the show; 'warn' = look at it."""
        cfg = self.store.config
        checks: list[dict] = []

        def add(level: str, name: str, msg: str) -> None:
            checks.append({"level": level, "name": name, "msg": msg})

        add("ok" if self.pw_ok else "fail", "PipeWire", "audio server reachable" if self.pw_ok else "cannot reach PipeWire")
        if self.simulated:
            add("warn", "Simulation", "running in SIMULATION mode: nothing here is real hardware")
        if not self.bt_ok:
            add("fail", "BlueZ", "cannot reach the Bluetooth service (bluetoothd) — is it running?")
        elif not self.adapters:
            add("fail", "Bluetooth adapters", "no Bluetooth adapters found")
        for a in self.adapters:
            if not a.powered:
                add("fail", f"Adapter {a.address}", "adapter is not powered")
            else:
                add("ok", f"Adapter {a.address}", f"{a.hfp_connected} headset(s) connected; "
                    "validated capacity per adapter: see docs/04-validation-plan.md (not yet measured)")
        for e in cfg.endpoints:
            if not e.enabled:
                add("info", e.name, "disabled by an administrator")
                continue
            if not e.address:
                add("warn", e.name, "no Bluetooth device assigned")
                continue
            findings = self.diagnose(e.id)
            worst = "ok"
            for f in findings:
                if f["level"] == "fail":
                    worst = "fail"
                elif f["level"] == "warn" and worst != "fail":
                    worst = "warn"
            add(worst, e.name, next((f["msg"] for f in findings if f["level"] in ("fail", "warn")),
                                    findings[-1]["msg"] if findings else "ok"))
            if e.tone_control and self.state[e.id].audio_up:
                add("ok", f"{e.name} tone commands", "decoder running on the live microphone tap"
                    if self.rt[e.id].last_chunk else "decoder waiting for audio")
        if cfg.captions.server:
            h = self.captions.health()
            add("ok" if h["connected"] else "warn", "Captions",
                f"connected to caption server (engine {h['engine']})" if h["connected"]
                else "caption server unreachable (audio is unaffected)")
        else:
            add("info", "Captions", "not configured (audio is unaffected)")
        add("ok" if cfg.show_mode else "warn", "Show mode",
            "configuration is locked" if cfg.show_mode else "show mode is OFF: pairing/routing changes are possible")
        if self.controller.active_attention():
            add("warn", "Attention alerts", "there are unacknowledged alerts")
        total, used, free = shutil.disk_usage(self.state_dir)
        add("ok" if free > 500_000_000 else "warn", "Disk", f"{free // 1_000_000} MB free")
        return checks

    async def mic_test(self, eid: str, seconds: float = 4.0) -> dict:
        """Ask the user to speak; report the peak level seen on that microphone."""
        rt = self.rt.get(eid)
        if not rt:
            return {"ok": False, "error": "unknown endpoint"}
        if not self.state[eid].audio_up:
            return {"ok": False, "error": "no two-way audio session"}
        rt.peak_since_test = -120.0
        await asyncio.sleep(seconds)
        peak = rt.peak_since_test
        return {"ok": peak > -70, "peak_dbfs": round(peak, 1),
                "note": "peak microphone level during the test window"}


# --------------------------------------------------------------------------------------
async def run(args) -> None:
    from .engine_api import serve_unix

    if args.sim:
        from .sim import SimDevice, SimGraph
        graph = SimGraph()
        bt = SimBluetooth(graph)
        graph.add_device(SimDevice("AA:BB:CC:00:00:01", "Rotary (Cell2Jack)"))
        graph.add_device(SimDevice("AA:BB:CC:00:00:02", "JLab GO Work A", battery=None))
        bt.discovered["AA:BB:CC:00:00:09"] = "JLab GO Work C"
    else:
        graph = PipeWireCli()
        bt = BluezDbus(lambda: {e.address for e in eng.store.config.endpoints if e.address})
    from .network import NmcliBackend, SimNetwork
    eng = Engine(Path(args.state_dir), graph, bt, simulated=args.sim,
                 net=SimNetwork() if args.sim else NmcliBackend())
    await eng.start()
    if args.sim:
        from .sim_demo import run_demo
        eng._tasks.append(asyncio.create_task(run_demo(eng, graph, bt)))
    runner = await serve_unix(eng, args.socket)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        await eng.stop()


def main() -> None:
    ap = argparse.ArgumentParser(description="Crewline engine")
    ap.add_argument("--state-dir", default=os.environ.get("CREWLINE_STATE", "/var/lib/crewline"))
    ap.add_argument("--socket", default=os.environ.get("CREWLINE_SOCKET", "/run/crewline/engine.sock"))
    ap.add_argument("--sim", action="store_true", help="run against a simulated Bluetooth/PipeWire (demo/dev only)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
