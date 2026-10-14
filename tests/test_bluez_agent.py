import pytest
from dbus_fast import DBusError

from crewline.bluez import make_agent

# Signatures from BlueZ doc/org.bluez.Agent.rst (agent-api).
EXPECTED = {
    "Release": ([], []),
    "RequestPinCode": (["o"], ["s"]),
    "DisplayPinCode": (["o", "s"], []),
    "RequestPasskey": (["o"], ["u"]),
    "DisplayPasskey": (["o", "u", "q"], []),
    "RequestConfirmation": (["o", "u"], []),
    "RequestAuthorization": (["o"], []),
    "AuthorizeService": (["o", "s"], []),
    "Cancel": ([], []),
}


def test_agent_dbus_signatures_match_bluez_agent_api():
    node = make_agent(lambda: True, lambda: set()).introspect()
    got = {m.name: ([a.signature for a in m.in_args], [a.signature for a in m.out_args]) for m in node.methods}
    assert got == EXPECTED


def test_agent_rejects_pairing_when_window_closed_but_accepts_known_devices():
    window = [False]
    known = {"AA:BB:CC:DD:EE:01"}
    agent = make_agent(lambda: window[0], lambda: known)
    unknown = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_99"
    knowndev = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_01"
    with pytest.raises(DBusError):
        agent._allow(unknown)
    agent._allow(knowndev)                 # configured headset may re-pair
    window[0] = True
    agent._allow(unknown)                  # window open: anyone may pair
