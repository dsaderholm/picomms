"""Wi-Fi hotspot ("its own network") with optional internet passthrough.

Built on NetworkManager (``nmcli``): an access-point profile with
``ipv4.method shared`` makes NetworkManager run DHCP/DNS and NAT the hotspot's clients
out through whatever the default route is (Ethernet, or a Wi-Fi client connection on a
second radio). Nothing in the *audio* path depends on any of this.

Design rules that come from the priorities (range first):
* The hotspot defaults to **5 GHz**. Bluetooth shares 2.4 GHz; a 2.4 GHz access point next
  to Bluetooth adapters costs range and causes dropouts.
* Changing the network drops everyone's phones, so every change is **locked in show mode**.
* The engine never touches the network by itself; it acts only on an administrator's request.

UNVERIFIED on real hardware (validation test T13). ``nmcli`` behaviours used here are from
NetworkManager's documented properties; the parsers are unit-tested against recorded-format
samples and the command lines against a stub ``nmcli``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
import shutil
import time
from dataclasses import dataclass, field
from typing import Protocol

log = logging.getLogger("crewline.net")

AP_PROFILE = "crewline-ap"
UPLINK_PREFIX = "crewline-uplink-"
AP_ADDRESS = "10.42.0.1/24"
IFACE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,15}$")
NETCTL = "/usr/local/sbin/crewline-netctl"

# Channels that need no radar detection (DFS) in most regulatory domains. The mt76 drivers
# used by the recommended Wi-Fi adapter do not support AP mode on DFS channels.
CHANNELS_5GHZ = (36, 40, 44, 48, 149, 153, 157, 161, 165)
CHANNELS_24GHZ = (1, 6, 11)

_WORDS = ("amber", "anchor", "arrow", "badge", "beacon", "blue", "boom", "cable", "cue", "curtain", "dimmer",
          "flat", "gel", "ghost", "grid", "house", "lamp", "light", "mic", "patch", "pipe", "prop", "rail",
          "ramp", "scrim", "spot", "stage", "strobe", "tech", "truss", "wing", "wire")


@dataclass
class NetworkSettings:
    """Desired hotspot configuration (stored in the main config)."""
    ap_enabled: bool = False
    ap_ssid: str = ""
    ap_password: str = ""
    ap_band: str = "5ghz"            # "5ghz" (default) | "2.4ghz"
    ap_channel: int = 36
    ap_interface: str = ""           # e.g. "wlan1"; empty = choose automatically
    passthrough: bool = True         # let hotspot clients reach the internet


def validate_network(n: NetworkSettings) -> None:
    from .model import ConfigError
    if n.ap_band not in ("5ghz", "2.4ghz"):
        raise ConfigError("hotspot band must be 5ghz or 2.4ghz")
    ok = CHANNELS_5GHZ if n.ap_band == "5ghz" else CHANNELS_24GHZ
    if n.ap_channel not in ok:
        raise ConfigError(f"channel {n.ap_channel} is not allowed on {n.ap_band}; use one of {list(ok)}")
    if n.ap_interface and not IFACE_RE.match(n.ap_interface):
        raise ConfigError("invalid network interface name")
    if n.ap_enabled:
        if not (1 <= len(n.ap_ssid.encode()) <= 32):
            raise ConfigError("hotspot name must be 1-32 characters")
        if not (8 <= len(n.ap_password) <= 63):
            raise ConfigError("hotspot password must be 8-63 characters")


def new_passphrase() -> str:
    """A readable password such as ``spot-truss-wing-4821`` (typeable on a phone)."""
    w = [secrets.choice(_WORDS) for _ in range(3)]
    return "-".join(w) + "-" + str(secrets.randbelow(9000) + 1000)


def default_ssid() -> str:
    return "Crewline-" + secrets.token_hex(2).upper()


SPECIALS = "\\;,:\""


def wifi_qr_payload(ssid: str, password: str) -> str:
    """The standard string phones scan to join a WPA network."""
    esc = lambda s: "".join("\\" + c if c in SPECIALS else c for c in s)  # noqa: E731
    return f"WIFI:T:WPA;S:{esc(ssid)};P:{esc(password)};;"


# --------------------------------------------------------------------------- terse nmcli parsing
def split_terse(line: str) -> list[str]:
    """Split a ``nmcli -t`` line on unescaped colons and unescape ``\\:`` and ``\\\\``."""
    out, cur, i = [], [], 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            cur.append(line[i + 1])
            i += 2
            continue
        if c == ":":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    out.append("".join(cur))
    return out


def parse_device_status(text: str) -> list[dict]:
    devs = []
    for line in text.splitlines():
        f = split_terse(line)
        if len(f) < 4 or f[1] in ("loopback", "bridge", "tun", "veth", "wifi-p2p"):
            continue
        kind = {"ethernet": "ethernet", "wifi": "wifi"}.get(f[1], "other")
        devs.append({"name": f[0], "kind": kind, "state": f[2], "connection": f[3]})
    return devs


def parse_kv(text: str) -> dict[str, str]:
    d: dict[str, str] = {}
    for line in text.splitlines():
        k, _, v = line.partition(":")
        d[k] = v.replace("\\:", ":")
    return d


def parse_wifi_list(text: str) -> list[dict]:
    """``nmcli -t -f SSID,BSSID,CHAN,FREQ,SIGNAL,SECURITY dev wifi list`` -> list of networks."""
    nets: dict[str, dict] = {}
    for line in text.splitlines():
        f = split_terse(line)
        if len(f) < 6 or not f[0]:
            continue
        ssid, bssid, chan, freq, sig, sec = f[:6]
        freq_mhz = int(re.sub(r"\D", "", freq) or 0)
        n = {"ssid": ssid, "channel": int(chan or 0), "freq_mhz": freq_mhz,
             "band": "5ghz" if freq_mhz >= 4900 else "2.4ghz", "signal": int(sig or 0),
             "secured": bool(sec and sec != "--")}
        if ssid not in nets or n["signal"] > nets[ssid]["signal"]:
            nets[ssid] = n
    return sorted(nets.values(), key=lambda n: -n["signal"])


def parse_default_route(text: str) -> str:
    m = re.search(r"default via \S+ dev (\S+)", text)
    return m.group(1) if m else ""


def parse_iw_info(text: str) -> dict:
    out = {}
    m = re.search(r"channel (\d+) \((\d+) MHz\)", text)
    if m:
        out["channel"], out["freq_mhz"] = int(m.group(1)), int(m.group(2))
    return out


# --------------------------------------------------------------------------- backends
class NetworkBackend(Protocol):
    available: bool
    async def status(self) -> dict: ...
    async def apply_ap(self, n: NetworkSettings) -> str: ...
    async def stop_ap(self) -> str: ...
    async def scan(self, iface: str) -> list[dict]: ...
    async def join(self, iface: str, ssid: str, password: str) -> str: ...
    async def forget(self, name: str) -> str: ...
    async def set_passthrough(self, on: bool, iface: str) -> str: ...


class NmcliBackend:
    def __init__(self, internet_probe: tuple[str, int] = ("1.1.1.1", 443)) -> None:
        self.available = shutil.which("nmcli") is not None
        self.probe = internet_probe

    async def _run(self, *argv: str, timeout: float = 20.0) -> tuple[int, str]:
        env = {**os.environ, "LC_ALL": "C"}
        env["PATH"] = env.get("PATH", "") + ":/usr/sbin:/sbin"
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=env)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout)
            return proc.returncode or 0, out.decode(errors="replace")
        except asyncio.TimeoutError:
            return 124, "timed out"
        except FileNotFoundError:
            return 127, f"{argv[0]} not installed"

    async def status(self) -> dict:
        if not self.available:
            return {"available": False, "reason": "NetworkManager (nmcli) is not installed"}
        rc, out = await self._run("nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev", "status")
        if rc:
            return {"available": False, "reason": out.strip()[:200]}
        ifaces = parse_device_status(out)
        for d in ifaces:
            rc, det = await self._run("nmcli", "-t", "-f",
                                      "GENERAL.HWADDR,IP4.ADDRESS,WIFI-PROPERTIES.AP,WIFI-PROPERTIES.5GHZ,"
                                      "WIFI-PROPERTIES.2GHZ", "dev", "show", d["name"])
            kv = parse_kv(det) if rc == 0 else {}
            d["mac"] = kv.get("GENERAL.HWADDR", "")
            d["ipv4"] = next((v.split("/")[0] for k, v in kv.items() if k.startswith("IP4.ADDRESS")), "")
            if d["kind"] == "wifi":
                d["ap_capable"] = kv.get("WIFI-PROPERTIES.AP") == "yes"
                d["supports_5ghz"] = kv.get("WIFI-PROPERTIES.5GHZ") == "yes"
                rc2, iw = await self._run("iw", "dev", d["name"], "info")
                info = parse_iw_info(iw) if rc2 == 0 else {}
                d.update({"channel": info.get("channel"), "freq_mhz": info.get("freq_mhz")})
        rc, route = await self._run("ip", "route", "show", "default")
        uplink = parse_default_route(route) if rc == 0 else ""
        rc, active = await self._run("nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active")
        act = [split_terse(l) for l in active.splitlines()] if rc == 0 else []
        ap_dev = next((a[1] for a in act if a[0] == AP_PROFILE), "")
        ap = {"active": bool(ap_dev), "interface": ap_dev, "clients": None}
        if ap_dev:
            rc, st = await self._run("iw", "dev", ap_dev, "station", "dump")
            if rc == 0:
                ap["clients"] = st.count("Station ")
        rc, prof = await self._run("nmcli", "-t", "-f", "connection.autoconnect,802-11-wireless.ssid",
                                   "connection", "show", AP_PROFILE)
        ap["profile_exists"] = rc == 0
        internet = await self._check_internet()
        return {"available": True, "interfaces": ifaces, "uplink_interface": uplink, "ap": ap,
                "internet": internet, "checked": time.time()}

    async def _check_internet(self) -> dict:
        host, port = self.probe
        t0 = time.monotonic()
        try:
            r, w = await asyncio.wait_for(asyncio.open_connection(host, port), 2.0)
            w.close()
            return {"ok": True, "ms": int((time.monotonic() - t0) * 1000)}
        except Exception:
            return {"ok": False, "ms": None}

    async def apply_ap(self, n: NetworkSettings) -> str:
        st = await self.status()
        if not st.get("available"):
            return "network control is not available: " + st.get("reason", "")
        wifi = [d for d in st["interfaces"] if d["kind"] == "wifi"]
        iface = n.ap_interface or next((d["name"] for d in wifi if d.get("ap_capable")), "")
        dev = next((d for d in wifi if d["name"] == iface), None)
        if not dev:
            return "no Wi-Fi adapter found for the hotspot"
        if not dev.get("ap_capable"):
            return f"{iface} cannot act as a hotspot (no access-point mode)"
        if n.ap_band == "5ghz" and not dev.get("supports_5ghz"):
            return f"{iface} does not support 5 GHz; choose 2.4 GHz (reduces Bluetooth range) or another adapter"
        band = "a" if n.ap_band == "5ghz" else "bg"
        await self._run("nmcli", "connection", "delete", AP_PROFILE)
        rc, out = await self._run(
            "nmcli", "connection", "add", "type", "wifi", "ifname", iface, "con-name", AP_PROFILE,
            "autoconnect", "yes", "ssid", n.ap_ssid,
            "802-11-wireless.mode", "ap", "802-11-wireless.band", band, "802-11-wireless.channel", str(n.ap_channel),
            "ipv4.method", "shared", "ipv4.addresses", AP_ADDRESS, "ipv6.method", "disabled",
            "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", n.ap_password,
            "wifi-sec.proto", "rsn", "wifi-sec.pairwise", "ccmp", "wifi-sec.group", "ccmp")
        if rc:
            return "could not create the hotspot: " + out.strip()[:200]
        rc, out = await self._run("nmcli", "connection", "up", AP_PROFILE, timeout=45)
        if rc:
            return "hotspot created but did not start: " + out.strip()[:200]
        await self.set_passthrough(n.passthrough, iface)
        return "hotspot started"

    async def stop_ap(self) -> str:
        await self._run("nmcli", "connection", "modify", AP_PROFILE, "connection.autoconnect", "no")
        rc, out = await self._run("nmcli", "connection", "down", AP_PROFILE)
        return "hotspot stopped" if rc == 0 else out.strip()[:200]

    async def scan(self, iface: str) -> list[dict]:
        if not IFACE_RE.match(iface):
            return []
        rc, out = await self._run("nmcli", "-t", "-f", "SSID,BSSID,CHAN,FREQ,SIGNAL,SECURITY",
                                  "dev", "wifi", "list", "ifname", iface, "--rescan", "yes", timeout=30)
        return parse_wifi_list(out) if rc == 0 else []

    async def join(self, iface: str, ssid: str, password: str) -> str:
        if not IFACE_RE.match(iface):
            return "invalid interface"
        args = ["nmcli", "dev", "wifi", "connect", ssid, "ifname", iface, "name", UPLINK_PREFIX + ssid[:24]]
        if password:
            args += ["password", password]
        rc, out = await self._run(*args, timeout=45)
        return "connected" if rc == 0 else "could not connect: " + out.strip()[:200]

    async def forget(self, name: str) -> str:
        if not name.startswith(UPLINK_PREFIX):
            return "only uplink connections created here can be removed"
        rc, out = await self._run("nmcli", "connection", "delete", name)
        return "removed" if rc == 0 else out.strip()[:200]

    async def set_passthrough(self, on: bool, iface: str) -> str:
        if not IFACE_RE.match(iface or ""):
            return "no hotspot interface"
        rc, out = await self._run("sudo", "-n", NETCTL, "passthrough", "on" if on else "off", iface)
        return "ok" if rc == 0 else "could not change passthrough: " + out.strip()[:200]


class SimNetwork:
    """In-memory network for the simulation and tests."""

    available = True

    def __init__(self) -> None:
        self.ap_active = False
        self.last_ap: NetworkSettings | None = None
        self.passthrough = True
        self.uplink = "eth0"
        self.joined: str | None = None
        self.calls: list[str] = []

    async def status(self) -> dict:
        ifaces = [
            {"name": "eth0", "kind": "ethernet", "state": "connected", "connection": "Wired connection 1",
             "mac": "52:54:00:aa:bb:01", "ipv4": "192.168.1.50"},
            {"name": "wlan0", "kind": "wifi", "state": "connected" if self.joined else "disconnected",
             "connection": self.joined or "", "mac": "52:54:00:aa:bb:02", "ipv4": "192.168.8.20" if self.joined else "",
             "ap_capable": False, "supports_5ghz": False, "channel": None, "freq_mhz": None},
            {"name": "wlan1", "kind": "wifi", "state": "connected" if self.ap_active else "disconnected",
             "connection": AP_PROFILE if self.ap_active else "", "mac": "52:54:00:aa:bb:03",
             "ipv4": "10.42.0.1" if self.ap_active else "", "ap_capable": True, "supports_5ghz": True,
             "channel": 36 if self.ap_active else None, "freq_mhz": 5180 if self.ap_active else None},
        ]
        return {"available": True, "interfaces": ifaces, "uplink_interface": self.uplink,
                "ap": {"active": self.ap_active, "interface": "wlan1" if self.ap_active else "",
                       "clients": 3 if self.ap_active else None, "profile_exists": self.last_ap is not None},
                "internet": {"ok": True, "ms": 24}, "checked": time.time(), "simulated": True}

    async def apply_ap(self, n: NetworkSettings) -> str:
        self.calls.append("apply_ap")
        self.ap_active, self.last_ap, self.passthrough = True, n, n.passthrough
        return "hotspot started"

    async def stop_ap(self) -> str:
        self.calls.append("stop_ap")
        self.ap_active = False
        return "hotspot stopped"

    async def scan(self, iface: str) -> list[dict]:
        return [{"ssid": "ICS-Guest", "channel": 6, "freq_mhz": 2437, "band": "2.4ghz", "signal": 71, "secured": True},
                {"ssid": "ICS-Staff", "channel": 40, "freq_mhz": 5200, "band": "5ghz", "signal": 64, "secured": True}]

    async def join(self, iface: str, ssid: str, password: str) -> str:
        self.calls.append(f"join {ssid}")
        self.joined = ssid
        return "connected"

    async def forget(self, name: str) -> str:
        self.joined = None
        return "removed"

    async def set_passthrough(self, on: bool, iface: str) -> str:
        self.calls.append(f"passthrough {on}")
        self.passthrough = on
        return "ok"
