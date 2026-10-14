# 1. Requirements, answers received, and assumptions

You asked for the minimum essential questions first. You were asleep, then told
me to decide anything obvious myself, so I proceeded on the assumptions below.
**Each one is a decision I made, not a fact I verified.** Correct any that are
wrong; most only change a quantity in the hardware list.

## What you told me (taken as given)

| Fact | Source |
|---|---|
| Headsets are **JLab GO Work, Bluetooth only** (already bought). Dongle-based headsets are welcome *if better*, but are not the plan. | your messages |
| Money is not the main constraint; reliability is. "Way cheaper than something you would buy." | your messages |
| You want **every** Bluetooth headset to work. | your message — see "Universal compatibility" below |
| Priorities: **range → latency → audio quality**. | your messages |
| Students/crew carry no Chromebooks; the Chromebooks and phones are used for dashboards. | your messages |
| Captions, dashboard and remote must work on **phones, Chromebooks and a desktop**. | your message |
| Open-source on GitHub for other schools/venues. The name "PicoMMS"/"PiComms" was yours to replace → **Crewline** (say if you prefer to keep PiComms; it is a one-place rename). | your messages |
| The UI must work for high-school students, be **dark-friendly** (an open, dark tech booth), and still be feature-rich. | your messages |
| The appliance should be able to **create its own Wi-Fi network** (probably a must for ICS) and pass internet through from Ethernet or another Wi-Fi network. | your messages |
| Name mentions in captions should be hard to miss (screen flash; also for handset/rotary-phone users). | your messages |
| You own **Raspberry Pi 3Bs and mini PCs**; the JLab headsets were just bought. | your messages |
| You want per-headset button use maximised, with a phone web page as backup and a cheat-sheet that teaches the buttons. | your message |

## The essential questions, with the answer I assumed

| Question | Assumption used | What changes if wrong |
|---|---|---|
| How many simultaneous endpoints? | **Design for 8 headsets + the rotary phone (9).** Milestone 1 uses 2 headsets + the rotary. | Number of Bluetooth adapters (see 03-hardware.md). |
| Exact JLab model/generation? | **Unknown — please read the model name on the box or headset.** The original GO Work and the "Gen 2" have different published specs (Gen 2: Bluetooth 5.3, HSP/HFP/A2DP/AVRCP, quick-mute with mic LED, multipoint, 55+ h battery). All hardware claims about "JLab buttons" are therefore *unverified for your units*. | Which button signals exist. Nothing structural. |
| What hardware do you already own? | **Raspberry Pi 3Bs and mini PCs (your words; models unknown).** Prototype on a mini PC; use a Pi 3B only as a spare or an extra data point (its onboard Bluetooth cannot carry voice and its Wi-Fi is 2.4 GHz only). | Whether the first test needs a purchase: probably only USB Bluetooth adapters (and a 5 GHz Wi-Fi adapter for the hotspot). |
| Budget | **No hard cap; minimise risk, not cost.** | — |
| Separate computer for captions? | **Assumed yes** (a desktop/laptop you already own, or the same mini PC if it benchmarks well). | Whether captions share the appliance CPU. |
| Which Cell2Jack? How does it reach the host? | **It is a Bluetooth hands-free device from the host's point of view** (it presents itself like a headset to a phone). We pair it to the appliance instead of a phone. Whether the "tones" arrive as **audio** (in-band) or as **AT commands** (`AT+VTS`/`ATD`) is **unknown** — the design decodes both and test T4 settles it. | Which tone path is primary. |
| Is the rotary phone really tone-dialing? | **Assumed it sends DTMF tones** (you said tested). | If it sends pulses, a different decoder is needed. |

### Universal compatibility

I cannot honestly promise that *every* Bluetooth headset works, and the brief
asked me not to. What I can do, and did:

* Rely only on the **Hands-Free Profile (HFP)**, which every Bluetooth headset
  with a microphone implements. Narrowband (CVSD) voice is mandatory in HFP, so
  a headset that cannot do wideband (mSBC) still works at lower quality.
* Never depend on buttons for essential functions (phone remote + dial codes).
* Build a **per-headset test** (`crewline-probe`, the readiness page's
  diagnosis, and a compatibility matrix in the validation plan) so you learn
  which models work *before* a show, and so other schools can contribute results.
* Known failure classes: headsets that only do A2DP (music only, no microphone),
  headsets whose multipoint grabs another device, headsets that drop voice links
  on idle, and adapters with poor voice support. The diagnosis page names these.

## Requirements → where each is handled

| Requirement | Where |
|---|---|
| Local, no internet for core audio | 02-architecture.md (no cloud component anywhere in the audio path) |
| Transcription failure never interrupts audio | captions are a separate process on a copy of the audio; tests in `tests/test_captions.py`, `tests/test_engine_sim.py` |
| Management UI crash never stops audio | engine/web split; `pw-link` links linger (checked in PipeWire source) |
| Tech + Stage groups, configurable, listen vs talk, all-call, permissions | `model.py`, `routing.py`, `control.py` (tests in `tests/test_routing_control.py`) |
| Show-mode lock ≠ mute ≠ lockout | 07-intercom-behavior.md |
| Open mic / latched / push-to-talk | `routing.is_transmitting`; remote page; buttons where proven |
| Audible confirmation, only to the affected endpoint | `cues.py`, `engine.play` (test: cue goes only to the endpoint) |
| Rotary phone dial codes, no tone broadcast | `dtmf.py` (+ gate), `commands.py`; T4 |
| Captions + attention alert not dependent on recogniser | `control.Attention`; dashboard banner |
| Browser admin: pair, name, groups, perms, diagnostics, readiness | `web/` |
| Battery / hardware-mute only when reliably known | UI shows "unknown"; `tests` assert `battery is None` is never invented |
| No retention by default | `CaptionSettings`; audio retention is *not implemented* and rejected by validation |
| Preserve Google Meet fallback | nothing in this project touches the Meet setup; docs/06 recommends keeping Chromebooks charged as fallback |

## Open questions that need your answer (consolidated)

1. **Which JLab GO Work do you have** (original or "Gen 2"; model name/number on the box)?
2. **Which Cell2Jack model**, and is the rotary phone sending **tones** or **pulses**? (If you still have the Cell2Jack manual, check for reserved key sequences such as `#*#`.)
3. **Dial codes** (07-intercom-behavior.md): talk-only vs talk+listen; all-call latched vs momentary; prefix key or not; what should happen when the handset goes down?
4. **How many headsets at the real show** (I assumed 8 + the rotary phone)?
5. Which computer will run **captions** (and is a quiet-speech accuracy target needed, e.g. "90% of whispered phrases")?
6. **License** for the GitHub project (MIT / Apache-2.0 / GPL-3.0 …) — I did not choose one.
7. **GitHub:** the repository was empty, so I could only push my working branch (`claude/happy-dirac-yrwgay`) and could not open a pull request (a PR needs a base branch such as `main`). Choose/create the default branch and open the PR, or tell me to.
8. Project **name** — I renamed PicoMMS to **Crewline**; say so if you prefer another (it is a one-place rename) — and the GitHub repository is still called `picomms`.
