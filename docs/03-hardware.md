# 3. Hardware recommendation

**Read the risks before buying.** The one thing I could not establish from
documentation is *how many simultaneous two-way voice links one Bluetooth
adapter carries on Linux*. That number sets how many adapters you need, so the
recommendation below is a **staged purchase**: buy the validation kit first,
measure, then buy the rest.

## Recommended complete configuration

| # | Item | Qty | Why / evidence | Price evidence |
|---|---|---|---|---|
| 1 | **Intel N100-class mini PC**, 8 GB RAM, 256 GB SATA/NVMe SSD, gigabit Ethernet, BIOS option "power on after AC loss". Run **Debian 13**. | 1 | See comparison below. Quad core, SSD (no SD-card wear), can also host captions if T11 shows enough headroom. | Jan 2026: a complete N100 mini PC (16 GB/512 GB) ≈ **$247**, the same as a complete Pi 5 kit ([Jeff Geerling, 2026](https://www.jeffgeerling.com/blog/2026/raspberry-pi-cheaper-than-mini-pc/)). Check current price. |
| 2 | **ASUS USB-BT500** (Realtek RTL8761B, Bluetooth 5.0) | **2 for validation; plan 4–5 for 8–9 endpoints** | Linux `btusb` explicitly lists it as wideband-speech capable (`0b05:190e`). See "Adapter evidence" for what that does and does not prove. | ≈ **$14–20** per retailer listings ([search](https://www.cdw.com/product/asus-bluetooth-5.0-usb-adapter/6495099) shows $19.99). Not date-stamped. |
| 3 | **TP-Link UB500** (also RTL8761B, `2357:0604`) — *a second brand of the same chip family, so one bad batch doesn't take everything out* | 1–2 | Also flagged by `btusb`. | ≈ NZ$13–15 / AU$10–15 in listings seen; US price not verified. |
| 4 | **Powered USB 2.0 hub (7-port), plain USB 2.0** — *not* USB 3.0 | 1 | Placement and extension, not power (a dongle draws little). USB 3.0 ports radiate broadband noise in the 2.4 GHz band; Plugable's and Intel's guidance is to keep dongles on USB 2.0 ports away from USB 3.0 ([Plugable KB](https://kb.plugable.com/en_US/the-range-of-the-plugable-bluetooth-adapter-seems-poor-and-or-audio-is-skipping-or-lagging)). | not verified |
| 5 | **USB 2.0 extension cables, 1.5–3 m**, or active 5 m USB 2.0 repeater cables | 2–4 | To get each adapter out of the metal box, up onto a shelf/stand, and **near the people it serves**. | not verified |
| 6 | Small **UPS** or surge strip with a power switch labelled "do not touch" | 1 | A glitch that reboots the box is a show stopper; the box reboots into a working state, but still. Optional. | not verified |
| 7 | **Ethernet cable / switch port**, DHCP reservation (or static IP) | 1 | Local IP and `http://crewline.local:8080` (mDNS). | — |
| 8 | **Captions:** any laptop/desktop already available (≥4 cores) running `crewline-caption-server`; *optional* a second mini PC | 0–1 | Benchmark first (T11). | — |

Nothing else is required: no sound card, no microphone, no Wi-Fi.

## Host comparison (Pi 3B reuse vs newer Pi vs x86)

| | Reuse Pi 3B | Raspberry Pi 5 (or 4) | **x86 mini PC (recommended)** |
|---|---|---|---|
| Cost to start | $0 if you own it (unconfirmed) | parity with x86 in 2026 once PSU/case/cooler/SSD are counted | ≈ the same as a complete Pi 5 kit |
| Bluetooth (onboard) | **Unusable for voice**: on the Pi 3B's BCM43438 the SCO (voice) packets go to PCM pins that are not wired to anything; routing voice over the HCI link needs a vendor command ([kernel patch discussion](https://lkml.iu.edu/hypermail/linux/kernel/1806.1/00401.html), [Infineon](https://community.infineon.com/t5/Wi-Fi-Combo/BT-HFP-HSP-profile-on-CY43455-CY43438/td-p/161869)). Not verified on a 3B. We would use USB adapters only. | A Pi 5 needs no extra SCO config per one report ([source](https://www.sefod.eu/posts/raspberry_bluetooth_audio_routing/)); a Zero 2 W did. Unverified for our case. | Ignored (disable in BIOS) — use known adapters |
| USB | 4 × USB 2.0 shared with Ethernet on one internal hub (general knowledge; not confirmed here) | USB 3 + 2 | USB 3 + 2; plenty |
| CPU/RAM | 4×A53 1.2 GHz, 1 GB — fine for routing, tight for tone decoding/meters on 9 taps (unmeasured) and no room for captions | much better | more than enough; can host captions |
| Storage | SD card (wear/corruption risk) | SD or NVMe | SSD |
| Boot after power loss | automatic | automatic | BIOS setting required |
| Verdict | **Good enough for the Milestone-1 experiment, not for the show** | fine if you prefer it; no price advantage now | **Recommended** |

If you already own a Pi 3B, use it to repeat the milestone tests *with USB adapters* — it
gives a free second data point on whether a Pi is viable.

## Adapter evidence (what is and is not known)

**What the evidence supports**
* The Linux kernel's `btusb` driver has an explicit wideband-speech table entry for the ASUS
  USB-BT500 (`0b05:190e`) and TP-Link UB500 (`2357:0604`); both are Realtek RTL8761B. It
  uses USB alt-setting 6 when the adapter has it, otherwise 3 or 1 (source reading;
  [btusb.c](https://github.com/torvalds/linux/blob/master/drivers/bluetooth/btusb.c)).
* Adapters based on the old **CSR8510** (cheap generic dongles) are specified HFP 1.5/HSP 1.2 — no
  wideband — and clones are unreliable. Excluded.

**What it does not prove (these are why the validation kit comes first)**
* A driver table entry says the kernel will *try* wideband; it is not a test of
  simultaneous microphone-and-earpiece sessions.
* Reports of trouble exist: a commenter reported stuttering on an RTL8761 with HFP/mSBC under
  PipeWire on kernel 5.17 ([LinuxReviews](https://linuxreviews.org/Realtek_RTL8761B)); a 2025 kernel patch
  states HFP is "flaky on most existing USB Bluetooth controllers, varying by vendor"
  ([LKML](https://lkml.iu.edu/hypermail/linux/kernel/2503.3/08476.html)); an Ubuntu bug records a
  Realtek mSBC fix ([Launchpad 2007331](https://bugs.edge.launchpad.net/bugs/2007331)). Debian 13's kernel (6.12+) should
  include these fixes; confirm with `crewline-probe inventory`.
* **PipeWire issues report that a second connected headset gets no audio**
  ([PipeWire #2401](https://gitlab.freedesktop.org/pipewire/pipewire/-/issues/2401),
  [#3230](https://gitlab.freedesktop.org/pipewire/pipewire/-/issues/3230)). Those are old, mostly
  desktop/A2DP reports, but they are exactly the risk to retire in T2.
* I found **no** published figure for simultaneous HFP voice links per adapter on Linux. Background:
  the Bluetooth spec allows up to 3 SCO links per piconet (an older paper), and a TI controller
  datasheet limits one piconet to 2 ([datasheet](https://www.mouser.com/datasheet/2/405/cc2564-269802.pdf));
  Realtek's firmware limit is unknown. **Planning assumption until T2/T3 say otherwise: 2 voice
  links per adapter.** That gives 4 adapters for 8 headsets plus 1 for the rotary phone = 5 adapters if the
  limit is 2; 3 if 3 links/adapter work. The cost of being wrong is two $15 adapters, which is why the
  staged purchase is cheap.

## Range plan (priority 1)

Range is improved mostly by **geometry**, not by a more powerful dongle:
* A Bluetooth link works only as far as the *weaker* direction. Headsets are low-power Class 2 devices;
  a "long-range" Class 1 host adapter improves the host→headset leg but not the headset→host leg
  (engineering reasoning; not measured). So extra transmit power is worth less than closeness.
* Put adapters **high, in the open, close to the crew's working areas**, on 2.0 hubs/extension cables
  (not inside the metal PC, not behind a rack, not beside USB 3.0 ports).
* Use **several adapters in different places** (e.g. one stage-left, one stage-right, one at the booth)
  and pair each headset to the adapter that serves its normal area. Pairing is per adapter,
  so assignment is stable (test T9).
* Existing coverage "from the central area" is a good baseline: the first range test (T7) repeats your
  current Chromebook-to-headset walk with the adapter in the same place.
* The headset's own antenna and how it is worn dominate behind scenery; test with the actual people.

## Staged purchase (recommended order)

1. **Nothing**: run Milestone 1 on any x86 laptop with Debian 13 booted from USB (or the Pi 3B)
   using whatever USB Bluetooth adapters you have; run T0–T5.
2. **Validation kit (~two adapters + a hub + two cables)**: 2 × ASUS USB-BT500 (or one ASUS + one TP-Link), 1 × powered USB 2.0 hub,
   2 × USB 2.0 extension cables. Run T1–T10. Outcome: voice links per adapter, codec choice, latency, range, Cell2Jack path.
3. **Host + remaining adapters** once T2/T3 give a number; buy 1 spare adapter of each brand.
4. Full-crew rehearsal (T12) before relying on it.

## Risks before you spend money

| Risk | Likelihood (my judgement, unmeasured) | Mitigation |
|---|---|---|
| Adapter firmware limits voice links to fewer than hoped | medium | more adapters; two brands; staged purchase |
| PipeWire misroutes/blocks a second headset (old issue reports) | low–medium | T2; fall back to BlueALSA (documented alternative) or an older/newer PipeWire |
| Clock drift between several Bluetooth links causes glitches over hours | low–medium | T12 soak; PipeWire adaptive resampling |
| Cell2Jack only sends tones as AT commands, or closes voice when on-hook | medium | decoder supports in-band and AT; `crewline-btsniff`; T4 decides |
| JLab buttons send nothing useful to a host | **high for the mute button (local to headset)**; medium for others | phone remote + dial codes carry every essential function |
| Headset multipoint steals the headset to a student's phone | medium | admin procedure: forget the headset on phones; readiness shows disconnected |
| School Wi-Fi/Ethernet blocks client-to-client traffic (AP isolation) | medium | put the appliance on a wired port in the same VLAN as the viewing devices; use a dedicated travel router if needed |
| 2.4 GHz crowding (Wi-Fi, wireless mics, other Bluetooth) | site-specific | Bluetooth AFH hops around Wi-Fi; avoid Wi-Fi-heavy placement; T7 in the real room during a show |
