# 5. Research notes and sources

How to read this: **[S]** = I read the primary source (code or docs) myself;
**[R]** = a search-result summary or secondary page (not opened in full);
**[?]** = could not be verified. Build-sandbox limits: only GitHub raw files, PyPI and npm
were fetchable; most vendor and standards sites (Bluetooth SIG, ITU, Cell2Jack, JLab,
PipeWire docs site) were not, so some items are second-hand.

## Existing projects and what they tell us

| Project | What it is | Relevance |
|---|---|---|
| **Mumble** + **talKKonnect** (Go, MPL-2.0) [R, README read: S] | IP voice system; talKKonnect is a headless Mumble client for SBCs. README: ALSA + USB sound cards, no Bluetooth mention. [talkkonnect/talkkonnect](https://github.com/talkkonnect/talkkonnect) | Wrong topology for "all endpoints on one host" (one client + audio device per endpoint). Rejected; see 02-architecture.md. |
| talkiepi / barnard, raspi stage intercom [R] | Mumble-based Pi intercoms ([marcuswolschon/raspi_stage_intercom](https://github.com/marcuswolschon/raspi_stage_intercom)) | Wired headsets via USB sound cards; confirms the usual approach is not Bluetooth. |
| PipeWire routing guide for two Bluetooth headsets [R] | Linking nodes in PipeWire ([0110.be](https://0110.be/posts/Connecting_two_Bluetooth_headsets_to_your_Linux_system%3A_audio_routing_in_PipeWire)) | Supports "routing = links in the graph". Output-only. |
| HFP for Linux (nohands) [R] | An old project making Linux a hands-free *unit* | Wrong role (we need the gateway role). |
| BlueALSA (arkq/bluez-alsa) [R] | ALSA plugin for BlueZ audio; supports HFP/HSP; "call management out of scope" ([wiki](https://github.com/arkq/bluez-alsa/wiki/Using-BlueALSA-with-HFP-and-HSP-Devices)) | Documented fallback if PipeWire mishandles multiple HFP headsets (T2). |
| oFono HFP AG plugin [R] | Telephony stack with an AG role | Heavier alternative; not used. |
| Commercial: Clear-Com, RTS, Pliant CrewCom; apps LiveIntercom, SyncFlowBoard [R] | Purpose-built intercoms ([search results](https://products.rtsintercoms.com/download/99972)) | Prove the product category; none uses stock Bluetooth headsets with captions. No open-source Bluetooth crew-intercom appliance was found. |

## Bluetooth on Linux: findings

1. **PipeWire native HFP backend** (`spa/plugins/bluez5/backend-native.c`, master) [S]:
   AG-role AT handling: `AT+BRSF`, `AT+BAC`, `AT+CIND`, `AT+CMER`, `AT+BCC` (mSBC), `AT+VGS/VGM` (volume),
   `AT+CKPD=200` (HSP; triggers a **profile switch**). `ATA`, `ATD`, `AT+CHUP`, `AT+VTS` are forwarded to
   ModemManager only when a modem exists; otherwise answered with an error. → *PipeWire will not
   surface Cell2Jack digits or call-button presses.* Source: [GitHub mirror](https://github.com/PipeWire/pipewire/blob/master/spa/plugins/bluez5/backend-native.c).
2. **PipeWire 1.6.0** (2026-02-19) is current; adds a bluetooth LDAC decoder and SpanDSP packet-loss concealment [S, NEWS]; 1.4.x is what Debian 13 ships [?].
3. **WirePlumber bluetooth settings** [S]: `bluez5.roles`, `bluez5.hfphsp-backend`, `bluez5.auto-connect`, `bluetooth.autoswitch-to-headset-profile`; initial profile cannot be set by property (WirePlumber applies its own policy), so the engine switches profile explicitly ([docs](https://github.com/PipeWire/wireplumber/blob/master/docs/rst/daemon/configuration/bluetooth.rst)).
4. **`pw-link` links persist** after the tool exits (default linger) [S] ([pw-link.c](https://github.com/PipeWire/pipewire/blob/master/src/tools/pw-link.c)).
5. **`pw-dump` schema**: links expose `output-node-id/input-node-id/…-port-id`; bluez nodes carry `api.bluez5.address/profile/codec` [S] ([pw-dump.c](https://github.com/PipeWire/pipewire/blob/master/src/tools/pw-dump.c), [bluez5-device.c](https://github.com/PipeWire/pipewire/blob/master/spa/plugins/bluez5/bluez5-device.c)).
6. **Kernel `btusb`** [S]: SCO USB alt-setting selection (CVSD: by link count up to 3; transparent/mSBC: alt 6, else 3 (Realtek, MTU ≥72), else 1); wideband-speech table includes `0b05:190e`, `2357:0604` ([btusb.c](https://github.com/torvalds/linux/blob/master/drivers/bluetooth/btusb.c)).
7. **AVRCP key events** [S]: uinput device named `<device name> (AVRCP)`, PHYS = adapter address ([avctp.c](https://github.com/bluez/bluez/blob/master/profiles/audio/avctp.c)). Identical headsets are not distinguishable by this source alone.
8. **Bluetooth capacity** [R]: spec allows up to 3 SCO links per piconet ([2004 paper](https://www.cs.nccu.edu.tw/~ttsai/mobilecomm_ttsai/papers2004/0205misi.pdf)); a TI CC256x datasheet limits one piconet to 2 SCO ([datasheet](https://www.mouser.com/datasheet/2/405/cc2564-269802.pdf)). **No Linux-specific figure for simultaneous HFP voice links per adapter was found.** [?]
9. **Reports of multi-headset trouble** [R]: PipeWire issues [#2401](https://gitlab.freedesktop.org/pipewire/pipewire/-/issues/2401) (second headset connects but gets no audio), [#3230](https://gitlab.freedesktop.org/pipewire/pipewire/-/issues/3230), [#3934](https://gitlab.freedesktop.org/pipewire/pipewire/-/issues/3934); a "mic works only once per connection" HFP bug ([abrus861/pipewire-hfp-atbcc-fix](https://github.com/abrus861/pipewire-hfp-atbcc-fix)). Versions/dates not reviewed — they define what to retest.
10. **Raspberry Pi 3B onboard Bluetooth**: BCM43438 sends SCO to PCM pins that are not connected on the Pi 3B; routing over HCI needs a vendor command [R] ([LKML](https://lkml.iu.edu/hypermail/linux/kernel/1806.1/00401.html)). Unverified on a 3B.
11. **USB 3.0 interference** with 2.4 GHz dongles; use USB 2.0 ports/hubs away from USB 3.0 [R] ([Plugable KB](https://kb.plugable.com/en_US/wireless-usb-device-not-working-on-usb-30-hub)).

## Devices

* **JLab GO Work** [R]: product pages list (Gen 2) Bluetooth 5.3, HSP/HFP/A2DP/AVRCP, SBC/AAC, quick-mute button with mic LED, multipoint (two devices), range "30+ ft", 55+ h battery; a retailer listing for the original model mentions a 2.4 GHz USB-C dongle and wired use ([JLab UK Gen 2](https://uk.jlab.com/products/go-work-wireless-on-ear-headset-gen-2), [JLab CA](https://www.jlab.com/en-ca/products/go-work-wireless-on-ear-headset)). Which generation you have is unknown. **What signals the buttons send to a host is not documented anywhere I could find.**
* **Cell2Jack** [R]: bridges a cell phone to an analog phone; "works like a Bluetooth headset for the phone"; pairing started from the handset keypad with `#*#`; the manual and any DTMF/hook behaviour could not be read ([manual summary](https://manuals.plus/cell2jack/cellphone-to-home-phone-adapter-manual), [Cell2Jack store](https://www.amazon.com/stores/CELL2JACK/page/5CBBB1E9-37ED-4ACA-84A0-11A01136541D)). Everything beyond that is unverified [?].
* **HFP and DTMF**: the hands-free unit sends DTMF as `AT+VTS` *during a call* ([ESP-IDF HFP client docs](https://docs.espressif.com/projects/esp-idf/en/v5.2.5/esp32/api-reference/bluetooth/esp_hf_client.html)); the Cell2Jack may instead place a call (`ATD`) when digits are dialled. Real captures decide (T4).
* **DTMF detection** [R]: Goertzel is the standard approach; speech "talk-off" is controlled with harmonic checks and strict twist ([Zilog AN0018](https://www.zilog.com/docs/modem/appnotes/an0018.pdf), spandsp header: normal twist ≤8 dB, reverse ≤4 dB, min tone-on 40 ms). ITU Q.24 tolerances were not read at the source; the search results disagree on minimum tone duration (23 ms vs 40 ms). Crewline defaults to 40 ms.

## Speech recognition

* sherpa-onnx streaming Zipformer, Moonshine, Whisper-via-ONNX, faster-whisper were evaluated; no head-to-head published benchmark on quiet/whispered speech on small CPUs was found [R]. Whisper-type models degrade on whispered speech in published work ([arXiv 2311.05179](https://arxiv.org/pdf/2311.05179), [arXiv 2508.13060](https://arxiv.org/html/2508.13060v1)); our own tiny sandbox run is in 10-caption-benchmarks.md.
* Moonshine v2 reports low-latency streaming encoder results (vendor claims) ([arXiv 2602.12241](https://arxiv.org/pdf/2602.12241)); not tested here.

## Prices seen (not date-stamped, verify before buying)

* ASUS USB-BT500: ≈$14–20 US retail ([CDW $19.99](https://www.cdw.com/product/asus-bluetooth-5.0-usb-adapter/6495099)).
* TP-Link UB500: ≈NZ$13–15 / AU$10–15 ([PB Tech](https://www.pbtech.com/pacific/product/NETTPL55500/TP-Link-UB500-Bluetooth-53-Nano-USB-A-Adapter)).
* Complete N100 mini PC vs Pi 5 kit: both ≈$247 (Jan 2026) [R] ([Geerling](https://www.jeffgeerling.com/blog/2026/raspberry-pi-cheaper-than-mini-pc/)).
* Everything else: **not verified**.
