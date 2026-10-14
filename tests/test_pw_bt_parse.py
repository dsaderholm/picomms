"""Parsers fed with synthetic data shaped like PipeWire's pw-dump and BlueZ's
GetManagedObjects. Key names were checked against PipeWire/BlueZ source and
docs; real-device output is still to be captured (validation test T1)."""
from crewline.bluez import HFP_HF_UUID, parse_managed_objects
from crewline.pwgraph import parse_dump

A, B = "AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02"


def node(i, name, cls, addr, profile="headset-head-unit"):
    return {"id": i, "type": "PipeWire:Interface:Node", "info": {"state": "running", "props": {
        "node.name": name, "media.class": cls, "api.bluez5.address": addr,
        "api.bluez5.profile": profile, "api.bluez5.codec": "msbc"}}}


def port(i, node_id, direction):
    return {"id": i, "type": "PipeWire:Interface:Port",
            "info": {"direction": direction, "props": {"node.id": node_id, "port.name": "x"}}}


def dump():
    return [
        node(10, "bluez_input.AA_BB_CC_DD_EE_01.0", "Audio/Source", A),
        node(11, "bluez_output.AA_BB_CC_DD_EE_01.1", "Audio/Sink", A),
        node(20, "bluez_input.AA_BB_CC_DD_EE_02.0", "Audio/Source", B),
        node(21, "bluez_output.AA_BB_CC_DD_EE_02.1", "Audio/Sink", B, profile="a2dp-sink"),
        node(30, "alsa_output.pci", "Audio/Sink", "11:22:33:44:55:66"),
        port(100, 10, "output"), port(101, 11, "input"),
        port(200, 20, "output"), port(201, 21, "input"),
        {"id": 500, "type": "PipeWire:Interface:Link", "info": {
            "output-node-id": 10, "output-port-id": 100, "input-node-id": 21, "input-port-id": 201}},
        {"id": 501, "type": "PipeWire:Interface:Link", "info": {
            "output-node-id": 30, "output-port-id": 1, "input-node-id": 21, "input-port-id": 201}},
        {"id": 50, "type": "PipeWire:Interface:Device", "info": {
            "props": {"device.name": "bluez_card.AA_BB_CC_DD_EE_01", "device.api": "bluez5",
                      "api.bluez5.address": A},
            "params": {"EnumProfile": [{"index": 1, "name": "a2dp-sink", "available": "yes"},
                                       {"index": 2, "name": "headset-head-unit", "available": "yes"}],
                       "Profile": [{"index": 1, "name": "a2dp-sink"}]}}},
    ]


def test_parse_dump_finds_bluetooth_nodes_ports_links_and_cards():
    s = parse_dump(dump())
    assert set(s.sources) == {A, B} and set(s.sinks) == {A, B}
    assert s.sources[A].out_ports == [100] and s.sinks[B].in_ports == [201]
    # only BT-source -> BT-sink links are reported; the ALSA link is ignored
    assert s.links == {500: (A, B)}
    assert s.cards[A].profiles["headset-head-unit"] == 2 and s.cards[A].active_profile == "a2dp-sink"


def test_audio_up_requires_hfp_profile_on_both_nodes():
    s = parse_dump(dump())
    assert s.audio_up(A) is True
    assert s.audio_up(B) is False        # sink is still A2DP: no two-way audio


def test_address_fallback_from_node_name():
    objs = [{"id": 1, "type": "PipeWire:Interface:Node", "info": {"props": {
        "node.name": "bluez_input.AA_BB_CC_DD_EE_09.0", "media.class": "Audio/Source"}}}]
    assert list(parse_dump(objs).sources) == ["AA:BB:CC:DD:EE:09"]


class V:               # stands in for dbus_fast.Variant
    def __init__(self, v):
        self.value = v


def test_parse_managed_objects():
    objs = {
        "/org/bluez/hci0": {"org.bluez.Adapter1": {
            "Address": V("00:11:22:33:44:55"), "Alias": V("hci0"), "Powered": V(True),
            "Discovering": V(False), "Discoverable": V(False), "Pairable": V(False)}},
        "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_01": {
            "org.bluez.Device1": {"Address": V(A), "Alias": V("JLab GO Work"), "Name": V("JLab GO Work"),
                                  "Adapter": V("/org/bluez/hci0"), "Paired": V(True), "Trusted": V(True),
                                  "Connected": V(True), "Icon": V("audio-headset"),
                                  "UUIDs": V([HFP_HF_UUID.upper()]), "RSSI": V(-48)},
            "org.bluez.Battery1": {"Percentage": V(80)}},
        "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_02": {
            "org.bluez.Device1": {"Address": V(B), "Alias": V("x"), "Adapter": V("/org/bluez/hci0"),
                                  "Paired": V(True), "Connected": V(False), "UUIDs": V([])}},
    }
    adapters, devices = parse_managed_objects(objs)
    assert adapters[0].address == "00:11:22:33:44:55" and adapters[0].hfp_connected == 1
    d = {x.address: x for x in devices}
    assert d[A].supports_hfp and d[A].battery == 80 and d[A].rssi == -48 and d[A].adapter == adapters[0].address
    assert d[B].battery is None and d[B].rssi is None      # unknown stays None
