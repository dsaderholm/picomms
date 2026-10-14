# Crewline

A local **Bluetooth intercom appliance** for school tech/stage crews. Students' ordinary Bluetooth
headsets connect **directly to one small Linux box**; the box routes conversation between Tech/Stage
groups, understands dial codes from a rotary phone, shows **live captions and "Calling Sound" alerts** in any
browser (phone, Chromebook, desktop), and keeps working with **no internet** and when the caption computer or
the web page fails.

> **Status: prototype. Not show-ready.** Built overnight in a cloud sandbox with *no Bluetooth hardware*:
> the logic, UI and caption pipeline are tested; everything that depends on real headsets, adapters,
> the Cell2Jack, range, latency and whispers is **designed but not yet measured**. The validation plan
> says exactly what to run and what each result decides. See [docs/08-known-limits.md](docs/08-known-limits.md).

## Start here

| Read | For |
|---|---|
| [docs/01-requirements-and-assumptions.md](docs/01-requirements-and-assumptions.md) | What I assumed in place of your answers; what to correct |
| [docs/03-hardware.md](docs/03-hardware.md) | **Recommended hardware, comparison (Pi 3B / newer Pi / x86), risks, staged purchase** |
| [docs/02-architecture.md](docs/02-architecture.md) | Why PipeWire does the audio and Crewline only the control plane; failure isolation |
| [docs/04-validation-plan.md](docs/04-validation-plan.md) | The hardware tests (T0–T13), pass criteria, results log — **all NOT RUN** |
| [docs/07-intercom-behavior.md](docs/07-intercom-behavior.md) | Groups, lock vs mute vs lockout, dial codes and custom channels, cues, gates |
| [docs/06-operations.md](docs/06-operations.md) | Install, recovery, backup/restore, **pre-show checklist** |
| [docs/09-ideas-and-headset-features.md](docs/09-ideas-and-headset-features.md) | Headset/earbud features usable; features you may be forgetting |
| [docs/05-research.md](docs/05-research.md), [docs/10-caption-benchmarks.md](docs/10-caption-benchmarks.md) | Sources (marked verified / second-hand / unknown) and the sandbox ASR numbers |

## How it works (one minute)

```
headsets ──Bluetooth HFP──► BlueZ ► PipeWire (mic node + earpiece node per headset)
                                       │  links = "who hears whom"  (stock tools, keep running if Crewline dies)
                                       ├─ copy of each mic ─► crewline-engine ─► meters · dial codes · caption segments ─► caption PC
browsers ◄── crewline-web ◄── unix socket ◄── crewline-engine (routing rules, permissions, Bluetooth management)
```

* **No audio code of our own** is on the live path; no voice gate or noise suppression (whispers and sentence starts are preserved).
* **Phone/Chromebook remote** per person (talk, mute, groups, Call Sound, button cheat-sheet) — buttons on headsets are shortcuts, not requirements.
* **Show mode** locks configuration only; it never silences anyone's ears.
* **Name alerts:** say someone's name (or "DJ") and their screen flashes violet; headset and rotary-phone users hear two soft pings. Call Sound (red) stays the reliable alert.
* **Its own Wi-Fi:** the appliance can make a hotspot (5 GHz, join by QR code) and pass internet through from Ethernet or another Wi-Fi network, for venues where you cannot use the building's Wi-Fi.
* **Made for a dark booth and for students:** dark theme by default, a red-only *night* theme, a light theme, big touch targets, plain-language setup assistant, help page, printable cheat sheets.

## Develop and test (no hardware needed)

```
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[test]' pytest-asyncio pytest-timeout segno
pytest                                  # 173 tests (10 drive a headless browser)
# full simulated system with fake headsets + the web UI:
crewline-engine --sim --state-dir /tmp/cl --socket /tmp/cl/engine.sock &
crewline-web --listen 127.0.0.1:8080 --socket /tmp/cl/engine.sock --state-dir /tmp/cl --config /dev/null &
cat /tmp/cl/FIRST-RUN-ADMIN-PASSWORD.txt   # then open http://127.0.0.1:8080/ and /admin
```

Simulation mode is labelled with a banner on every page and is never evidence about real hardware.

## Layout

```
src/crewline/      engine, routing, control, dtmf, cues, bluez, pwgraph, captions/, web/, tools/
deploy/            installer, systemd units, WirePlumber + BlueZ config, backup/restore
tools/             asr_bench.py (caption benchmark), pw_mix_selftest.py (T3)
tests/             173 automated tests (logic, security, simulation, headless-browser UI flows)
docs/              the design, research, hardware, validation plan
```

## License

[MIT](LICENSE). Bundled third-party pieces keep their own licenses (see `src/crewline/web/static/vendor/LICENSES.md`).
