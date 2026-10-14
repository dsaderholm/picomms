# 7. Intercom behaviour: groups, locks, mute, dial codes, cues

## Groups, listening and talking

* Two groups out of the box: **Tech** and **Stage**; add more in Admin → Groups.
* Each endpoint has **home** groups (what it starts with after a restart) and a **permission ceiling** (the most it may
  ever select). Talk and listen are separate sets: someone can *talk* to Stage while *listening* to both.
* Routing is mix-minus: you hear every permitted talker in the groups you listen to, except yourself (no sidetone).
* **All-call**: only endpoints with the permission can use it; while active, that endpoint reaches *everyone connected*,
  whatever they listen to. It ends by toggle, by selecting a group, by muting, or after a timeout (default 20 s).
* Everything above is covered by `tests/test_routing_control.py`.

## Lock vs mute vs lockout (three different things)

| | What it stops | Who | What it never does |
|---|---|---|---|
| **Show mode** (config lock) | Configuration changes: pairing, forgetting, disconnecting, names, groups, permissions, dial codes, button maps, restore | Admin turns it on/off | Never stops anyone hearing or using talk/mute/group-selection/Call Sound/reconnect |
| **Mute** | An endpoint's *transmission* | the person (button/remote/dial code) or an admin ("muted by administrator") | Never stops that person hearing |
| **Lockout** | — deliberately **not implemented** as "silencing someone's ears" | — | The strongest admin tool is *forced mute* or *disabled* (visible on the dashboard) |

Design rule: nothing labelled "lock" can ever silence what a person hears, so safety/essential communication
cannot be lost by a mis-click. Dashboard and remote show who is muted-by-admin and who is disabled.

## Talk modes

* **Open mic** — transmits whenever connected and not muted. Simple; adds everyone's background noise to the mix.
* **Latched talk** — tap to start, tap to stop (headset button where proven, phone remote, dial code). *Recommended for
  whispering booth users*: no voice-threshold decision is involved, so whispers and sentence starts are never cut.
* **Push-to-talk** — hold the remote button (or a headset key that sends press *and* release, i.e. AVRCP keys).
* Headsets with their own mute button keep it (it works inside the headset). The system cannot see it and shows
  "headset mute: unknown".

### "Should we use a gate for headsets without a mute button?"

Short answer: **not as the main mechanism.** A voice gate (open on speech, closed otherwise) chops sentence onsets and
drops whispers — the thing you ruled out. Preferred ladder:
1. **Explicit control** — latched talk or push-to-talk from the phone remote, or a headset button once proven on that model.
2. **Optional soft expander** (off by default, per endpoint): quiet noise is turned down by a fixed amount (e.g. 12–15 dB)
   with a very fast attack and a ~1 s hold, instead of being cut to silence. It runs on the *mix* path only; captions always
   get the ungated copy. Implementation plan: LSP Plugins expander in a PipeWire filter-chain (proven plugin, no custom DSP).
   **Not implemented yet and untested;** needs T6 with real show audio before use.
3. **Never** a hard gate.

## Dial codes (rotary phone)

You confirmed these defaults, and that the rotary phone's tones reach the appliance through the Cell2Jack 3 **as tones** (audio), which is what the decoder reads. Everything is editable under Admin → Dial codes.

| Dial | Action | Notes |
|---|---|---|
| 1 | Talk to **Tech** (listening unchanged) | You hear one beep, only in your own ear |
| 2 | Talk to **Stage** | Two beeps |
| 0 | **All-call** on/off (latched, auto-ends after 20 s or when you select a group) | rising three tones = on, falling = off |
| 7 | Mute / unmute your microphone | descending two tones = muted |
| 8 | Status beep (current group / mute / all-call) | |
| `#` and `*` | unused | The Cell2Jack may use `#*#` for pairing; avoid until its manual is checked |

### Private lines ("whisper")

A person with the permission *Can open private one-to-one lines* (Admin → People) can pick one other person on their phone remote (or by a dial code / button you map: *Private line to Sam*, *End private line*). While it is open **only that person hears them**; nobody else does, even in a shared group. It ends by itself after a time you set (default 60 s), when they mute, pick a group or start an all-call, and it is refused while muted. They hear a distinct cue (three equal low blips on, one low tone off). Dashboards show only "On a private line", never with whom; the engine's diagnostics ("Why can't X hear Y?") do say so, since only admins see them. Off by default per person. Nobody can use it to hear someone else, only to talk to them.

### Custom channels and more than 12 actions

* **Two groups is not a limit.** Tech and Stage are only the defaults: add as many groups as you like under Admin → Groups (Lights, Video, Front of house, Band, Wings…).
* A single dial key is limited to the 12 keys, so codes may also be **2–4 keys** (for example `2` `1` for a third group, `3` `0` `5` for something else). A code cannot be the start of a longer code (`2` and `21` cannot both exist), because without a "send" key the phone could not tell them apart; the editor refuses it and says why. The pause allowed between keys is a setting (default 2 s).
* **Headset cues:** every group has a cue of 1–5 beeps at a low, medium or high pitch: 15 different cues, still language-free and only in the affected person's ear. Group colours repeat after six groups; names are always shown, so nothing depends on colour.
* People choose among groups on their phone remote (any number of buttons), so dial codes are only needed for the rotary phone and for headset-free use.
* Not built: per-group colours, named "scenes" or per-person private lines (listed in 09-ideas); say if you want them.

Settings you can change (defaults in brackets): talking only or talking and listening when selecting a group (`select_scope`, talking only); all-call latched with auto-end (20 s) or momentary; an optional prefix key such as `*` to make accidental triggers by speech practically impossible (none). When the handset goes down: unknown until T4 (does the voice link close?).

### Preventing command tones from being broadcast

* The decoder watches your microphone's copy. The moment a DTMF-like tone appears (one 20 ms frame) your transmission is
  **closed**; it reopens 150 ms after the tone ends. The first part of the first tone can still leak: one 20 ms detection frame
  plus the time to remove the PipeWire link (a `pw-link` call, plus the graph's buffer) — my estimate is **50–100 ms, unmeasured**.
  Everything after that is gated. In simulation the engine test only asserts that the gate opens during the tone and closes
  afterwards; real leakage is measured in T4c (the engine records the gate-to-link delay as `last_gate_ms` in its state).
* If T4c finds the first 20–40 ms audible, enable the **look-ahead option** (planned, not built): a 50–100 ms delay line on the
  rotary endpoint only, via PipeWire's filter-chain `delay`, so the gate closes before the tone arrives. This costs the rotary
  phone's own speech 50–100 ms; nobody else is affected.
* Speech false triggers: harmonic/purity/twist checks plus a 40 ms minimum. One speech clip at 18 speed/gain variants produced
  zero digits and at most one momentary gate event per 11 s. That is a regression guard, not proof.

## Audible cues (language-free, only in the affected person's ear)

| Event | Cue |
|---|---|
| Selected group | N beeps, N = that group's "Beeps" setting (Tech 1, Stage 2) |
| Mute on / off | falling / rising two-tone |
| All-call on / off | rising / falling three-tone |
| Latched talk on / off | high / low blip |
| Not permitted | low double buzz |
| Status | two short beeps |

Cues are synthesized (`cues.py`) and played into that one headset's earpiece node only (never into a group). Whether the
narrowband codec and a real headset reproduce them clearly is for T1/T5.

## Attention ("Calling Sound")

* Raised by: the **Call Sound** button on a person's phone/Chromebook remote (works anywhere), a mapped headset button
  (where proven), or a dial code. **Never** by the speech recogniser.
* Shown as a persistent red banner on every dashboard until acknowledged; repeated presses by the same person collapse into one alert.
  Optional browser beep/vibration (user-enabled).
* **Name mentions** (supplementary, violet, never red): when captions contain a person's configured words, *their* dashboards and remotes flash violet and,
  if they wear a headset or hold the rotary phone, they hear two soft pings (the `mention` cue; one cue per target per 8 s by default; the screen alert is not rate-limited,
  and many mentions collapse to the newest with "N earlier / Clear all"). The speaker is never alerted about their own words. Words are matched whole-word and expanded
  (e.g. "DJ" → "d j", "dee jay"). Captions can miss or mishear: this is a nudge, not a guarantee.
* Everyone sees calls; mentions show only for the person the viewer says they are (set per device; defaults to the sound operator).
* **Ringing the rotary phone** to alert you is **not built**: it needs the host to signal an incoming call to the Cell2Jack
  (`RING`/`+CIEV` over HFP), which PipeWire's native backend does not do without a modem. Decide after T4 whether it matters.
