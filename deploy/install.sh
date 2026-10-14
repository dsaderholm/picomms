#!/usr/bin/env bash
# Crewline installer for Debian 13 (trixie) / Raspberry Pi OS (trixie) on a fresh machine.
# Idempotent. Run as root from a checkout:  sudo ./deploy/install.sh
# Not yet run on real hardware: treat the first run as part of validation step T0.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
PREFIX=/opt/crewline
STATE=/var/lib/crewline
CONF=/etc/crewline
WHEELHOUSE="${1:-}"        # optional: directory of pre-downloaded wheels for offline installs

[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
. /etc/os-release
case "${VERSION_CODENAME:-}" in
  trixie|forky) ;;
  *) echo "WARNING: tested target is Debian 13 (trixie); found ${PRETTY_NAME}. PipeWire/WirePlumber may be too old (need WirePlumber >= 0.5)." ;;
esac

echo "== packages"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  pipewire pipewire-bin pipewire-audio wireplumber libspa-0.2-bluetooth \
  bluez python3 python3-venv python3-pip usbutils rfkill chrony ca-certificates \
  libsndfile1 pulseaudio-utils avahi-daemon

wp_ver=$(wireplumber --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1 || echo "0.0")
echo "WirePlumber ${wp_ver}; PipeWire $(pipewire --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
awk -v v="$wp_ver" 'BEGIN{split(v,a,"."); exit !((a[1]>0)||(a[2]>=5))}' || { echo "WirePlumber >= 0.5 required"; exit 1; }

echo "== user and directories"
id crewline >/dev/null 2>&1 || useradd --system --create-home --home-dir /home/crewline --shell /usr/sbin/nologin crewline
usermod -aG bluetooth,audio crewline
install -d -o crewline -g crewline -m 0750 "$STATE"
install -d -m 0755 "$CONF"
loginctl enable-linger crewline          # user services (and PipeWire) run without a login

echo "== application"
install -d "$PREFIX"
python3 -m venv "$PREFIX/venv"
if [ -n "$WHEELHOUSE" ]; then
  "$PREFIX/venv/bin/pip" install --no-index --find-links "$WHEELHOUSE" "$SRC" segno
else
  "$PREFIX/venv/bin/pip" install "$SRC" segno
fi

echo "== configuration"
install -D -m 0644 "$SRC/deploy/wireplumber/50-crewline.conf" /etc/wireplumber/wireplumber.conf.d/50-crewline.conf
install -D -m 0644 "$SRC/deploy/modprobe/crewline-btusb.conf" /etc/modprobe.d/crewline-btusb.conf
if ! grep -q "Crewline" /etc/bluetooth/main.conf; then
  cp -n /etc/bluetooth/main.conf /etc/bluetooth/main.conf.pre-crewline
  { echo; echo "# --- Crewline settings (see deploy/bluetooth/crewline-main.conf.snippet) ---"; } >> /etc/bluetooth/main.conf
  # Apply keys inside their existing sections where possible; otherwise append a block.
  python3 - "$SRC/deploy/bluetooth/crewline-main.conf.snippet" <<'PY'
import configparser, sys
want = configparser.ConfigParser(); want.optionxform = str; want.read(sys.argv[1])
cur = configparser.ConfigParser(strict=False, interpolation=None, allow_no_value=True); cur.optionxform = str
cur.read("/etc/bluetooth/main.conf")
for sec in want.sections():
    if not cur.has_section(sec): cur.add_section(sec)
    for k, v in want.items(sec): cur.set(sec, k, v)
with open("/etc/bluetooth/main.conf", "w") as f: cur.write(f)
PY
fi
[ -f "$CONF/web.toml" ] || cat > "$CONF/web.toml" <<'TOML'
# Crewline web settings
# Networks allowed to reach the web UI (default: private ranges + loopback).
# allowed_networks = ["192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12", "127.0.0.0/8"]
viewer_mode = "open"        # "open" = anyone on the LAN may view the dashboard; "pin" = need viewer_pin
# viewer_pin = "4821"
ack_requires_admin = false
TOML

echo "== services"
install -D -m 0644 "$SRC"/deploy/systemd/crewline-engine.service /etc/systemd/user/crewline-engine.service
install -D -m 0644 "$SRC"/deploy/systemd/crewline-web.service /etc/systemd/user/crewline-web.service
install -D -m 0644 "$SRC"/deploy/systemd/crewline-btsniff.service /etc/systemd/system/crewline-btsniff.service
systemctl --global enable pipewire.service wireplumber.service crewline-engine.service crewline-web.service || true
systemctl enable bluetooth.service
systemctl daemon-reload
systemctl restart bluetooth.service
uid=$(id -u crewline)
systemctl start "user@${uid}.service"
runuser -u crewline -- env XDG_RUNTIME_DIR="/run/user/${uid}" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${uid}/bus" systemctl --user daemon-reload
runuser -u crewline -- env XDG_RUNTIME_DIR="/run/user/${uid}" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${uid}/bus" systemctl --user restart pipewire.service wireplumber.service crewline-engine.service crewline-web.service || \
  echo "NOTE: user services did not start yet; reboot once and check 'journalctl' (see docs/06-operations.md)"

install -m 0755 "$SRC/deploy/crewline-backup.sh" /usr/local/sbin/crewline-backup
install -m 0755 "$SRC/deploy/crewline-restore.sh" /usr/local/sbin/crewline-restore
ln -sf "$PREFIX/venv/bin/crewline-probe" /usr/local/bin/crewline-probe
ln -sf "$PREFIX/venv/bin/crewline-web" /usr/local/bin/crewline-web

echo
echo "Installed. Open  http://$(hostname -I | awk '{print $1}'):8080/admin"
[ -f "$STATE/FIRST-RUN-ADMIN-PASSWORD.txt" ] && { echo "First-run admin password (delete the file after saving it):"; sed -n 2p "$STATE/FIRST-RUN-ADMIN-PASSWORD.txt"; }
echo "Then work through docs/04-validation-plan.md. Do not rely on this for a show before that."
