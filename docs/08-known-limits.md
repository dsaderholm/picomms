# 8. Status, known limitations, and what is prototype-only

## Honest status (as of the overnight build)

| Area | State | Evidence |
|---|---|---|
| Config model, groups, permissions, show-mode lock, backup/restore | **Implemented, unit-tested** | `tests/test_routing_control.py`, `tests/test_store.py` |
| Routing logic (mix-minus, mute, latched/PTT, all-call, attention) | **Implemented, unit-tested** | same |
| DTMF decoder + command handling + tone gate | **Implemented, unit-tested on synthetic tones and one speech clip** | `tests/test_dtmf.py`, `tests/test_commands_cues.py` |
| Engine, local API, web UI (dashboard, remote, admin) | **Implemented; exercised against a simulation only**; UI screenshotted at phone/Chromebook/desktop sizes in a headless browser | `tests/test_engine_sim.py`, `tests/test_web.py` |
| Caption pipeline (segmenter, protocol, client/server, engines) | **Implemented; engines functionally run in a sandbox**; accuracy on real audio unknown | `tests/test_captions.py`, 10-caption-benchmarks.md |
| PipeWire adapter (`pwgraph.py`) | **Written against upstream source; parser unit-tested on synthetic `pw-dump` JSON; never run against a real PipeWire** | `tests/test_pw_bt_parse.py` |
| BlueZ manager (`bluez.py`) | **Written to the BlueZ D-Bus API; parser unit-tested; never run against real BlueZ** | same |
| Button support (AT/AVRCP sniffing, learn mode) | **Logic unit-tested; `btmon` text format reproduced from memory — must be validated** | `tests/test_buttons.py` |
| Install, systemd, WirePlumber/BlueZ config | **Written, syntax-checked only** | `deploy/` |
| **Everything that needs hardware** | **NOT RUN** | 04-validation-plan.md |

## Prototype-only vs show-ready

**Show-ready today: nothing.** The brief requires full-endpoint-count and rehearsal-duration testing before
declaring show readiness; neither has happened (T12). Until then:

* **Prototype (use for experiments, not shows):** the whole system.
* **Closest to ready once hardware tests pass:** routing/permissions, dashboard/remote/admin UI, config backup, the caption
  pipeline's isolation from audio.
* **Needs a design decision after hardware tests:** adapter count; codec default (range vs wideband); Cell2Jack tone path;
  whether the optional expander/look-ahead are needed.
* Keep the **Google Meet fallback** until T12 passes.

## Known limitations (design, not bugs)

* **Universal headset compatibility is not promised.** HFP is universal for microphone headsets, but individual models
  behave differently (multipoint, power-saving, voice-link quirks). Test each model (compatibility matrix in the plan).
* **Buttons:** a headset's *mute button* usually acts inside the headset and is invisible to the host. Other buttons may send
  no signal in HFP-only mode. The UI offers only buttons observed from that unit. Identical headsets cannot be distinguished by
  AVRCP key events alone (BlueZ names the device by model and uses the adapter address as PHYS); HFP AT commands are per device.
* **Battery** is shown only when BlueZ exposes it (`Battery1`); otherwise "unknown". **Headset hardware mute state is always
  "unknown"** — there is no reliable standard signal.
* **Adapter capacity** (simultaneous voice links) is unmeasured; the BOM assumes 2 per adapter.
* **Mono, narrowband/wideband voice only** — Bluetooth HFP is 8 kHz (CVSD) or 16 kHz (mSBC). Audio quality is deliberately
  priority 3; there is no music mode.
* **No echo cancellation** between endpoints. People sitting next to each other's *open speakers* is not a supported setup;
  headsets only.
* **Rotary phone:** hook state, ringing, and whether the voice link survives on-hook are unknown (T4). Ringing the phone is not built.
* **Phones as endpoints:** a phone cannot act as a Bluetooth *headset* to the appliance. Phones are supported as **dashboard/remote
  clients**; an audio-over-web endpoint (WebRTC) is a possible later feature (needs HTTPS for microphone access).
* **Captions:** English models only as tested; accuracy on whispers and booth noise is unmeasured; captions lag speech by about
  the segment length. Nothing is stored unless enabled; audio retention is not implemented (rejected by validation).
* **Security:** designed for a trusted LAN (password, LAN-only guard, CSRF header, CSP). Not designed for hostile networks;
  no TLS by default; remote links are bearer secrets.
* **Runtime selections** (who is muted, which group someone selected) are **not** persisted across restarts; endpoints return to
  their configured "home" groups. A reboot clears mutes — deliberate (nobody stays muted by surprise), but note it.
* **Not tested at all:** more than one simultaneous speaker through real hardware, hours-long drift, USB hub behaviour with 5 adapters.

## Things in the code that were verified by *experiment* in the sandbox

* 121 automated tests pass (`pytest`), including 7 headless-Chromium tests that click through the real pages.
* DTMF decoder: all 16 keys, twist limits, noise, harmonics; zero false digits on the JFK clip at 18 speed/gain variants, ~0.5–1% of a
  CPU core to decode a 16 kHz stream in pure Python.
* ActivityMeter detects a whisper-level signal (−42 dBFS) over a −64 dBFS noise floor in the unit test.
* Web security checks (login, CSRF header, LAN guard, remote-link scope, CSP without inline script) via HTTP tests.
* Pages render without console errors at 390×844, 1366×768 and 1600×900 in headless Chromium.
