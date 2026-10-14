#!/usr/bin/env bash
# Full backup: Crewline settings + Bluetooth pairing keys + site config.
# Pairing keys are tied to each adapter's address: restoring them only helps on
# a machine using the SAME adapters (same physical dongles).
set -euo pipefail
OUT="${1:-/root/crewline-backup-$(hostname)-$(date +%Y%m%d-%H%M).tar.gz}"
tar -czf "$OUT" --warnings=no-file-changed \
  /var/lib/crewline/config.json /var/lib/crewline/backups /var/lib/crewline/web-auth.json \
  /var/lib/bluetooth /etc/crewline /etc/bluetooth/main.conf \
  /etc/wireplumber/wireplumber.conf.d/50-crewline.conf 2>/dev/null || true
chmod 600 "$OUT"
echo "wrote $OUT  (contains Bluetooth keys and the admin credential file: store it safely)"
