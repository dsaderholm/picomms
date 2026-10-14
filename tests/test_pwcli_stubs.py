"""PipeWireCli against stub pw-dump / pw-link / wpctl / pw-cat executables.

The stubs keep a small JSON "graph" on disk and log every invocation, so we can
check the exact command lines Crewline issues (argument order, ids, which links
are touched). The stubs are our model of the tools -- real PipeWire output is
captured in validation test T0/T1.
"""
import json
import os
import stat
import sys

import pytest

from crewline.pwgraph import PipeWireCli

STUB = r'''#!{py}
import json, os, sys
name = os.path.basename(sys.argv[0])
state_path = os.environ["STUB_STATE"]
log = open(os.environ["STUB_LOG"], "a")
log.write(json.dumps([name] + sys.argv[1:]) + "\n"); log.close()
st = json.load(open(state_path))
def save(): json.dump(st, open(state_path, "w"))
if name == "pw-dump":
    print(json.dumps(st["objects"]))
elif name == "pw-link":
    a = sys.argv[1:]
    objs = st["objects"]
    if a[0] == "-d":
        st["objects"] = [o for o in objs if not (o["type"].endswith("Link") and str(o["id"]) == a[1])]
    else:
        ports = {o["id"]: o for o in objs if o["type"].endswith("Port")}
        out, inp = int(a[0]), int(a[1])
        nid = max(o["id"] for o in objs) + 1
        objs.append({"id": nid, "type": "PipeWire:Interface:Link", "info": {
            "output-node-id": ports[out]["info"]["props"]["node.id"], "output-port-id": out,
            "input-node-id": ports[inp]["info"]["props"]["node.id"], "input-port-id": inp}})
    save()
elif name == "wpctl":
    dev, idx = int(sys.argv[2]), int(sys.argv[3])
    for o in st["objects"]:
        if o["id"] == dev:
            names = {p["index"]: p["name"] for p in o["info"]["params"]["EnumProfile"]}
            o["info"]["params"]["Profile"] = [{"index": idx, "name": names[idx]}]
    save()
elif name == "pw-cat":
    if "--record" in sys.argv:
        sys.stdout.buffer.write(b"\x00\x00" * 640)
'''

A, B, C = "AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02", "AA:BB:CC:DD:EE:03"


def node(i, nm, cls, addr, profile="headset-head-unit"):
    return {"id": i, "type": "PipeWire:Interface:Node", "info": {"state": "running", "props": {
        "node.name": nm, "media.class": cls, "api.bluez5.address": addr,
        "api.bluez5.profile": profile, "api.bluez5.codec": "msbc"}}}


def port(i, nid, d):
    return {"id": i, "type": "PipeWire:Interface:Port", "info": {"direction": d, "props": {"node.id": nid}}}


def base_objects():
    objs = []
    for k, addr in enumerate((A, B, C)):
        n = 10 * (k + 1)
        mac = addr.replace(":", "_")
        objs += [node(n, f"bluez_input.{mac}.0", "Audio/Source", addr), node(n + 1, f"bluez_output.{mac}.1", "Audio/Sink", addr),
                 port(n + 2, n, "output"), port(n + 3, n + 1, "input")]
    # an unrelated, non-Bluetooth link that must NEVER be touched
    objs += [{"id": 5, "type": "PipeWire:Interface:Node", "info": {"props": {"node.name": "alsa_output.x", "media.class": "Audio/Sink"}}},
             {"id": 6, "type": "PipeWire:Interface:Port", "info": {"direction": "input", "props": {"node.id": 5}}},
             {"id": 7, "type": "PipeWire:Interface:Link", "info": {"output-node-id": 10, "output-port-id": 12, "input-node-id": 5, "input-port-id": 6}}]
    return objs


@pytest.fixture
def cli(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "stubtool.py"
    script.write_text(STUB.replace("{py}", sys.executable))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    for tool in ("pw-dump", "pw-link", "pw-cat", "wpctl"):
        (bindir / tool).symlink_to(script)
    state = tmp_path / "state.json"
    log = tmp_path / "calls.log"
    state.write_text(json.dumps({"objects": base_objects()}))
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setenv("STUB_STATE", str(state))
    monkeypatch.setenv("STUB_LOG", str(log))
    c = PipeWireCli()
    c.calls = lambda: [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
    c.state = lambda: json.loads(state.read_text())
    return c


async def test_reconcile_adds_links_in_the_right_direction_and_leaves_others_alone(cli):
    added, removed = await cli.reconcile({(A, B), (B, A), (A, C)})
    assert (added, removed) == (3, 0)
    snap = await cli.snapshot()
    assert set(snap.links.values()) == {(A, B), (B, A), (A, C)}
    # port ids: source A out=12, sink B in=23 -> `pw-link 12 23`
    assert ["pw-link", "12", "23"] in cli.calls()
    # the non-Bluetooth link (id 7) is untouched
    assert any(o["id"] == 7 for o in cli.state()["objects"])


async def test_reconcile_removes_only_unwanted_bluetooth_links(cli):
    await cli.reconcile({(A, B), (B, A), (A, C)})
    added, removed = await cli.reconcile({(A, B)})
    assert (added, removed) == (0, 2)
    snap = await cli.snapshot()
    assert set(snap.links.values()) == {(A, B)}
    assert any(o["id"] == 7 for o in cli.state()["objects"])
    assert not any(c[:2] == ["pw-link", "-d"] and c[2] == "7" for c in cli.calls())


async def test_reconcile_is_idempotent(cli):
    await cli.reconcile({(A, B)})
    n = len(cli.calls())
    added, removed = await cli.reconcile({(A, B)})
    assert (added, removed) == (0, 0)
    assert [c[0] for c in cli.calls()[n:]] == ["pw-dump"]     # only a snapshot, no writes


async def test_reconcile_skips_pairs_without_nodes(cli):
    added, _ = await cli.reconcile({(A, "AA:BB:CC:DD:EE:99")})
    assert added == 0


async def test_hfp_profile_switch_uses_wpctl_with_card_id_and_profile_index(cli):
    objs = cli.state()["objects"]
    objs.append({"id": 50, "type": "PipeWire:Interface:Device", "info": {
        "props": {"device.name": "bluez_card.AA_BB_CC_DD_EE_01", "device.api": "bluez5", "api.bluez5.address": A},
        "params": {"EnumProfile": [{"index": 1, "name": "a2dp-sink", "available": "yes"},
                                   {"index": 2, "name": "headset-head-unit", "available": "yes"}],
                   "Profile": [{"index": 1, "name": "a2dp-sink"}]}}})
    import json as _j, os as _o
    _j.dump({"objects": objs}, open(_o.environ["STUB_STATE"], "w"))
    snap = await cli.snapshot()
    switched = await cli.ensure_hfp_profile(snap)
    assert switched == [A]
    assert ["wpctl", "set-profile", "50", "2"] in cli.calls()
    # second call: already in HFP -> nothing to do
    assert await cli.ensure_hfp_profile(await cli.snapshot()) == []


async def test_cue_is_played_to_that_endpoints_sink_only(cli, tmp_path):
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"RIFF")
    await cli.play_cue(B, str(wav))
    pc = [c for c in cli.calls() if c[0] == "pw-cat"]
    assert len(pc) == 1
    assert pc[0][1:4] == ["--playback", "--target", f"bluez_output.{B.replace(':', '_')}.1"]
    assert pc[0][-1] == str(wav)


async def test_tap_reads_raw_s16_mono_from_the_microphone_node(cli):
    proc = await cli.start_tap(f"bluez_input.{A.replace(':', '_')}.0")
    data = await proc.stdout.read(2000)
    await proc.wait()
    assert len(data) == 1280
    args = [c for c in cli.calls() if c[0] == "pw-cat"][0]
    assert "--record" in args and "--raw" in args and args[args.index("--format") + 1] == "s16"
    assert args[args.index("--channels") + 1] == "1" and args[args.index("--rate") + 1] == "16000"


def test_missing_tools_raise_clear_error(monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(RuntimeError, match="missing PipeWire tools"):
        PipeWireCli()
