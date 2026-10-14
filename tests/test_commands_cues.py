import io
import wave

from crewline.commands import DtmfCommandHandler
from crewline.cues import duration_s, render_wav
from crewline.dtmf import DtmfEvent
from crewline.model import default_config


def digit(d, t=0.0):
    return DtmfEvent("digit", t, d)


def test_single_digit_commands_map_to_actions():
    cfg = default_config()
    h = DtmfCommandHandler("sound", lambda: cfg)
    r = h.handle(digit("1"))
    assert [(c.endpoint, c.action, c.source) for c in r.controls] == [("sound", "select:tech", "dtmf")]
    assert h.handle(digit("2")).controls[0].action == "select:stage"
    assert h.handle(digit("0")).controls[0].action == "allcall:toggle"
    assert h.handle(digit("5")).controls is None  # unmapped digit ignored


def test_gate_events_pass_through():
    cfg = default_config()
    h = DtmfCommandHandler("sound", lambda: cfg)
    assert h.handle(DtmfEvent("gate_on", 0)).gate is True
    assert h.handle(DtmfEvent("gate_off", 1)).gate is False


def test_prefix_required_when_configured():
    cfg = default_config()
    cfg.dtmf.prefix = "*"
    now = [0.0]
    h = DtmfCommandHandler("sound", lambda: cfg, clock=lambda: now[0])
    assert h.handle(digit("1")).controls is None            # unarmed
    assert h.handle(digit("*")).controls is None            # arms
    assert h.handle(digit("1")).controls[0].action == "select:tech"
    assert h.handle(digit("1")).controls is None            # armed state consumed
    h.handle(digit("*"))
    now[0] += 5                                             # prefix timed out
    assert h.handle(digit("2")).controls is None


def test_cues_are_valid_wav_and_short():
    for kind in ("group", "mute_on", "mute_off", "allcall_on", "allcall_off",
                 "talk_on", "talk_off", "denied", "status", "attention_ack"):
        data = render_wav(kind, 2)
        with wave.open(io.BytesIO(data)) as w:
            assert w.getnchannels() == 1 and w.getframerate() == 16000
            assert 0.05 < w.getnframes() / 16000 < 0.8, kind


def test_group_cue_length_scales_with_beeps():
    assert duration_s("group", 3) > duration_s("group", 1)


def test_multi_key_codes_fire_when_complete_and_ignore_wrong_starts():
    cfg = default_config()
    cfg.dtmf.commands = {"1": "select:tech", "21": "select:stage", "22": "mute:toggle", "305": "status"}
    cfg.validate()
    now = [0.0]
    h = DtmfCommandHandler("sound", lambda: cfg, clock=lambda: now[0])
    assert h.handle(digit("1")).controls[0].action == "select:tech"
    assert h.handle(digit("2")).controls is None                 # waiting for the second key
    assert h.handle(digit("1")).controls[0].action == "select:stage"
    h.handle(digit("3")); h.handle(digit("0"))
    assert h.handle(digit("5")).controls[0].action == "status"
    h.handle(digit("2"))
    now[0] += 5                                                   # too slow: the start is forgotten
    assert h.handle(digit("1")).controls[0].action == "select:tech"
    h.handle(digit("2"))
    assert h.handle(digit("9")).controls is None                 # wrong second key resets
    assert h.handle(digit("2")).controls is None                 # a fresh "2" starts again
    assert h.handle(digit("2")).controls[0].action == "mute:toggle"


def test_multi_key_codes_work_after_the_prefix_key():
    cfg = default_config()
    cfg.dtmf.commands = {"21": "select:stage"}
    cfg.dtmf.prefix = "*"
    now = [0.0]
    h = DtmfCommandHandler("sound", lambda: cfg, clock=lambda: now[0])
    assert h.handle(digit("2")).controls is None                 # not armed
    h.handle(digit("*")); h.handle(digit("2"))
    assert h.handle(digit("1")).controls[0].action == "select:stage"
    assert h.handle(digit("2")).controls is None                 # disarmed again


def test_codes_that_start_other_codes_are_rejected():
    import pytest
    from crewline.model import ConfigError
    cfg = default_config()
    cfg.dtmf.commands = {"2": "select:stage", "21": "mute:toggle"}
    with pytest.raises(ConfigError, match="start of"):
        cfg.validate()
    cfg.dtmf.commands = {"12345": "mute:toggle"}
    with pytest.raises(ConfigError, match="invalid dial code"):
        cfg.validate()


def test_group_cue_pitch_gives_fifteen_distinct_cues():
    from crewline.cues import pattern
    seen = {tuple(pattern("group", n, p)) for n in range(1, 6) for p in ("low", "mid", "high")}
    assert len(seen) == 15
    assert pattern("group", 2, "low") != pattern("group", 2, "high")
    import pytest
    from crewline.model import Group, ConfigError
    with pytest.raises(ConfigError):
        Group(id="x", name="X", cue_pitch="shrill").validate()
