# 9. Headset features that could be used, and features you may be forgetting

## A. What earbuds, headsets and headphones can offer a host

"Reaches the host" = a signal Crewline can read. Everything marked *to test* is a hypothesis until T5 — the UI only
offers a mapping for a signal it has actually seen from that unit.

| Feature | Typical form | Reaches the host? | Use in Crewline |
|---|---|---|---|
| **Local mic-mute button** (boom headsets, e.g. JLab GO Work: "quick mute" + LED) | inside the headset | **No** (the host just hears silence) | Keep as is. UI shows "headset mute: unknown". Phone remote gives a *software* mute as well. |
| **Volume +/−** | HFP `AT+VGS` gain changes; AVRCP keys if A2DP/AVRCP is connected | HFP gain: *to test*; AVRCP: *to test* | Default: leave as earpiece volume (least surprise). Optional: map **hold** of a key to something else. |
| **Call / multi-function button** (tap, double, long) | `AT+CKPD=200` (HSP), `ATA`/`AT+CHUP`, `AT+BLDN` (redial = common "double press") | *to test* | Best candidate for **latched talk** or **Call Sound**. Double-press → redial signal is common in HFP headsets. |
| **Voice-assistant button** | `AT+BVRA=1`, only if the gateway advertises voice recognition | *to test*; may need an AG feature bit PipeWire does not set | Candidate for **Call Sound**. |
| **Media keys** (play/pause, next/prev) on earbuds and some headsets | AVRCP key events (BlueZ uinput) with press *and* release | *to test*; needs AVRCP connected; identical models ambiguous | Only source that supports **push-to-talk** (has release). Next/prev → group up/down. |
| **Touch gestures on true-wireless earbuds** (1/2/3 taps, hold) | vendor firmware turns them into the keys above or into local actions (ANC, assistant) | only if translated to the keys above | Same mapping UI; learn mode shows what a unit really sends. |
| **Wear/in-ear detection** | local; sometimes pauses media | usually **no** | Possible future "away" status if a model exposes it. |
| **ANC / ambient / EQ modes** | local or vendor BLE app | **No** (standard HFP) | Not used. For crew, "ambient/transparency" on is usually wise. |
| **Battery** | HFP battery indicator; BlueZ `Battery1`; PipeWire reports to UPower for HFP AG | *sometimes* | Shown only when reported; low-battery warning at ≤20%. |
| **Voice prompts** ("battery low", "mic muted") | local | **No** | Helpful as a second confirmation in the ear; keep enabled. |
| **Multipoint** (two devices at once) | local | n/a | **Risk**: a headset also paired to a student's phone may drift to it. Admin procedure: forget the headset on phones. |
| **Stereo** | A2DP | n/a | HFP is mono. Earbuds in HFP sometimes use **one bud only** (PipeWire issue #1181) — test earbuds before relying on them. |
| **Microphone type** | boom (JLab), in-line, bud mic | n/a | Boom mics are best for whispers and noise; earbud mics pick up less speech and more wind/scenery noise. Prefer boom headsets for active crew. |
| **Antenna / range** | small in earbuds, larger in on-ear headsets | n/a | Earbuds generally have **worse range** (priority 1): use for stationary roles, test with T7. |
| **Headphones with no microphone** | A2DP only | **Cannot join the voice intercom** | Could become *listen-only* endpoints (A2DP, higher quality, higher latency, no talk) for observers. Not built; possible. |
| **USB-dongle headsets / wired USB headsets** | UAC audio | n/a | Would appear as PipeWire nodes; routing layer is reusable. Fixed stations could use wired headsets. Not built. |

## B0. Compared with other intercom systems: still not built

* **Program / show-relay feed** into headsets (needs a non-Bluetooth source node in the PipeWire graph and a per-listener level; design it with real PipeWire in hand).
* **Per-person earpiece volume and a hearing-safety limiter** (the limiter should be a proven PipeWire filter-chain plugin, tested on real headsets; Bluetooth headset volume control is unverified).
* **Phone/Chromebook as a talk-and-listen endpoint** (browser audio, needs HTTPS for the microphone).
* **Wired/external audio ports** (venue paging or a mixer), cue lights.

## B. Features you may be forgetting (my suggestions, roughly by value)

Included already: per-person phone remote with cheat sheet; learn-buttons mode; readiness page; setup assistant; diagnosis by plain
language; Call Sound alert; name-mention alerts (screen + earpiece); crew announcements (text banner on every screen); own Wi-Fi hotspot with join QR; dark/night/light themes; printable sheets; backup/restore; no retention by default.

1. **Standby/cue announcements** — *(text banner on every dashboard/remote is built; a beep/audio version for headsets is not)* "Standby cue 12" / "Go", independent of voice.
2. **Show profiles** — one-click "Rehearsal / Show / Load-in" presets that swap groups and permissions (then lock).
3. **Private line** — *built* (permission per person; phone remote, dial code or button).
4. **Stuck-mic detector** — warn when an open mic has carried continuous noise for minutes (the classic open-mic-mix problem); the activity meter already has the data.
5. **Earpiece hearing-safety limiter** — a limiter in the PipeWire graph so a shout or feedback cannot hurt a student's ears (students are minors). Proven plugin, no custom DSP.
6. **Headset inventory and sign-out** — numbered labels, who has which, low-battery list for charging; "find my headset" beep.
7. **Coverage walk mode** — logs drops per location with a timestamp button on the phone ("I'm at stage left") to build the T7 coverage map automatically.
8. **Link-health trend** — "dropped 3× in 10 min" warning per headset (RSSI isn't reliably available for connected links).
9. **Incident log export** — connects/drops/restarts with times (no audio, no transcripts) for post-show debugging and for the open-source community's compatibility matrix.
10. **Loaner/guest headsets** — pairing that auto-forgets at the end of the day.
11. **Guided mic check** — the wizard version of the microphone/earpiece tests, per person, 20 seconds.
12. **Large-text / high-contrast caption display** for hearing-impaired crew or a big screen in the booth; colour-blind-safe group markers (group names are always shown, not only colours — already done).
13. **Teacher/observer view** — read-only dashboard with a PIN, no controls.
14. **Venue profile files** for the community: a shareable JSON of groups/names/dial codes for similar venues (the Backup file already does this).
15. **Remote (offsite) endpoint** — bridge to Mumble or a WebRTC page for a director off-site.
16. **Ring the rotary phone** to alert the sound operator (needs HFP call signalling; depends on T4).
17. **Show clock/timers** on the dashboard.
18. **Translation/second-language captions** (engine swap).
19. **Spare adapter hot-swap** procedure and a "which adapter has which headsets" map (partly done: adapter shown per endpoint).
20. **Meet fallback bridge** — only if you ever want the intercom audio *into* Meet for remote observers (note: that reintroduces an internet dependency; keep optional).

## C. Names of things (for the project)

The project is named **Crewline** ("party line" is the old intercom term for a shared channel). Rename in
one place if you prefer another: package `crewline`, services `crewline-*`, env vars `CREWLINE_*`.
License: **MIT** (see `LICENSE`), chosen so schools and other venues can use and adapt it freely. Bundled fonts, icons and
libraries keep their own permissive licenses (`vendor/LICENSES.md`). Apache-2.0 (explicit patent grant) or GPL-3.0 (keeps derivatives open) are the alternatives if you change your mind.
