# 4. Hardware validation plan and results log

**Status of every test below: NOT RUN.** This project was built overnight in a cloud
sandbox with no Bluetooth hardware, no PipeWire, and no headsets. The software is
unit-tested and exercised against a simulation; *none of the hardware behaviour has
been observed.* Nothing in this document is a result until its "Result" row is filled
in with real output.

Run the tests in order. Tests T0–T5 are Milestone 1 (two JLab headsets + the rotary
phone). Keep an unedited copy of each command's output in `docs/results/` (use the
template at the end). Every test uses the same on-appliance tool: `crewline-probe`.

Common setup: Debian 13 host (or the appliance), `deploy/install.sh` run, headsets
charged, `journalctl --user -u crewline-engine -f` open in a second terminal.

---

## T0 — Inventory and install

* **Why:** results are meaningless without versions.
* **Do:** `crewline-probe inventory --json docs/results/T0-inventory.json`
* **Record:** kernel, PipeWire, WirePlumber, BlueZ versions; each adapter's USB ID, `btmgmt info` supported settings, firmware messages.
* **Pass:** WirePlumber ≥ 0.5; adapters appear in `inventory` and are powered; `bluetoothd` running with `ControllerMode = bredr`.

## T1 — One headset, full duplex (microphone *and* earpiece)

* **Why:** "paired" and "plays music" prove nothing. We need a live voice (HFP) session.
* **Do:** open the pairing window in the admin UI, pair one JLab as endpoint "Test A". Then:
  * `crewline-probe nodes` — expect one `headset-head-unit` source *and* sink for its address; note `codec` (`cvsd` or `msbc`).
  * `crewline-probe record <ADDR> 10 /tmp/a.wav` while speaking, play it back: intelligible?
  * Admin → Diagnostics → *Earpiece test (beep)*: audible in the headset?
* **Pass:** both nodes present, mic recording intelligible, beep audible, stable for 10 minutes.
* **Record:** codec, any dropouts. Repeat with `bluez5.enable-msbc = false` (force CVSD) and note which is steadier at the *edge of range* (that decides the codec default for priority 1).
* **Failure signatures:** only an output node (headset stuck in A2DP) → the diagnosis page says so; no nodes → voice link failed (check `btmon`, adapter, kernel).

## T2 — Two headsets at once; capacity per adapter

* **Why:** the central unknown. Defines how many adapters to buy.
* **Do:**
  1. Pair two JLabs to the **same** adapter. Talk A↔B for 30 minutes (admin matrix shows both directions). Run `crewline-probe sco` and note both voice links.
  2. Pair a **third** headset (or the Cell2Jack) to the same adapter. Repeat.
  3. Repeat with each headset on its **own** adapter.
* **Pass for "N links per adapter":** N headsets + 30 min with no audible dropouts, `pw-top` shows no sustained xruns, every endpoint `two-way audio` in the status table, and all directions in the matrix carry audio.
* **Record:** the largest N that passes for CVSD and for mSBC. **Enter it in `docs/03-hardware.md` and in the adapter count.** Also record whether a link fails *quietly* (e.g. connected but no node) — the diagnosis wording must match what you see.

## T3 — Mixing and routing semantics

* **Why:** the architecture assumes PipeWire sums links into one earpiece.
* **Hardware-free test:** `python3 tools/pw_mix_selftest.py` (creates virtual sinks; PASS means both tones arrive near full level at the mix sink). *This script was written without PipeWire available; if port names differ, `pw-link -io` and fix the constants.*
* **With headsets:** three endpoints in one group; two talk at once (counting aloud together); the third should hear both, not just the loudest/last.
* **Pass:** both voices audible, no clipping distortion at the third headset.

## T4 — Cell2Jack and tone commands

* **Why:** dial codes and the "rotary phone" are core. How tones arrive is unknown.
* **T4a (what does the Cell2Jack do?)** Pair the Cell2Jack to the appliance as endpoint "Sound" (kind: rotary phone). Run `btmon | tee docs/results/T4-btmon.txt` in one terminal. Pick up the handset, wait 5 s, dial `1`, `2`, `0`, `7`, `8`, `*`, put the handset down for 10 s, pick it up again. Also record audio: `crewline-probe record <ADDR> 60 docs/results/T4-sound.wav` during the same sequence.
  * From `T4-btmon.txt` note which AT commands appear (`ATD…`, `AT+VTS=…`, `ATA`, `AT+CHUP`, `+CIEV`, `RING`, `AT+BCC`) and when.
  * Does the voice link (SCO) stay open when the handset is down? (`crewline-probe nodes` while on-hook.) **This decides whether on-hook can be detected and whether the mic stays live.**
  * `crewline-probe dtmf-scan docs/results/T4-sound.wav -v` — do the tones appear **in the audio**? At what level, twist and length? Which frames were rejected and why?
* **T4b (talk-off):** with the decoder enabled and **no** commands issued, let 30 minutes of real booth talk (including music/effects at show level) run through the rotary phone's microphone; count `digit` events in the engine log. **Pass: zero false commands.** A single JFK clip in the unit tests produced none, but that is not evidence for your room.
* **T4c (tone leak):** while another headset listens, dial `1` ten times. Record the listener's earpiece (acoustic recording) and measure how much tone is audible before the gate closes. Target: below audibility (<~50 ms). If audible, enable the optional look-ahead delay for the rotary endpoint only (07-intercom-behavior.md).
* **T4d (alternate path):** if tones arrive as `ATD`/`AT+VTS` and not audio, start `crewline-btsniff` and confirm digits reach the engine log ("digit X seen as AT command").
* **T4e (reserved codes):** the Cell2Jack may use `#*#` (pairing) and other key sequences itself (its manual could not be fetched during development). Check the real manual; do **not** map `#`/`*` until confirmed.
* **Decision outputs:** which path is primary; the true minimum tone length and level; whether `prefix = *` is needed.

## T5 — Headset buttons (actual behaviour)

* **Why:** "audio compatibility does not imply button compatibility." Nothing is assumed for any model.
* **Do:** run `crewline-btsniff --log docs/results/T5-btsniff.log` (or plain `btmon`) and in the admin UI open Endpoints → *Buttons* → **Learn buttons**. Press every button on the JLab: single tap, double tap, hold, and both volume keys, in two states: (a) HFP-only (our default), (b) with A2DP enabled (`bluez5.roles` including `a2dp_sink`) so AVRCP media keys exist.
* **Record per model:** the table of signals seen (`hfp-at` vs `avrcp`) for each physical action. Note that the **mute button almost certainly sends nothing** (it mutes inside the headset).
* **Identical units:** put two identical JLabs on one adapter, press a button on one, and see whether the signal is attributed to the right endpoint. HFP-AT is per device; AVRCP is not unless names/adapters differ.
* **Pass:** every mapping you want to offer has been *observed from that unit*; the UI only offers observed ones.

## T6 — Whisper intelligibility with production sound running

* **Do:** play representative show audio (music/effects/audience) in the room at show level. Whisper a standard list of 20 short sentences into each headset at the booth. Listener on another headset rates each 1–5; record the same audio with `crewline-probe record` for T11.
* **Compare:** (a) default (no processing); (b) optional expander if you decide to try it. Check that the *first word* of each sentence is intact (onset clipping).
* **Pass:** ≥90% of sentences fully understandable with defaults; no onset clipping.
* **Do not** introduce a voice gate to "fix" noise: tune with the expander or microphone placement.

## T7 — Coverage on real crew routes (priority 1)

* **Do:** map the routes crew walk (booth ↔ stage left ↔ stage right ↔ wings ↔ behind each scenery piece ↔ lobby). A tester walks each route continuously talking while the engine log records `connected=…/two-way-audio=…` transitions with timestamps and a second person listens at the booth grading each 5 m segment (clean / glitchy / dropped). Repeat: adapter in the central area (baseline = your current Chromebook range), adapter on a stand/extension, two adapters (zones), CVSD vs mSBC.
* **Pass:** documented coverage map at least as good as the current Chromebook setup in every location crew actually work; no *silent* drops (a dropped link must raise the readiness warning).
* **Record:** adapter positions, codec, dropouts per route. Output feeds the adapter placement in the real install.

## T8 — Recovery

For each event, record *seconds to restored audio* and *whether a human had to act*:

| Event | Expected |
|---|---|
| Headset power-cycled | auto reconnect within ~10–20 s (BlueZ `ReconnectAttempts`, `FastConnectable`); the engine switches it to HFP and re-links |
| One adapter unplugged/replugged | its headsets reconnect; others unaffected |
| `systemctl --user restart crewline-engine` | **audio continues** (links linger); controls return in seconds — verify talking never stops |
| `kill -9` the engine | same as above |
| `kill -9` the web process | no effect on audio; page offline until restart |
| Stop the caption server | audio unaffected; dashboard says captions unavailable |
| `systemctl --user restart pipewire wireplumber` | audio stops; headsets must re-establish voice links; record how long |
| `systemctl restart bluetooth` | same |
| Host reboot | all of it returns without login; record time |
| Pull the power | box boots; Bluetooth bonds persist; record time |

**The "links linger" claim is verified in source but not by experiment — this test is how it becomes fact.**

## T9 — Stable device-to-adapter assignment

* **Do:** with ≥2 adapters, pair each headset to a chosen adapter; reboot 5 times; also swap which USB port each adapter uses and replug in a different order.
* **Pass:** every headset reconnects through the same adapter each time (the status table shows the adapter's address); the UI's adapter column never shows an unexpected change. Bonds are per adapter *address*, not `hciN` index.

## T10 — End-to-end latency (priority 2)

Method (two-channel recording on **one** device so one clock times both events):

1. `crewline-probe click-train /tmp/clicks.wav --count 20 --interval 1.0`
2. Play `clicks.wav` from a laptop with a speaker placed against **headset A's boom microphone**; send the same signal electrically to **left channel** of a stereo recorder (line in).
3. Put a small microphone against **headset B's earcup** into the **right channel**.
4. Record 25 s. `crewline-probe latency recording.wav` → median / p95 / jitter.
5. **Calibration run:** repeat with the speaker→mic and cup→mic distances identical but *without* the intercom (headset A's mic replaced by a direct microphone into the recorder) to measure the fixed acoustic and recorder path; subtract it.
6. Repeat for: CVSD vs mSBC; one adapter vs two adapters; 2 vs 4 active headsets; each PipeWire quantum setting you try.

* **Reference points (general guidance, not looked up here):** one-way delays below roughly 150 ms are conventionally treated as unnoticeable in conversation, and above ~250–400 ms as disruptive. Compare to Google Meet measured the same way — you reported Meet as "noticeably" slow.
* **Pass:** your call; record the numbers and decide with the people using it.

## T11 — Caption engine on the real caption computer

* **Do:** record real audio from T6 (including whispers, with production noise). Provide reference transcripts. `python tools/asr_bench.py --wav … --ref "…" --engine sherpa-moonshine:DIR --engine sherpa-whisper:DIR:tiny.en …` for each candidate, on the *caption computer*.
* **Also:** concurrency — replay N simultaneous recordings and record CPU use and end-to-end caption delay (speech end → text visible on the dashboard).
* **Pass:** your call on WER and delay; the sandbox numbers in 10-caption-benchmarks.md are only a starting point.

## T12 — Full-crew rehearsal and soak

* **Do:** the intended endpoint count (8 headsets + rotary), real rehearsal ≥2 hours, show mode **on**, deliberate faults injected (switch a headset off, unplug an adapter, kill the caption server). Keep an incident log: time, symptom, who noticed, how fixed.
* **Pass:** no incident needed more than the documented recovery action; no unexplained audio glitches; readiness page accurate (what it said "ready" about really was).
* **Until this passes, do not call the system show-ready.** (See 08-known-limits.md.)

---

## Results log

Copy this table into `docs/results/<date>-<test>.md` for each run, with raw outputs attached.

| Field | Value |
|---|---|
| Test / date / who | |
| Host, kernel, PipeWire, WirePlumber, BlueZ | |
| Adapters (USB ID, positions) | |
| Headsets (model/generation/firmware) | |
| Codec(s) | |
| Procedure deviations | |
| Raw outputs (files) | |
| Result (pass / fail / partial), numbers | |
| Surprises / follow-ups | |

### Compatibility matrix (fill per headset model — also useful for other users of the project)

| Model / generation | Pairs | HFP voice (CVSD) | HFP wideband (mSBC) | 2 on one adapter | Buttons seen (source) | Battery reported | Notes |
|---|---|---|---|---|---|---|---|
| JLab GO Work (which gen?) | NOT TESTED | | | | | | |
| Cell2Jack | NOT TESTED | | | | | | |

### Results so far

*Nothing from hardware yet.* Software-only results that exist today: 121 automated tests (all passing in the build sandbox), the DTMF talk-off check on one speech clip (zero false digits across 18 speed/gain variants), and the caption benchmark in 10-caption-benchmarks.md.
