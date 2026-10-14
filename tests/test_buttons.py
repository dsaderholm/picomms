import pytest

from crewline.buttons import (
    AtTranslator, ButtonEvent, ButtonHub, attribute_avrcp, parse_btmon,
)
from crewline.control import Controller
from crewline.model import ConfigError, default_config
from crewline.routing import init_state


class Clock:
    t = 100.0

    def __call__(self):
        return self.t


def rig(buttons):
    cfg = default_config()
    ep = cfg.endpoint("sound")
    ep.buttons = buttons
    cfg.validate()
    sent = []
    clock = Clock()
    hub = ButtonHub(lambda: cfg, sent.append, clock)
    return cfg, hub, sent, clock


def test_unmapped_button_is_recorded_as_observed_only():
    cfg, hub, sent, _ = rig({})
    hub.feed(ButtonEvent("sound", "call_button", "tap", "hfp-at"))
    assert sent == []
    assert hub.observed_list("sound") == [{"event": "call_button", "count": 1, "source": "hfp-at"}]


def test_tap_maps_to_action():
    cfg, hub, sent, _ = rig({"redial": "mute:toggle"})
    hub.feed(ButtonEvent("sound", "redial", "tap", "hfp-at"))
    assert [(c.action, c.source) for c in sent] == [("mute:toggle", "button")]


def test_ptt_uses_press_and_release():
    cfg, hub, sent, _ = rig({"play_pause": "ptt"})
    hub.feed(ButtonEvent("sound", "play_pause", "press", "avrcp"))
    hub.feed(ButtonEvent("sound", "play_pause", "release", "avrcp"))
    assert [c.action for c in sent] == ["ptt:down", "ptt:up"]


def test_short_and_long_press_are_distinct():
    cfg, hub, sent, clock = rig({"play_pause": "mute:toggle", "play_pause:long": "attention"})
    hub.feed(ButtonEvent("sound", "play_pause", "press", "avrcp"))
    clock.t += 0.2
    hub.feed(ButtonEvent("sound", "play_pause", "release", "avrcp"))
    hub.feed(ButtonEvent("sound", "play_pause", "press", "avrcp"))
    clock.t += 1.0
    hub.feed(ButtonEvent("sound", "play_pause", "release", "avrcp"))
    assert [c.action for c in sent] == ["mute:toggle", "attention"]


def test_learn_mode_suppresses_actions_but_records():
    cfg, hub, sent, clock = rig({"redial": "mute:toggle"})
    hub.start_learning("sound", 10)
    hub.feed(ButtonEvent("sound", "redial", "tap", "hfp-at"))
    assert sent == [] and hub.observed_list("sound")[0]["count"] == 1
    clock.t += 11
    hub.feed(ButtonEvent("sound", "redial", "tap", "hfp-at"))
    assert len(sent) == 1


def test_invalid_button_mapping_rejected_by_config():
    cfg = default_config()
    cfg.endpoint("sound").buttons = {"laser_key": "mute:toggle"}
    with pytest.raises(ConfigError):
        cfg.validate()
    cfg.endpoint("sound").buttons = {"redial": "explode"}
    with pytest.raises(ConfigError):
        cfg.validate()


def test_at_translation():
    t = AtTranslator()
    a = "AA:BB:CC:DD:EE:01"
    assert t.translate(a, "AT+BRSF=511") == []                       # housekeeping
    assert t.translate(a, "AT+BLDN") == [("redial", "AT+BLDN")]
    assert t.translate(a, "AT+CKPD=200")[0][0] == "call_button"
    assert t.translate(a, "AT+BVRA=1")[0][0] == "voice_assist"
    assert t.translate(a, "AT+VGS=7") == []                          # first report: baseline only
    assert t.translate(a, "AT+VGS=8")[0][0] == "vol_up"
    assert t.translate(a, "AT+VGS=5")[0][0] == "vol_down"
    assert t.translate(a, "AT+VGS=5") == []
    assert t.translate(a, "AT+WEIRD=1")[0][0].startswith("raw:")    # shown, never guessed


def test_avrcp_attribution_refuses_to_guess_between_identical_headsets():
    cands = [{"id": "a", "name": "JLab GO Work", "adapter": "AD:1"},
             {"id": "b", "name": "JLab GO Work", "adapter": "AD:1"},
             {"id": "c", "name": "JLab GO Work", "adapter": "AD:2"},
             {"id": "d", "name": "Other", "adapter": "AD:1"}]
    assert attribute_avrcp("JLab GO Work (AVRCP)", "AD:1", cands) is None     # two units, same adapter
    assert attribute_avrcp("JLab GO Work (AVRCP)", "AD:2", cands) == "c"      # unique by adapter
    assert attribute_avrcp("Other (AVRCP)", "AD:1", cands) == "d"


BTMON = """\
@ MGMT Event: Device Connected (0x000b) plane 0
        LE Address: x
> HCI Event: Connect Complete (0x03) plane 0
        Status: Success (0x00)
        Handle: 256 Address: AA:BB:CC:DD:EE:01 (OUI AA-BB-CC)
> ACL Data RX: Handle 256 flags 0x02 dlen 17
      L2CAP: Unknown (0x03) len 13
        Channel: 66 len 13
      RFCOMM: Unnumbered Info with Header Check (UIH) (0xef)
        Address: 0x0b cr 1 dlci 0x02
         41 54 2b 56 47 53 3d 31 35 0d                    AT+VGS=15.
< ACL Data TX: Handle 256 flags 0x00 dlen 10
         0d 0a 4f 4b 0d 0a                                ..OK..
> ACL Data RX: Handle 256 flags 0x02 dlen 11
         41 54 2b 42 4c 44 4e 0d                          AT+BLDN.
"""


def test_parse_btmon_sample():
    got = list(parse_btmon(BTMON.splitlines()))
    assert got == [("AA:BB:CC:DD:EE:01", "AT+VGS=15"), ("AA:BB:CC:DD:EE:01", "AT+BLDN")]
