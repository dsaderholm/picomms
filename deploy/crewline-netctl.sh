#!/usr/bin/env bash
# Tiny root helper: turns internet passthrough for the Crewline hotspot on or off.
# Called only through sudo by the engine (see deploy/sudoers.d/crewline). It validates every
# argument itself and touches nothing except its own nftables table.
set -euo pipefail
[ $# -eq 3 ] && [ "$1" = "passthrough" ] || { echo "usage: crewline-netctl passthrough on|off IFACE" >&2; exit 2; }
state="$2"; iface="$3"
[[ "$state" =~ ^(on|off)$ ]] || { echo "bad state" >&2; exit 2; }
[[ "$iface" =~ ^[A-Za-z0-9_.-]{1,15}$ ]] || { echo "bad interface" >&2; exit 2; }
nft delete table inet crewline_guard 2>/dev/null || true
if [ "$state" = "off" ]; then
  nft -f - <<NFT
table inet crewline_guard {
  chain forward {
    type filter hook forward priority -10; policy accept;
    iifname "$iface" oifname != "$iface" drop comment "crewline: hotspot clients have no internet"
  }
}
NFT
fi
echo ok
