# 2. Architecture

## The decision in one paragraph

All headsets connect **directly to one Linux host** over Bluetooth Hands-Free
Profile. **PipeWire** (with BlueZ and WirePlumber, all stock) is the real-time
audio engine: each headset becomes a microphone node and an earpiece node, and
"who hears whom" is simply *which microphone is linked to which earpiece*.
PipeWire mixes several links arriving at one earpiece. Crewline contains **no
audio code on the live path**. It is a control plane: it decides which links
should exist, creates them with `pw-link`, reads a *copy* of each microphone
for meters/tone commands/captions, and serves the browser UI.

```
  JLab headset ──BT HFP──► BlueZ ──SCO──► PipeWire ─┐ mic node (A)
  JLab headset ──BT HFP──► BlueZ ──SCO──► PipeWire ─┤ mic node (B)         links created
  Cell2Jack ───BT HFP────► BlueZ ──SCO──► PipeWire ─┘ mic node (Sound) ───► by `pw-link`
                                              │                             (kept by PipeWire
        earpiece nodes ◄──────────────────────┘                              even if Crewline dies)
                                              │
                                              ├─ copy (pw-cat tap) ─► Crewline engine ─► meters, DTMF, captions
                                              │
 browser (phone / Chromebook / desktop) ◄── Crewline web ◄── unix socket ◄── Crewline engine
                                                                               │ TCP (best effort)
                                                                               ▼
                                                                    caption server (other computer)
```

## Separation of concerns (required by the brief)

| Concern | Component | Runs as | If it crashes |
|---|---|---|---|
| Bluetooth devices, profiles, SCO | `bluetoothd` (BlueZ) + PipeWire's `bluez5` plugin | system / user services | that device reconnects; others unaffected |
| **Real-time audio capture, routing, mixing, playback** | **PipeWire + WirePlumber** | `crewline` user session | audio stops — this is the one component whose failure matters; it is the most widely deployed Linux audio server, not our code |
| Device management (pair/connect/forget, pairing window, agent) | `crewline/bluez.py` (BlueZ D-Bus) inside the engine | engine process | existing connections persist; pairing unavailable until restart |
| Endpoint identity & permissions | `model.py`/`store.py` (JSON, atomic writes, 20 automatic backups) | engine | last good file on disk |
| Control inputs (dial codes, buttons, remote taps) | `dtmf.py`, `commands.py`, `buttons.py`, web remote | engine / web | see engine row |
| Routing decisions | `routing.py`, `control.py` (pure functions, unit-tested) | engine | **links already in PipeWire linger**; talk groups/mutes freeze until restart (~1 s via systemd) |
| Browser management & dashboard | `crewline/web/` | web process | **no effect on audio or engine**; page shows "engine offline" if the reverse |
| Transcription & attention alerts | caption server (other computer); attention logic in `control.py` | separate machine / engine | captions stop; audio and attention alerts continue |
| Optional AT-command / button sniffer | `crewline-btsniff` | separate service | buttons/AT digits stop; audio unaffected |

Facts verified in upstream source (not from memory): `pw-link` creates links with
`object.linger=true` unless `-m` is used (`src/tools/pw-link.c`), which is what lets
audio survive an engine restart. The detailed upstream files are listed in
05-research.md.

## Why this and not the alternatives

**Mumble / talKKonnect (considered, rejected for this topology).**
Mumble is a network voice system: a server plus one *client per endpoint*. talKKonnect
is a Go Mumble client for single-board computers; its README documents ALSA and
USB sound cards and never mentions Bluetooth. With every headset attached to one
host, Mumble would need one client process and one audio device per headset,
an extra Opus encode/decode hop and a jitter buffer between two Bluetooth hops, and
still needs something to feed each client from the Bluetooth node. That is more
processes, more latency and more failure modes than linking nodes inside the audio
server that already owns the devices. Mumble *would* be the right choice for
endpoints on **different machines** (e.g. an offsite director); the design keeps
that door open (a Mumble bridge could be one more endpoint) but does not start there.

**Custom mixer in Python (rejected).** Reading each microphone and writing mixed
buffers from a Python process puts a GIL-bound process on the live path. Brief:
"do not replace proven audio components with custom code without a concrete reason."

**Asterisk `chan_mobile` / oFono / hsphfpd (rejected).** Telephony stacks that act as a
Bluetooth phone; powerful but a much larger system to run and debug, and
their audio gateway model still ends at a mixing bridge we would have to configure.
PipeWire's native HFP backend already provides what we need (AG role, SCO, mSBC).

**Dongle-based headsets (not the plan).** Per your message the JLabs are Bluetooth-only. The routing layer is
audio-server-agnostic: a USB-dongle headset would appear as one more pair of PipeWire
nodes and work with the same routing code.

## Verified vs unverified

**Verified (source reading / unit tests):**
* PipeWire's native backend handles the *headset-initiated* HFP traffic it needs and
  implements the AG role. `ATD`/`AT+VTS`/`ATA`/`AT+CHUP` are only acted on if a
  ModemManager modem exists; otherwise they get an error reply
  (`spa/plugins/bluez5/backend-native.c`). **Consequence:** PipeWire will *not*
  expose Cell2Jack digits or headset call-button presses to us — if they arrive as AT
  commands we have to observe them another way (`btmon`, `crewline-btsniff`).
* In HSP, `AT+CKPD=200` (the call button) makes PipeWire switch profile, so HSP is
  disabled in our config (`hfp_ag` only).
* Linux `btusb` sets USB alt-setting per air mode; for mSBC (transparent) it uses
  alt 6/3/1 independent of the number of voice links; for CVSD it scales with the number
  of links up to three (`drivers/bluetooth/btusb.c`). No *software* ceiling at two
  links was found; the **controller firmware** limit is unknown (see 05-research.md).
* The kernel flags ASUS USB-BT500 (`0b05:190e`) and TP-Link UB500 (`2357:0604`) as Realtek
  parts with wideband-speech support. That is a driver table, **not** a two-headset
  voice test.
* BlueZ's AVRCP key device is named `"<remote name> (AVRCP)"` and its `PHYS` field is the
  *adapter* address (`profiles/audio/avctp.c`, `src/shared/uinput.c`), so identical
  headsets on one adapter cannot be told apart from AVRCP key events alone.

**Unverified until hardware tests (see 04-validation-plan.md):**
* Two or more *simultaneous* HFP voice links on one adapter, and on one host.
* That PipeWire mixes several links into one earpiece without distortion (T3 has a
  hardware-free test for this).
* Clock drift between independently clocked Bluetooth links over a long session.
* Everything about the Cell2Jack (tones in-band vs AT, hook state, ring).
* Any headset button signal; the `btmon` text format used by the parser.
* Range, latency, whisper intelligibility.

## Latency: what is in the path (not measured)

Mouth → headset ADC/codec → Bluetooth radio hop 1 (SCO, ~7.5 ms frames for mSBC,
retransmissions possible) → controller/USB → BlueZ → PipeWire SCO source → graph
quantum (default buffer; configurable) → PipeWire SCO sink → BlueZ/USB → radio hop 2 →
headset DAC → ear. Everything in the host is controllable (quantum sizes, no
resampling beyond drift compensation, no extra processing); the two radio hops and
headset codecs are not. A tone-leak gate adds **no** delay to talkers (the gate is a
link removal, not a delay line); an optional 50–100 ms look-ahead for the *rotary phone
only* is described in 07-intercom-behavior.md and deliberately not enabled by default.
Measurement method: 04-validation-plan.md T10 and `crewline-probe click-train / latency`.

## Whisper-safe audio processing

There is **no voice gate, noise suppressor or automatic gain** anywhere in the live
path. The only detectors (`activity.py`) look at a *copy* of the audio to drive the
"speaking" indicator and to cut caption segments; they use a pre-roll buffer so onsets
are not clipped and a thresholds that scale to the measured noise floor (test:
a whisper-level signal is detected). Optional, off by default, per endpoint: a gentle
downward *expander* (not a gate) for headsets that have no mute button — see
09-ideas.md for the reasoning and the proposed implementation (LSP expander in a
PipeWire filter-chain). It must be tuned on real production sound before use.

## Captions are off the critical path

The engine reads a tap of each microphone, runs a noise-floor-relative detector, and for
detected speech opens a *segment* (with 0.5 s pre-roll) and streams it over TCP to the
caption server. The client's `submit` calls never block or raise; when the server is
away or slow it **drops** audio (bounded queue) and exposes "unavailable". Per-endpoint
segmentation means captions use configured names rather than guessing speakers.

*Compute consequence:* transcribing each endpoint separately costs one decode per
speech segment, and only while someone speaks. Crew conversation is mostly turn-taking, so
average load is far below "N streams"; peak load is the number of people speaking at
once. Transcribing a group *mix* would be cheaper at peak but loses the speaker identity
and degrades when two people talk over each other. Measurements on a sandbox VM are in
10-caption-benchmarks.md; they must be repeated on the real caption computer (T11).

## Process / port map

| Process | Listens on | Notes |
|---|---|---|
| `crewline-engine` | unix socket `/run/user/<uid>/crewline/engine.sock` (0660) | never reachable from the network |
| `crewline-web` | TCP 8080 | LAN-only guard rejects non-private source addresses; admin needs password |
| `crewline-caption-server` (other PC) | TCP 7070 | shared token; appliance connects *to* it |
| `bluetoothd`, `pipewire`, `wireplumber` | D-Bus / local sockets | stock |

Security model: no internet exposure (the guard refuses public source addresses so an
accidental port-forward does not expose it), admin password (PBKDF2), `SameSite=Strict`
cookie + custom-header CSRF check, strict CSP (no inline scripts; all assets local, so it
works offline), per-person unguessable remote links that can only call a short whitelist
and are checked again against permissions in the engine.
