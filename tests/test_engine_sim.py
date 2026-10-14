"""Engine integration tests against the simulated PipeWire/Bluetooth backends.

These prove the engine's control logic end to end. They say NOTHING about real
Bluetooth or PipeWire behaviour (that is what the hardware validation plan is for).
"""
import asyncio
import math
import struct

import pytest
from aiohttp.test_utils import TestClient, TestServer

from crewline.engine import Engine
from crewline.engine_api import make_app
from crewline.bluez import SimBluetooth
from crewline.sim import SimDevice, SimGraph

SOUND, ALEX, BO = "AA:BB:CC:00:00:01", "AA:BB:CC:00:00:02", "AA:BB:CC:00:00:03"


def dtmf(d, dur=0.12):
    rows = {"1": (697, 1209), "2": (697, 1336), "0": (941, 1336)}
    lo, hi = rows[d]
    n = int(dur * 16000)
    return struct.pack(f"<{n}h", *[
        int((math.sin(2 * math.pi * lo * i / 16000) + math.sin(2 * math.pi * hi * i / 16000)) * 0.2 * 32767)
        for i in range(n)])


async def wait_for(pred, timeout=3.0):
    t = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - t < timeout:
        if pred():
            return True
        await asyncio.sleep(0.02)
    return False


@pytest.fixture
async def rig(tmp_path):
    g = SimGraph()
    bt = SimBluetooth(g)
    for a, n in ((SOUND, "Rotary"), (ALEX, "A"), (BO, "B")):
        g.add_device(SimDevice(a, n))
    eng = Engine(tmp_path, g, bt, simulated=True)
    await eng.start()
    s = eng.store
    s.upsert_endpoint(s.config.endpoint("sound").__dict__ | {"address": SOUND})
    s.upsert_endpoint({"id": "alex", "name": "Alex", "address": ALEX, "listen": ["tech"], "talk": ["tech"],
                       "listen_allowed": ["tech"], "talk_allowed": ["tech"]})
    s.upsert_endpoint({"id": "bo", "name": "Bo", "address": BO, "listen": ["stage"], "talk": ["stage"],
                       "listen_allowed": ["stage"], "talk_allowed": ["stage"]})
    eng.kick()
    assert await wait_for(lambda: len(eng.links_now) > 0)
    yield eng, g
    await eng.stop()


async def test_links_follow_groups(rig):
    eng, g = rig
    assert (SOUND, ALEX) in g.links and (ALEX, SOUND) in g.links
    # Bo is on stage, Sound talks to tech: Bo does not hear Sound
    assert (SOUND, BO) not in g.links
    from crewline.control import ControlEvent
    await eng.control(ControlEvent("sound", "select:stage", "test"))
    assert await wait_for(lambda: (SOUND, BO) in g.links and (SOUND, ALEX) not in g.links)


async def test_cue_goes_only_to_affected_endpoint(rig):
    from crewline.control import ControlEvent
    eng, g = rig
    await eng.control(ControlEvent("sound", "select:stage", "dtmf"))
    assert await wait_for(lambda: len(g.cues) >= 1)
    assert {a for a, _ in g.cues} == {SOUND}
    assert g.cues[-1][1].endswith("group-2.wav")


async def test_disconnect_removes_links_and_reconnect_restores(rig):
    eng, g = rig
    g.devices[ALEX].connected = False
    eng.kick()
    assert await wait_for(lambda: not any(ALEX in l for l in g.links))
    assert not eng.state["alex"].audio_up
    g.devices[ALEX].connected = True
    eng.kick()
    assert await wait_for(lambda: (SOUND, ALEX) in g.links)


async def test_paired_but_no_voice_audio_is_diagnosed_not_routed(rig):
    eng, g = rig
    g.devices[ALEX].sco_ok = False        # pairs and connects, but no HFP voice nodes
    eng.kick()
    assert await wait_for(lambda: not any(ALEX in l for l in g.links))
    d = eng.diagnose("alex")
    assert any("no voice nodes" in f["msg"] for f in d)
    rd = {c["name"]: c for c in eng.readiness()}
    assert rd["Alex"]["level"] == "fail"


async def test_dtmf_tone_gates_tx_and_executes_command(rig):
    eng, g = rig
    assert await wait_for(lambda: SOUND in g.taps)
    tap = g.taps[SOUND]
    pcm = b"\x00\x00" * 3200 + dtmf("2") + b"\x00\x00" * 8000
    for i in range(0, len(pcm), 640):
        tap.push(pcm[i:i + 640])
        await asyncio.sleep(0.005)
    assert await wait_for(lambda: eng.state["sound"].talk == {"stage"})
    # the gate opened during the tone and closed again afterwards
    assert await wait_for(lambda: not eng.state["sound"].tone_gate, 3)
    assert (SOUND, BO) in g.links or await wait_for(lambda: (SOUND, BO) in g.links)


async def test_mute_and_show_mode_via_api(rig, tmp_path):
    eng, g = rig
    async with TestClient(TestServer(make_app(eng))) as c:
        r = await c.post("/control", json={"endpoint": "alex", "action": "mute:on", "source": "web"})
        assert (await r.json())["ok"]
        assert await wait_for(lambda: not any(l[0] == ALEX for l in g.links))
        # show mode: config locked, controls still work
        assert (await c.post("/config/show_mode", json={"on": True})).status == 200
        r = await c.post("/config/endpoint", json={"id": "z", "name": "Z"})
        assert r.status == 423
        r = await c.post("/bt/open_pairing", json={"seconds": 30})
        assert r.status == 423
        r = await c.post("/control", json={"endpoint": "alex", "action": "mute:off", "source": "web"})
        assert (await r.json())["ok"]
        assert await wait_for(lambda: (ALEX, SOUND) in g.links)
        r = await c.post("/bt/connect", json={"address": ALEX})       # reconnect allowed in show mode
        assert r.status == 200
        await c.post("/config/show_mode", json={"on": False})


async def test_pairing_window_flow(rig):
    eng, g = rig
    eng.bt.discovered["AA:BB:CC:00:00:09"] = "New Headset"
    async with TestClient(TestServer(make_app(eng))) as c:
        r = await c.post("/bt/pair", json={"address": "AA:BB:CC:00:00:09", "new_name": "Casey"})
        assert not (await r.json())["ok"]          # window closed
        await c.post("/bt/open_pairing", json={"seconds": 30})
        r = await c.post("/bt/pair", json={"address": "AA:BB:CC:00:00:09", "new_name": "Casey"})
        assert (await r.json())["ok"]
        assert eng.store.config.endpoint("casey").address == "AA:BB:CC:00:00:09"


async def test_attention_alert_flow_and_state_unknowns(rig):
    eng, g = rig
    async with TestClient(TestServer(make_app(eng))) as c:
        r = await c.post("/control", json={"endpoint": "alex", "action": "attention", "source": "web"})
        assert (await r.json())["attention"]["active"]
        st = await (await c.get("/state")).json()
        assert [a for a in st["attention"] if a["active"]]
        alex = next(e for e in st["endpoints"] if e["id"] == "alex")
        assert alex["battery"] is None and alex["hw_mute"] is None      # never invented
        await c.post("/attention/ack", json={"by": "sound"})
        st = await (await c.get("/state")).json()
        assert not [a for a in st["attention"] if a["active"]]


async def test_engine_survives_caption_server_down(rig):
    eng, g = rig
    eng.store.set_captions({"server": "127.0.0.1:1"})
    tap = g.taps.get(ALEX) or None
    assert await wait_for(lambda: ALEX in g.taps)
    from crewline.sim import speech_like
    pcm = speech_like(1.0)
    for i in range(0, len(pcm), 640):
        g.taps[ALEX].push(pcm[i:i + 640])
    await asyncio.sleep(0.3)
    assert (SOUND, ALEX) in g.links          # audio routing unaffected


async def test_buttons_learn_then_map_via_api(rig):
    eng, g = rig
    async with TestClient(TestServer(make_app(eng))) as c:
        await c.post("/buttons/learn", json={"endpoint": "alex", "seconds": 5})
        await c.post("/button/at", json={"address": ALEX, "at": "AT+BLDN"})
        info = await (await c.get("/buttons/alex")).json()
        assert info["observed"][0]["event"] == "redial" and info["learning_left_s"] > 0
        eng.buttons.learning.clear()
        ep = eng.store.config.endpoint("alex")
        eng.store.upsert_endpoint(ep.__dict__ | {"buttons": {"redial": "mute:toggle"}})
        await c.post("/button/at", json={"address": ALEX, "at": "AT+BLDN"})
        assert await wait_for(lambda: eng.state["alex"].muted)


async def test_cell2jack_digits_seen_as_at_commands_also_run_commands(rig):
    eng, g = rig
    eng.on_at(SOUND, "AT+VTS=2")
    assert await wait_for(lambda: eng.state["sound"].talk == {"stage"})
    eng.on_at(SOUND, "ATD1;")
    assert await wait_for(lambda: eng.state["sound"].talk == {"tech"})


async def test_engine_survives_bluez_not_ready(tmp_path):
    """BlueZ starting after the engine must not crash it; links/readiness reflect it."""
    from crewline.bluez import SimBluetooth

    class LateBt(SimBluetooth):
        calls = 0

        async def start(self):
            LateBt.calls += 1
            if LateBt.calls < 2:
                raise RuntimeError("org.bluez not on the bus yet")

    g = SimGraph()
    eng = Engine(tmp_path, g, LateBt(g), simulated=True)
    await eng.start()
    assert not eng.bt_ok
    assert any(c["name"] == "BlueZ" and c["level"] == "fail" for c in eng.readiness())
    assert await wait_for(lambda: eng.bt_ok, 5)
    await eng.stop()


async def test_engine_restart_does_not_tear_down_live_links(tmp_path):
    """Links linger in PipeWire across an engine restart. Before Bluetooth state is read,
    the engine must not treat 'unknown' as 'disconnected' and delete them."""
    from crewline.bluez import SimBluetooth
    from crewline.store import ConfigStore

    class SlowBt(SimBluetooth):
        async def start(self):
            await asyncio.sleep(0.6)             # BlueZ answers late after a restart

    g = SimGraph()
    for a in (SOUND, ALEX):
        g.add_device(SimDevice(a, "x"))
    # persisted configuration from "before the restart"
    s = ConfigStore(tmp_path / "config.json"); s.load()
    s.upsert_endpoint(s.config.endpoint("sound").__dict__ | {"address": SOUND})
    s.upsert_endpoint({"id": "alex", "name": "Alex", "address": ALEX, "listen": ["tech"], "talk": ["tech"],
                       "listen_allowed": ["tech"], "talk_allowed": ["tech"]})
    g.links = {(SOUND, ALEX), (ALEX, SOUND)}               # lingering links from the previous engine
    eng = Engine(tmp_path, g, SlowBt(g), simulated=True)
    await eng.start()
    await asyncio.sleep(0.4)                                # several cycles run before BlueZ is ready
    assert g.links == {(SOUND, ALEX), (ALEX, SOUND)}, "links were torn down while BT state was unknown"
    assert await wait_for(lambda: eng.bt_ok and eng._bt_known, 5)
    assert g.links == {(SOUND, ALEX), (ALEX, SOUND)}
    await eng.stop()
