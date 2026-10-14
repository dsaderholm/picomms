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
| 7 | **Ethernet cable / switch port**, DHCP reservation (or static IP) | 1 | Local IP and `http://crewline.local:8080` (mDNS); also the preferred internet source for hotspot passthrough. | — |
| 7b | **Dual-band USB Wi-Fi adapter with AP mode** (e.g. ALFA AWUS036ACM) — *only if the appliance should create its own Wi-Fi* | 0–1 | See "Hotspot hardware". | ≈ $40–60 (not verified) |
| 8 | **Captions:** any laptop/desktop already available (≥4 cores) running `crewline-caption-server`; *optional* a second mini PC | 0–1 | Benchmark first (T11). | — |

Nothing else is required for the intercom itself: no sound card, no microphone. **If the appliance
should make its own Wi-Fi network** (see "Hotspot hardware" below, which is likely for ICS), add one
dual-band USB Wi-Fi adapter that can act as an access point.

**Sized for your crew (about 6 endpoints: 3 JLab + Cell2Jack + ~2 others):** with the planning assumption of 2 voice links per adapter that is **3 USB Bluetooth adapters**, plus 1 spare. If T2/T3 show 3 links per adapter, 2 may do. Spreading the adapters (booth, stage left, stage right) also helps range.

**Your old Intel NUC (i7/i8-generation) is a good host:** more than enough CPU (it could also run captions; benchmark in T11), SSD, Ethernet, and set BIOS "power on after AC loss". Do **not** rely on its internal Wi-Fi/Bluetooth card for the headsets: it sits inside a metal case (poor range) and Intel combo cards are untested here for multiple voice links. Use external USB adapters on short cables, and treat the internal one as a free extra data point in T2. Its internal Wi-Fi may not be able to host a 5 GHz hotspot (many Intel cards restrict it): check `iw list` for `AP` and 5 GHz, otherwise use the USB Wi-Fi adapter.

**You already own hardware:** you said you have Raspberry Pi 3Bs and several mini PCs. Use a **mini PC** for
the prototype and the show (x86, SSD, Ethernet, USB 2/3). Keep the Pi 3B for tests or as a spare; see the host
comparison. The JLab headsets need no purchase; only the USB Bluetooth adapters (and optionally a Wi-Fi
adapter) are new money.

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

You told me you own Pi 3Bs and mini PCs. The mini PC is the recommended host. If you want a free data point, use a Pi 3B to repeat the milestone tests *with USB adapters* — it
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

## Hotspot hardware (the appliance makes its own Wi-Fi)

For venues where you cannot use the building's Wi-Fi, the appliance can be the Wi-Fi network (Admin → Network)
and share internet from Ethernet or from another Wi-Fi network. This needs a Wi-Fi radio that supports
**access-point (AP) mode**; check with `iw list` (look for `AP` under "Supported interface modes").

* **Use 5 GHz.** Bluetooth lives at 2.4 GHz; a 2.4 GHz hotspot on the same box competes with every headset.
  Crewline defaults to 5 GHz and offers only non-DFS channels (36–48, 149–165) because radar-avoidance
  channels can make the hotspot vanish. It warns before you choose 2.4 GHz.
* **A separate adapter, placed away from the Bluetooth adapters** (extension cable). Do not rely on a combo
  Wi-Fi/Bluetooth chip for the headsets.
* **Candidate: ALFA AWUS036ACM (MediaTek MT7612U).** In-kernel driver since Linux 4.19 per the
  [maintainer's page](https://github.com/morrownr/7612u); it notes 5 GHz AP mode may want the `disable_usb_sg` module
  option and that DFS channels are not supported in AP mode (we avoid them anyway). One
  [forum report](https://forum.openwrt.org/t/ap-mode-crashing-raspberry-pi-3b-w-two-alfa-awus036acm-mt7612u-wireless-usb-adapters-openwrt-21-02/115931)
  has AP mode crashing under heavy load with *two* such adapters on a Pi 3B/OpenWrt. Not tested by me; verify with T13.
* **Pi 3B:** its onboard Wi-Fi is 2.4 GHz only, so a Pi 3B hotspot would share the headsets' band. If you use a Pi
  for the hotspot, add a 5 GHz USB adapter.
* **Passthrough:** plug the venue's Ethernet into the appliance (preferred) or join the venue's Wi-Fi with a
  *second* Wi-Fi adapter (one radio cannot reliably be hotspot and client at once). The intercom never needs
  internet; it is only for phones on the hotspot and updates.
* The hotspot password is stored on the appliance (and in backups); the join QR and print sheet show it to the crew.
  WPA2-PSK (CCMP).

## Range plan (priority 1)

Range is improved mostly by **geometry**, then by adapter choice:
* Put adapters **high, in the open, close to the crew's working areas**, on 2.0 hubs/extension cables
  (not inside the metal PC, not behind a rack, not beside USB 3.0 ports).
* Use **several adapters in different places** (e.g. one stage-left, one stage-right, one at the booth)
  and pair each headset to the adapter that serves its normal area. Pairing is per adapter,
  so assignment is stable (test T9).
* **Antenna gain helps in both directions** (a better antenna also hears better), and a Class 1 radio
  usually has a better *receive* sensitivity as well as more transmit power. So a Class 1 adapter with a
  detachable external antenna is a real, if modest, range upgrade. What it cannot fix is a weak
  *headset* transmitter (Class 2, tiny antenna, worn on a head): the uplink is still the limit, which is why
  geometry comes first. This corrects an earlier note in these docs that said extra host power only helps one direction.
* Existing coverage "from the central area" is a good baseline: the first range test (T7) repeats your
  current Chromebook-to-headset walk with the adapter in the same place.
* The headset's own antenna and how it is worn dominate behind scenery; test with the actual people.

### Long-range adapter candidates (none tested by me; treat as a bake-off, T7b)

I searched for long-range options. The honest result: **vendor range claims ("100 m") are open-air
best case and not independently measured; I found no Linux HFP range test of any of them.** Choose by chipset,
because the chipset decides whether Linux and HFP work:

| Candidate | Chipset (per listing) | Notes | Risk |
|---|---|---|---|
| **StarTech Bluetooth 5.3 Class 1 USB adapter** (AV53C1-USB-BLUETOOTH) | RTL8761BUE per one retailer listing | Class 1, 5.3; listing says Linux kernel ≥ 5.19; antenna type not clear from the listings. Same chip family as the ASUS/TP-Link adapters, so the wideband path in `btusb` applies. | Verify chipset with `lsusb`/`crewline-probe inventory`; range unmeasured |
| **Techkey Bluetooth 5.4 Class 1** | not stated | 5 dBi external antenna per one review blog (a claimed 120 ft through three interior walls, one reviewer's test); Linux support not confirmed | Unknown chipset; check before buying |
| **Feasycom FSC-BP119** | CSR8510A10 (vendor datasheet) | Class 1, SMA connector for a swappable antenna, HFP 1.5/HSP 1.2, plug-and-play on Linux in HCI mode per the vendor | **CVSD only (no wideband)**: narrower voice, but arguably fine under *range → latency → quality*. CSR clones are common; buy from the vendor |
| Generic "100 m" RTL8761B sticks | RTL8761B | Usually Class 2 or Class 1 with a stub antenna; spec sheet rarely says | Likely no better than the ASUS/TP-Link |

Plan: buy **one** of each of the first rows with a detachable antenna next to the validation kit, then run the
same walk-away test (T7) with each, same spot, same headset, and record the result in `docs/compatibility.md`.
Do not buy five of anything before that. A *directional* or higher-gain antenna on an SMA adapter is the cheapest
experiment; keep the antenna vertical and in the open, and avoid putting it near a USB 3 cable.

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
| School Wi-Fi/Ethernet blocks client-to-client traffic (AP isolation) | medium | **use the appliance's own hotspot** (viewers join it directly), or a wired port in the same VLAN |
| The hotspot hurts Bluetooth range (same 2.4 GHz band, or adapter proximity) | medium if 2.4 GHz; low on 5 GHz | 5 GHz default, separate adapter on a cable, T13 + T7 with the hotspot busy |
| 2.4 GHz crowding (Wi-Fi, wireless mics, other Bluetooth) | site-specific | Bluetooth AFH hops around Wi-Fi; avoid Wi-Fi-heavy placement; T7 in the real room during a show |
