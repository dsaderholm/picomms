"""Bluetooth device management through BlueZ's D-Bus API (and a simulated twin).

Responsibilities (and nothing else): adapters, discovery, a *limited* pairing
window, pair / connect / disconnect / forget, reconnect of known devices, and
reading what BlueZ reliably reports (Connected, Paired, RSSI, Battery1).

Audio is not handled here. When a headset connects with HFP, PipeWire creates
its microphone/earpiece nodes; ``pwgraph`` observes those. "Connected" in this
module therefore never implies "audio works" -- the engine reports those as
separate facts.

UNVERIFIED on hardware: everything touching live BlueZ. ``parse_managed_objects``
is unit-tested against synthetic D-Bus data shaped like BlueZ's documented
objects; the D-Bus calls follow the BlueZ API docs (adapter-api, device-api,
agent-api, battery-api).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

log = logging.getLogger("crewline.bt")

HFP_HF_UUID = "0000111e-0000-1000-8000-00805f9b34fb"   # Handsfree (the headset)
HSP_HS_UUID = "00001108-0000-1000-8000-00805f9b34fb"   # Headset
A2DP_SINK_UUID = "0000110b-0000-1000-8000-00805f9b34fb"
AVRCP_CT_UUID = "0000110e-0000-1000-8000-00805f9b34fb"


@dataclass
class BtAdapter:
    address: str
    path: str
    name: str = ""
    powered: bool = False
    discovering: bool = False
    discoverable: bool = False
    pairable: bool = False
    # How many HFP devices are connected through this adapter right now.
    hfp_connected: int = 0


@dataclass
class BtDevice:
    address: str
    path: str
    adapter: str                      # adapter address
    name: str = ""
    alias: str = ""
    paired: bool = False
    trusted: bool = False
    connected: bool = False
    rssi: int | None = None
    icon: str = ""
    uuids: list[str] = field(default_factory=list)
    battery: int | None = None         # None == unknown (never invented)

    @property
    def supports_hfp(self) -> bool:
        return HFP_HF_UUID in self.uuids or HSP_HS_UUID in self.uuids

    @property
    def is_audio_like(self) -> bool:
        return self.supports_hfp or self.icon.startswith("audio") or self.icon.startswith("phone")


def _v(d: dict[str, Any], key: str, default: Any = None) -> Any:
    x = d.get(key)
    if x is None:
        return default
    return getattr(x, "value", x)       # dbus_fast Variant or plain value


def parse_managed_objects(objs: dict[str, dict[str, dict[str, Any]]]) -> tuple[list[BtAdapter], list[BtDevice]]:
    """Convert ObjectManager.GetManagedObjects() output into adapters/devices."""
    adapters: dict[str, BtAdapter] = {}
    for path, ifaces in objs.items():
        a = ifaces.get("org.bluez.Adapter1")
        if a:
            adapters[path] = BtAdapter(
                address=str(_v(a, "Address", "")).upper(), path=path,
                name=str(_v(a, "Alias", _v(a, "Name", ""))),
                powered=bool(_v(a, "Powered", False)),
                discovering=bool(_v(a, "Discovering", False)),
                discoverable=bool(_v(a, "Discoverable", False)),
                pairable=bool(_v(a, "Pairable", False)),
            )
    devices: list[BtDevice] = []
    for path, ifaces in objs.items():
        d = ifaces.get("org.bluez.Device1")
        if not d:
            continue
        ad = adapters.get(str(_v(d, "Adapter", "")))
        batt = ifaces.get("org.bluez.Battery1")
        rssi = _v(d, "RSSI")
        dev = BtDevice(
            address=str(_v(d, "Address", "")).upper(), path=path,
            adapter=ad.address if ad else "",
            name=str(_v(d, "Name", "")), alias=str(_v(d, "Alias", "")),
            paired=bool(_v(d, "Paired", False)), trusted=bool(_v(d, "Trusted", False)),
            connected=bool(_v(d, "Connected", False)),
            rssi=int(rssi) if rssi is not None else None,
            icon=str(_v(d, "Icon", "")),
            uuids=[str(u).lower() for u in (_v(d, "UUIDs", []) or [])],
            battery=int(_v(batt, "Percentage")) if batt and _v(batt, "Percentage") is not None else None,
        )
        devices.append(dev)
        if ad and dev.connected and dev.supports_hfp:
            ad.hfp_connected += 1
    return list(adapters.values()), devices


class BtManager(Protocol):
    async def start(self) -> None: ...
    async def refresh(self) -> tuple[list[BtAdapter], list[BtDevice]]: ...
    async def open_pairing(self, adapter: str | None, seconds: int) -> None: ...
    async def close_pairing(self) -> None: ...
    @property
    def pairing_open_until(self) -> float: ...
    async def pair(self, address: str) -> str: ...
    async def connect(self, address: str) -> str: ...
    async def disconnect(self, address: str) -> str: ...
    async def forget(self, address: str) -> str: ...
    async def trust(self, address: str, on: bool = True) -> None: ...


class BluezDbus:
    """Real BlueZ manager. Requires ``dbus-fast`` and a running ``bluetoothd``."""

    AGENT_PATH = "/org/crewline/agent"

    def __init__(self, known_addresses: Callable[[], set[str]]) -> None:
        self._bus = None
        self._known = known_addresses
        self._pairing_until = 0.0
        self._pairing_task: asyncio.Task | None = None
        self._pair_adapter: str | None = None

    @property
    def pairing_open_until(self) -> float:
        return self._pairing_until

    def _window_open(self) -> bool:
        return time.monotonic() < self._pairing_until

    async def start(self) -> None:
        from dbus_fast import BusType
        from dbus_fast.aio import MessageBus
        self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        await self._register_agent()

    async def _iface(self, path: str, iface: str):
        intro = await self._bus.introspect("org.bluez", path)
        return self._bus.get_proxy_object("org.bluez", path, intro).get_interface(iface)

    async def _register_agent(self) -> None:
        from dbus_fast import DBusError
        from dbus_fast.service import ServiceInterface, method

        outer = self

        class Agent(ServiceInterface):
            """Auto-accepting agent -- but ONLY while the pairing window is open
            (or for devices already in our configuration)."""

            def __init__(self) -> None:
                super().__init__("org.bluez.Agent1")

            def _allow(self, device: str) -> None:
                addr = device.rsplit("dev_", 1)[-1].replace("_", ":").upper()
                if not (outer._window_open() or addr in outer._known()):
                    raise DBusError("org.bluez.Error.Rejected", "pairing window is closed")

            @method()
            def Release(self):
                pass

            @method()
            def RequestPinCode(self, device: "o") -> "s":  # noqa: F821
                self._allow(device)
                return "0000"             # legacy PIN used by most headsets

            @method()
            def DisplayPinCode(self, device: "o", pincode: "s"):  # noqa: F821
                pass

            @method()
            def RequestPasskey(self, device: "o") -> "u":  # noqa: F821
                self._allow(device)
                return 0

            @method()
            def DisplayPasskey(self, device: "o", passkey: "u", entered: "q"):  # noqa: F821
                pass

            @method()
            def RequestConfirmation(self, device: "o", passkey: "u"):  # noqa: F821
                self._allow(device)

            @method()
            def RequestAuthorization(self, device: "o"):  # noqa: F821
                self._allow(device)

            @method()
            def AuthorizeService(self, device: "o", uuid: "s"):  # noqa: F821
                self._allow(device)

            @method()
            def Cancel(self):
                pass

        self._bus.export(self.AGENT_PATH, Agent())
        mgr = await self._iface("/org/bluez", "org.bluez.AgentManager1")
        await mgr.call_register_agent(self.AGENT_PATH, "NoInputNoOutput")
        await mgr.call_request_default_agent(self.AGENT_PATH)

    async def refresh(self) -> tuple[list[BtAdapter], list[BtDevice]]:
        om = await self._iface("/", "org.freedesktop.DBus.ObjectManager")
        return parse_managed_objects(await om.call_get_managed_objects())

    async def _adapter_paths(self) -> dict[str, str]:
        adapters, _ = await self.refresh()
        return {a.address: a.path for a in adapters}

    async def open_pairing(self, adapter: str | None, seconds: int) -> None:
        """Open a time-limited pairing window on one adapter (or all if None)."""
        seconds = max(10, min(int(seconds), 300))
        paths = await self._adapter_paths()
        targets = {a: p for a, p in paths.items() if adapter in (None, a)}
        if not targets:
            raise RuntimeError("no such Bluetooth adapter")
        self._pair_adapter = adapter
        self._pairing_until = time.monotonic() + seconds
        for addr, path in targets.items():
            ad = await self._iface(path, "org.bluez.Adapter1")
            await ad.set_powered(True)
            await ad.set_pairable(True)
            await ad.set_pairable_timeout(seconds)
            await ad.set_discoverable(True)
            await ad.set_discoverable_timeout(seconds)
            try:
                from dbus_fast import Variant
                await ad.call_set_discovery_filter({"Transport": Variant("s", "bredr")})
            except Exception:       # filter is best-effort
                pass
            await ad.call_start_discovery()
        if self._pairing_task:
            self._pairing_task.cancel()
        self._pairing_task = asyncio.create_task(self._expire(seconds))

    async def _expire(self, seconds: int) -> None:
        await asyncio.sleep(seconds)
        await self.close_pairing()

    async def close_pairing(self) -> None:
        self._pairing_until = 0.0
        for addr, path in (await self._adapter_paths()).items():
            ad = await self._iface(path, "org.bluez.Adapter1")
            for fn in (ad.set_discoverable, ad.set_pairable):
                try:
                    await fn(False)
                except Exception:
                    pass
            try:
                await ad.call_stop_discovery()
            except Exception:
                pass          # not discovering

    async def _device_path(self, address: str) -> str:
        _, devices = await self.refresh()
        for d in devices:
            if d.address == address.upper():
                return d.path
        raise RuntimeError(f"device {address} is not known to BlueZ (not discovered yet?)")

    async def pair(self, address: str) -> str:
        if not self._window_open():
            return "pairing window is closed; open it first"
        path = await self._device_path(address)
        dev = await self._iface(path, "org.bluez.Device1")
        try:
            await asyncio.wait_for(dev.call_pair(), 30)
        except Exception as exc:
            if "AlreadyExists" not in str(exc):
                return f"pairing failed: {exc}"
        await dev.set_trusted(True)
        try:
            await asyncio.wait_for(dev.call_connect(), 20)
        except Exception as exc:
            return f"paired, but connecting failed: {exc}"
        return "paired and connected"

    async def connect(self, address: str) -> str:
        dev = await self._iface(await self._device_path(address), "org.bluez.Device1")
        try:
            await asyncio.wait_for(dev.call_connect(), 20)
            return "connected"
        except Exception as exc:
            return f"connect failed: {exc}"

    async def disconnect(self, address: str) -> str:
        dev = await self._iface(await self._device_path(address), "org.bluez.Device1")
        try:
            await dev.call_disconnect()
            return "disconnected"
        except Exception as exc:
            return f"disconnect failed: {exc}"

    async def forget(self, address: str) -> str:
        adapters, devices = await self.refresh()
        for d in devices:
            if d.address == address.upper():
                ad = await self._iface(d.adapter and next(a.path for a in adapters if a.address == d.adapter), "org.bluez.Adapter1")
                await ad.call_remove_device(d.path)
                return "forgotten"
        return "unknown device"

    async def trust(self, address: str, on: bool = True) -> None:
        dev = await self._iface(await self._device_path(address), "org.bluez.Device1")
        await dev.set_trusted(on)


class SimBluetooth:
    """Simulated manager used with SimGraph (tests and demo mode)."""

    def __init__(self, graph) -> None:
        self.graph = graph
        self._until = 0.0
        self.discovered: dict[str, str] = {}      # address -> name (not yet paired)
        self.adapters = [BtAdapter("00:00:00:00:00:01", "/sim/hci0", "sim-adapter-1", True),
                         BtAdapter("00:00:00:00:00:02", "/sim/hci1", "sim-adapter-2", True)]

    @property
    def pairing_open_until(self) -> float:
        return self._until

    async def start(self) -> None:
        return None

    async def refresh(self):
        devs = []
        counts = {a.address: 0 for a in self.adapters}
        for addr, d in self.graph.devices.items():
            devs.append(BtDevice(addr, f"/sim/{addr}", d.adapter, d.name, d.name, d.paired,
                                 True, d.connected, d.rssi, "audio-headset",
                                 [HFP_HF_UUID, A2DP_SINK_UUID], d.battery))
            if d.connected:
                counts[d.adapter] = counts.get(d.adapter, 0) + 1
        if time.monotonic() < self._until:
            for addr, name in self.discovered.items():
                if addr not in self.graph.devices:
                    devs.append(BtDevice(addr, f"/sim/{addr}", self.adapters[0].address, name, name,
                                         False, False, False, -60, "audio-headset", [HFP_HF_UUID]))
        for a in self.adapters:
            a.hfp_connected = counts.get(a.address, 0)
            a.discoverable = a.pairable = time.monotonic() < self._until
        return self.adapters, devs

    async def open_pairing(self, adapter, seconds):
        self._until = time.monotonic() + max(10, min(seconds, 300))

    async def close_pairing(self):
        self._until = 0.0

    async def pair(self, address):
        from .sim import SimDevice
        if time.monotonic() >= self._until:
            return "pairing window is closed; open it first"
        name = self.discovered.get(address)
        if not name:
            return "device not found"
        self.graph.add_device(SimDevice(address, name))
        return "paired and connected"

    async def connect(self, address):
        d = self.graph.devices.get(address)
        if not d:
            return "unknown device"
        d.connected = True
        return "connected"

    async def disconnect(self, address):
        d = self.graph.devices.get(address)
        if d:
            d.connected = False
        return "disconnected"

    async def forget(self, address):
        self.graph.remove_device(address)
        return "forgotten"

    async def trust(self, address, on=True):
        return None
