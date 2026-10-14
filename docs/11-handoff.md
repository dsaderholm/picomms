# 11. Handoff: where this project stands and where to pick it up

The original author built this for a school crew, then lost the headsets it was designed around and **shelved it**.
It is published in the hope that someone finds it useful. It is MIT-licensed; take it, change it, rename it.

## Honest status

* **Works, in simulation:** routing and permissions, groups (any number), dial codes (1-4 keys), private lines, all-call,
  show-mode lock, Call Sound, name-mention alerts, captions pipeline (off the audio path), the web UI (dashboard, phone
  remote, admin, setup assistant, help; dark/night/light), Wi-Fi hotspot + internet-passthrough code, backup/restore.
  177 automated tests pass (`pytest`), 11 of them drive a headless browser.
* **Never run on real hardware:** Bluetooth pairing, PipeWire links, mSBC/CVSD voice links, how many headsets one adapter
  carries, range, latency, whisper intelligibility, the Cell2Jack/rotary phone path, NetworkManager hotspot, the installer.
  Every such claim in the docs is labelled *unverified*. `docs/04-validation-plan.md` (T0-T13) says exactly what to run
  and what each result decides.
* **No audio code of our own** is on the live path: PipeWire does the routing and mixing; this project is the control plane.

## Suggested first steps for a new maintainer

1. On a spare x86 machine with Debian 13: `sudo ./deploy/install.sh` (expect small fixes), then T0-T3 with two or three
   Bluetooth headsets that have a boom microphone. The number that matters most is simultaneous voice links per adapter.
2. Run T10 (latency) and T7 (range) honestly and write the numbers into `docs/results/`.
3. Decide whether Bluetooth is good enough for your venue. If range and latency matter most, USB-dongle (DECT) headsets are
   likely better; the routing layer is device-agnostic but **endpoints are currently keyed by Bluetooth address**, so
   supporting USB-audio endpoints means adding a node matcher in `pwgraph.py`/`engine.py` (moderate change).

## Ideas not built (see docs/09)

Program/show-relay feed into headsets, per-person volume and a hearing-safety limiter (use a proven PipeWire plugin and
test on real headsets), phone/Chromebook as a talk-and-listen endpoint (browser audio, needs HTTPS), wired/paging ports,
cue lights, per-group colours.

## Map of the code

`src/crewline/`: `model.py` (config), `routing.py` + `control.py` (pure logic), `engine.py` (daemon), `pwgraph.py` (PipeWire),
`bluez.py` (Bluetooth), `dtmf.py` + `commands.py` (dial codes), `mentions.py`, `network.py`, `captions/`, `web/` (aiohttp + a
no-build Preact UI, vendored, works offline). `deploy/` has the installer, systemd units and config. `tools/` and `crewline-probe`
are for hardware tests.
