# 6. Operations: install, startup, recovery, backup, pre-show checklist

> **Not yet run on real hardware.** `deploy/install.sh` passed `bash -n` and shellcheck
> but has never executed on a Debian machine (the build sandbox had no apt access).
> Treat the first install as test T0 and expect to fix small things.

## Install (selected host: x86 mini PC, Debian 13 "trixie")

1. Install Debian 13 (minimal, SSH server, no desktop). In BIOS: *power on after AC loss*, disable the
   internal Wi-Fi/Bluetooth, boot from SSD.
2. Give it a **wired** network port and (recommended) a DHCP reservation. Set the hostname:
   `sudo hostnamectl set-hostname crewline` and `sudo apt install avahi-daemon` so
   `http://crewline.local:8080` works on phones and Chromebooks (mDNS).
3. Plug the Bluetooth adapters into the **powered USB 2.0 hub** / extension cables (not next to USB 3.0 ports).
4. `git clone <your repo> && cd crewline && sudo ./deploy/install.sh`
   (offline installs: `pip download` the wheels once and pass the folder as the first argument).
5. The installer prints the **first-run admin password** once (also in `/var/lib/crewline/FIRST-RUN-ADMIN-PASSWORD.txt`).
   Change it: `sudo -u crewline crewline-web --set-password`, then delete that file.
6. Open `http://<ip>:8080/admin`, log in, run **Status → readiness**.
7. Pair headsets (Devices → open pairing window → *Pair as…*). Name them by person/role.
8. Send each person their **Remote link** (Endpoints → *Remote link*, QR code for phones).
9. Put the box on a UPS or at least a surge strip. Do not run it from a laptop battery.

### What the installer sets up
* user `crewline` (in `bluetooth`, `audio`), lingering user session running PipeWire, WirePlumber, `crewline-engine`, `crewline-web`;
* `/etc/wireplumber/wireplumber.conf.d/50-crewline.conf` (HFP-only, no profile auto-switching, no node suspend);
* `/etc/bluetooth/main.conf` additions (`ControllerMode = bredr`, `FastConnectable`, reconnect attempts);
* `/etc/modprobe.d/crewline-btusb.conf` (no USB autosuspend);
* `/etc/crewline/web.toml` (LAN-only guard, viewer mode);
* `crewline-backup` / `crewline-restore` in `/usr/local/sbin`.

## Automatic startup and what restarts what

Everything is a systemd service with `Restart=always`. After power-on: network → `bluetooth.service` →
user session (lingering) → `pipewire`/`wireplumber` → `crewline-engine` → `crewline-web`. The engine retries
if PipeWire is not ready (it does not crash-loop). Headsets reconnect by themselves when switched on
(BlueZ reconnect + the engine's profile switch + link reconcile each second). No login, keyboard or monitor needed.

## Recovery behaviour (designed; to be proven in T8)

| Symptom | What happens | What you do |
|---|---|---|
| One headset drops | it disappears from "two-way audio"; others unaffected; readiness warns | switch it off/on; press **Reconnect** in admin (allowed even in show mode) |
| Engine crashes | links stay; talking continues; tone commands/mute buttons pause; systemd restarts it in ~1 s | nothing |
| Web UI crashes | no audio effect | nothing (restarts) / `systemctl --user restart crewline-web` as `crewline` |
| Caption PC off | captions say "unavailable"; audio and attention alerts fine | nothing |
| PipeWire/BlueZ restart | audio interrupts until voice links re-establish | wait ~30 s; switch headsets off/on if needed |
| Box rebooted | back in about a minute (not measured) | wait |
| Something truly wrong | fall back to the Google Meet setup (keep Chromebooks charged) | — |

Handy commands (run as root; `U=$(id -u crewline)`):

```
runuser -u crewline -- env XDG_RUNTIME_DIR=/run/user/$U systemctl --user status crewline-engine crewline-web
runuser -u crewline -- env XDG_RUNTIME_DIR=/run/user/$U journalctl --user -u crewline-engine -f
crewline-probe nodes        # what PipeWire sees
crewline-probe sco          # voice links per adapter (hcitool)
```

## Backup and restore

* **Settings only (any time, from the browser):** Admin → *Backup & restore* → Download. It holds groups, endpoints (with
  Bluetooth addresses), permissions, dial codes, caption settings. It does **not** hold Bluetooth pairing keys.
* **Automatic versions:** the last 20 saved configurations are in `/var/lib/crewline/backups/`.
* **Full backup** (settings + pairing keys + admin credentials): `sudo crewline-backup` → tarball.
  Restore with `sudo crewline-restore <file>`. Pairing keys are tied to each adapter's address: they only help
  if the **same physical adapters** are used. On new adapters, headsets must be paired again (settings restore is fine).
* Keep a copy off the box (USB stick or school drive). The tarball contains secrets — store it like a password.

## Show mode, passwords, network

* **Show mode** (Admin → top bar) locks configuration only. Crew can still talk, mute, change groups within their
  permissions, call Sound; reconnecting a headset is allowed. See 07-intercom-behavior.md.
* **Never expose the appliance to the internet.** It refuses non-private client addresses by default, but also do not
  port-forward it and keep it off guest Wi-Fi. School networks sometimes block client-to-client traffic: put the appliance
  and the viewing devices on the same VLAN/SSID, or give it a small dedicated Wi-Fi router.
* **HTTPS (optional):** the pages work over plain HTTP on the LAN. Two browser features need HTTPS and are hidden otherwise:
  "keep screen on" (wake lock). If you want it, put Caddy/nginx in front with a certificate from your school CA.
* Viewer PIN: set `viewer_mode = "pin"` and `viewer_pin` in `/etc/crewline/web.toml` if you do not want the dashboard
  open to everyone on the LAN. Remote links are per-person secrets; rotate if one leaks.
* **Privacy:** audio is never recorded (not implemented). Transcripts are not kept unless an admin ticks the box; the
  Captions tab shows that state.

## Pre-show checklist (≈3 minutes)

1. Power on the box and the caption computer (if used). Wait ~1 minute.
2. Switch on every headset (and the Cell2Jack/rotary phone). Stand near the crew area for ~20 s.
3. Open **Admin → Status** (or `/admin` on the booth computer). Everything green? Read any red/yellow line — each says what to do.
   * ✗ *no two-way audio*: switch that headset off/on; if it persists use **Diagnostics → Diagnose**.
4. **Microphone test** and **Earpiece test** on any headset that changed since the last show (Diagnostics).
5. Dial `1`, then `2` on the rotary phone: you should hear 1 beep, then 2 beeps; the other headsets must **not** hear the tones.
6. Press **Call Sound** from one phone remote: the dashboard banner must appear; acknowledge it.
7. Check captions on the dashboard (say a sentence). Not required for the show: audio never depends on it.
8. Turn **Show mode on** (lock configuration).
9. Keep the Google Meet fallback ready (Chromebooks charged) until the system has passed the T12 rehearsal.

After the show: show mode off; check **Backup → Download**; charge headsets.
