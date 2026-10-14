#!/usr/bin/env bash
# Restore a crewline-backup tarball onto this machine (same adapters assumed for pairings).
set -euo pipefail
[ $# -eq 1 ] || { echo "usage: crewline-restore BACKUP.tar.gz"; exit 1; }
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
uid=$(id -u crewline)
runuser -u crewline -- env XDG_RUNTIME_DIR="/run/user/${uid}" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${uid}/bus" systemctl --user stop crewline-engine crewline-web || true
systemctl stop bluetooth
tar -xzf "$1" -C /
chown -R crewline:crewline /var/lib/crewline
systemctl start bluetooth
runuser -u crewline -- env XDG_RUNTIME_DIR="/run/user/${uid}" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${uid}/bus" systemctl --user start crewline-engine crewline-web
echo "restored. Headsets may need to be power-cycled once."
