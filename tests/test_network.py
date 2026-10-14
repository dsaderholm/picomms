"""Network (hotspot) tests: parsers, nmcli command lines (stub), validation, API and show-mode lock."""
import json
import os
import stat
import sys

import pytest
from aiohttp.test_utils import TestClient, TestServer

from crewline.bluez import SimBluetooth
from crewline.engine import Engine
from crewline.engine_api import make_app
from crewline.model import ConfigError, ConfigLocked, default_config
from crewline.network import (
    AP_PROFILE, NetworkSettings, NmcliBackend, SimNetwork, new_passphrase, parse_default_route,
    parse_device_status, parse_kv, parse_wifi_list, split_terse, validate_network, wifi_qr_payload,
)
from crewline.sim import SimGraph


# ---- pure helpers --------------------------------------------------------------------------
def test_split_terse_handles_escaped_colons_and_backslashes():
    assert split_terse(r"My\:SSID:AA\:BB\:CC\:DD\:EE\:FF:36") == ["My:SSID", "AA:BB:CC:DD:EE:FF", "36"]
    assert split_terse(r"a\\b:c") == ["a\\b", "c"]
    assert split_terse("::") == ["", "", ""]


def test_parse_device_status_skips_loopback_and_classifies():
    text = "eth0:ethernet:connected:Wired connection 1\nwlan0:wifi:disconnected:\nlo:loopback:unmanaged:\np2p-dev-wlan0:wifi-p2p:disconnected:"
    d = parse_device_status(text)
    assert [(x["name"], x["kind"], x["state"]) for x in d] == [("eth0", "ethernet", "connected"), ("wlan0", "wifi", "disconnected")]


def test_parse_wifi_list_dedupes_by_strongest_and_labels_band():
    text = r"ICS-Staff:AA\:BB\:CC\:00\:00\:01:40:5200 MHz:64:WPA2" + "\n" + \
           r"ICS-Staff:AA\:BB\:CC\:00\:00\:02:36:5180 MHz:80:WPA2" + "\n" + \
           r"Guest:AA\:BB\:CC\:00\:00\:03:6:2437 MHz:55:--" + "\n" + ":x:1:2412 MHz:50:WPA2"
    nets = parse_wifi_list(text)
    assert [n["ssid"] for n in nets] == ["ICS-Staff", "Guest"]
    assert nets[0]["signal"] == 80 and nets[0]["band"] == "5ghz" and nets[0]["secured"]
    assert nets[1]["band"] == "2.4ghz" and not nets[1]["secured"]


def test_default_route_and_kv():
    assert parse_default_route("default via 192.168.1.1 dev eth0 proto dhcp metric 100") == "eth0"
    assert parse_default_route("") == ""
    kv = parse_kv("GENERAL.HWADDR:52\\:54\\:00\\:aa\\:bb\\:01\nIP4.ADDRESS[1]:10.42.0.1/24")
    assert kv["GENERAL.HWADDR"] == "52:54:00:aa:bb:01" or kv["GENERAL.HWADDR"].startswith("52")


def test_wifi_qr_payload_escapes_specials():
    assert wifi_qr_payload("Crew;line", 'pa:ss,"w\\d') == r'WIFI:T:WPA;S:Crew\;line;P:pa\:ss\,\"w\\d;;'


def test_passphrase_is_readable_and_long_enough():
    p = new_passphrase()
    assert len(p) >= 8 and p.count("-") == 3 and p.rsplit("-", 1)[1].isdigit()


def test_validation_rules():
    ok = NetworkSettings(ap_enabled=True, ap_ssid="Crewline-A1B2", ap_password="spot-truss-wing-4821")
    validate_network(ok)
    for bad in (
        NetworkSettings(ap_enabled=True, ap_ssid="", ap_password="12345678"),
        NetworkSettings(ap_enabled=True, ap_ssid="x" * 33, ap_password="12345678"),
        NetworkSettings(ap_enabled=True, ap_ssid="x", ap_password="short"),
        NetworkSettings(ap_band="5ghz", ap_channel=6),             # 2.4 GHz channel on 5 GHz
        NetworkSettings(ap_band="5ghz", ap_channel=52),            # DFS channel not allowed
        NetworkSettings(ap_band="6ghz"),
        NetworkSettings(ap_interface="wlan0; rm -rf /"),
    ):
        with pytest.raises(ConfigError):
            validate_network(bad)


def test_old_config_without_network_section_still_loads():
    from crewline.model import Config
    d = default_config().to_dict()
    d.pop("network")
    assert Config.from_dict(d).network.ap_band == "5ghz"


def test_show_mode_locks_network_settings(tmp_path):
    from crewline.store import ConfigStore
    s = ConfigStore(tmp_path / "c.json"); s.load()
    s.set_network({"ap_ssid": "Crewline-1", "ap_password": "spot-truss-wing-4821"})
    s.set_show_mode(True)
    with pytest.raises(ConfigLocked):
        s.set_network({"ap_channel": 40})


# ---- NmcliBackend against a stub nmcli ------------------------------------------------------
STUB = r'''#!{py}
import json, os, sys
log = open(os.environ["STUB_LOG"], "a"); log.write(json.dumps(sys.argv[1:]) + "\n"); log.close()
a = sys.argv[1:]
j = " ".join(a)
if a[:5] == ["-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev", "status"]:
    print("eth0:ethernet:connected:Wired connection 1\nwlan0:wifi:disconnected:\nwlan1:wifi:disconnected:\nlo:loopback:unmanaged:")
elif "dev show" in j:
    dev = a[-1]
    if dev == "eth0": print("GENERAL.HWADDR:52\\:54\\:00\\:00\\:00\\:01\nIP4.ADDRESS[1]:192.168.1.50/24")
    elif dev == "wlan0": print("GENERAL.HWADDR:52\\:54\\:00\\:00\\:00\\:02\nWIFI-PROPERTIES.AP:no\nWIFI-PROPERTIES.5GHZ:no\nWIFI-PROPERTIES.2GHZ:yes")
    else: print("GENERAL.HWADDR:52\\:54\\:00\\:00\\:00\\:03\nWIFI-PROPERTIES.AP:yes\nWIFI-PROPERTIES.5GHZ:yes\nWIFI-PROPERTIES.2GHZ:yes")
elif "connection show --active" in j:
    print("Wired connection 1:eth0")
elif a[:2] == ["connection", "up"]:
    if os.environ.get("STUB_FAIL_UP"): print("Error: Connection activation failed"); sys.exit(4)
elif "dev wifi list" in j:
    print("ICS-Staff:AA\\:BB\\:CC\\:00\\:00\\:01:40:5200 MHz:64:WPA2")
'''
ROUTE = '#!{py}\nprint("default via 192.168.1.1 dev eth0 proto dhcp")\n'
SUDO = '#!{py}\nimport json, os, sys\nopen(os.environ["STUB_LOG"], "a").write(json.dumps(["sudo"] + sys.argv[1:]) + "\\n")\n'


@pytest.fixture
def nm(tmp_path, monkeypatch):
    b = tmp_path / "bin"; b.mkdir()
    for name, body in (("nmcli", STUB), ("ip", ROUTE), ("sudo", SUDO)):
        f = b / name
        f.write_text(body.replace("{py}", sys.executable))
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.log"
    monkeypatch.setenv("PATH", f"{b}:{os.environ['PATH']}")
    monkeypatch.setenv("STUB_LOG", str(log))
    be = NmcliBackend(internet_probe=("127.0.0.1", 9))            # nothing listens: internet 'down'
    be.calls = lambda: [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
    return be


async def test_status_lists_interfaces_capabilities_and_uplink(nm):
    st = await nm.status()
    assert st["available"] and st["uplink_interface"] == "eth0"
    wl = {d["name"]: d for d in st["interfaces"] if d["kind"] == "wifi"}
    assert wl["wlan0"]["ap_capable"] is False and wl["wlan1"]["ap_capable"] and wl["wlan1"]["supports_5ghz"]
    eth = next(d for d in st["interfaces"] if d["name"] == "eth0")
    assert eth["ipv4"] == "192.168.1.50"
    assert st["internet"]["ok"] is False and st["ap"]["active"] is False


async def test_apply_ap_picks_a_capable_adapter_and_builds_the_5ghz_shared_profile(nm):
    n = NetworkSettings(ap_enabled=True, ap_ssid="Crewline-A1B2", ap_password="spot-truss-wing-4821", passthrough=False)
    msg = await nm.apply_ap(n)
    assert msg == "hotspot started"
    add = next(c for c in nm.calls() if c[:2] == ["connection", "add"])
    kv = dict(zip(add[2::2], add[3::2]))
    assert kv["ifname"] == "wlan1"                                   # the AP-capable one, not wlan0
    assert kv["802-11-wireless.mode"] == "ap" and kv["802-11-wireless.band"] == "a"
    assert kv["802-11-wireless.channel"] == "36" and kv["ipv4.method"] == "shared"
    assert kv["wifi-sec.key-mgmt"] == "wpa-psk" and kv["wifi-sec.proto"] == "rsn" and kv["wifi-sec.pairwise"] == "ccmp"
    assert ["connection", "up", AP_PROFILE] in nm.calls()
    assert ["sudo", "-n", "/usr/local/sbin/crewline-netctl", "passthrough", "off", "wlan1"] in nm.calls()


async def test_apply_ap_refuses_5ghz_on_a_radio_without_it_and_reports_failures(nm, monkeypatch):
    n = NetworkSettings(ap_enabled=True, ap_ssid="x", ap_password="12345678", ap_interface="wlan0")
    assert "cannot act as a hotspot" in await nm.apply_ap(n)
    n = NetworkSettings(ap_enabled=True, ap_ssid="x", ap_password="12345678", ap_interface="nope0")
    assert "no Wi-Fi adapter" in await nm.apply_ap(n)
    monkeypatch.setenv("STUB_FAIL_UP", "1")
    n = NetworkSettings(ap_enabled=True, ap_ssid="x", ap_password="12345678")
    assert "did not start" in await nm.apply_ap(n)


async def test_scan_join_forget_and_interface_name_injection_guard(nm):
    nets = await nm.scan("wlan0")
    assert nets[0]["ssid"] == "ICS-Staff" and nets[0]["band"] == "5ghz"
    assert await nm.scan("wlan0; reboot") == []
    assert await nm.join("wlan0", "ICS-Staff", "pw") == "connected"
    join = next(c for c in nm.calls() if c[:3] == ["dev", "wifi", "connect"])
    assert join[3] == "ICS-Staff" and "password" in join and "crewline-uplink-ICS-Staff" in join
    assert await nm.join("wlan0; x", "a", "b") == "invalid interface"
    assert "only uplink" in await nm.forget("Wired connection 1")
    assert await nm.forget("crewline-uplink-ICS-Staff") == "removed"
    assert "no hotspot interface" == await nm.set_passthrough(False, "wlan1; rm")


async def test_missing_nmcli_reports_unavailable(monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    st = await NmcliBackend().status()
    assert st["available"] is False and "not installed" in st["reason"]


# ---- engine + API (simulation) ------------------------------------------------------------------
@pytest.fixture
async def site(tmp_path):
    g = SimGraph()
    net = SimNetwork()
    eng = Engine(tmp_path, g, SimBluetooth(g), simulated=True, net=net)
    await eng.start()
    await eng.refresh_network()
    async with TestClient(TestServer(make_app(eng))) as c:
        yield c, eng, net


async def test_api_round_trip_start_hotspot_toggle_passthrough_and_stop(site):
    c, eng, net = site
    sug = await (await c.post("/network/suggest", json={})).json()
    r = await c.post("/network/settings", json={"ap_ssid": sug["ssid"], "ap_password": sug["password"], "ap_enabled": True})
    assert r.status == 200
    r = await c.post("/network/ap/start", json={})
    assert (await r.json())["ok"] and net.ap_active
    info = await (await c.get("/network")).json()
    assert info["status"]["ap"]["active"] and info["wifi_qr"].startswith("WIFI:T:WPA;S:Crewline-")
    r = await c.post("/network/passthrough", json={"on": False})
    assert (await r.json())["ok"] and net.passthrough is False and eng.store.config.network.passthrough is False
    r = await c.post("/network/ap/stop", json={})
    assert (await r.json())["ok"] and not net.ap_active


async def test_network_changes_are_locked_in_show_mode_but_status_is_readable(site):
    c, eng, net = site
    await c.post("/network/settings", json={"ap_ssid": "Crewline-1", "ap_password": "spot-truss-wing-4821"})
    eng.store.set_show_mode(True)
    for path, body in (("/network/settings", {"ap_channel": 40}), ("/network/ap/start", {}), ("/network/ap/stop", {}),
                       ("/network/join", {"iface": "wlan0", "ssid": "x"}), ("/network/passthrough", {"on": False}),
                       ("/network/forget", {"name": "crewline-uplink-x"})):
        assert (await c.post(path, json=body)).status == 423, path
    assert (await c.get("/network")).status == 200
    assert not net.ap_active and net.calls == []


async def test_start_requires_credentials_and_bad_values_are_rejected(site):
    c, eng, net = site
    r = await c.post("/network/ap/start", json={})
    assert r.status == 400
    r = await c.post("/network/settings", json={"ap_band": "5ghz", "ap_channel": 6})
    assert r.status == 400


async def test_public_state_never_contains_the_hotspot_password(site):
    c, eng, net = site
    await c.post("/network/settings", json={"ap_ssid": "Crewline-1", "ap_password": "spot-truss-wing-4821"})
    await c.post("/network/ap/start", json={})
    await eng.refresh_network()
    st = eng.snapshot_state()
    assert st["network"]["ap_active"] and st["network"]["ap_ssid"] == "Crewline-1"
    assert "spot-truss" not in json.dumps(st)


async def test_passthrough_rule_is_reapplied_after_reboot(tmp_path):
    """The nftables 'no internet' rule is lost on reboot; the engine restores it when the hotspot is back."""
    g = SimGraph(); net = SimNetwork()
    from crewline.store import ConfigStore
    s = ConfigStore(tmp_path / "config.json"); s.load()
    s.set_network({"ap_ssid": "Crewline-1", "ap_password": "spot-truss-wing-4821", "ap_enabled": True, "passthrough": False})
    net.ap_active = True                                    # NM autoconnected the hotspot at boot
    eng = Engine(tmp_path, g, SimBluetooth(g), simulated=True, net=net)
    await eng.start()
    import asyncio
    for _ in range(100):
        if "passthrough False" in net.calls:
            break
        await asyncio.sleep(0.05)
    assert "passthrough False" in net.calls
    await eng.stop()
