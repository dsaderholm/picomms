import pytest

from crewline.control import Controller, ControlEvent
from crewline.model import (
    Config, ConfigError, Endpoint, Group, default_config,
)
from crewline.routing import Link, compute_links, explain, init_state


def make_cfg():
    cfg = Config(
        groups=[Group("tech", "Tech", 1), Group("stage", "Stage", 2)],
        endpoints=[
            Endpoint("sound", "Sound", kind="rotary", listen=["tech", "stage"], talk=["tech"],
                     listen_allowed=["tech", "stage"], talk_allowed=["tech", "stage"],
                     can_allcall=True, tone_control=True),
            Endpoint("alex", "Alex", listen=["tech"], talk=["tech"],
                     listen_allowed=["tech"], talk_allowed=["tech"]),
            Endpoint("bo", "Bo", listen=["stage"], talk=["stage"],
                     listen_allowed=["stage"], talk_allowed=["stage"]),
            Endpoint("cy", "Cy", listen=["stage", "tech"], talk=["stage"],
                     listen_allowed=["stage", "tech"], talk_allowed=["stage"]),
        ],
        attention_target="sound",
    )
    cfg.validate()
    return cfg


def up(state):
    for s in state.values():
        s.connected = s.audio_up = True


def ctl(cfg=None):
    cfg = cfg or make_cfg()
    st = init_state(cfg)
    up(st)
    now = [100.0]
    c = Controller(lambda: cfg, st, clock=lambda: now[0], wall=lambda: 1000 + now[0])
    return cfg, st, c, now


def pairs(links):
    return {(l.src, l.dst) for l in links}


# ---- routing ---------------------------------------------------------------
def test_group_routing_is_mix_minus_and_full_duplex():
    cfg, st, c, _ = ctl()
    p = pairs(compute_links(cfg, st))
    # Sound talks to tech: Alex and Cy (listens to tech) hear Sound, Bo does not
    assert ("sound", "alex") in p and ("sound", "cy") in p and ("sound", "bo") not in p
    # Alex talks tech: Sound and Cy hear Alex
    assert ("alex", "sound") in p and ("alex", "cy") in p
    # nobody hears themselves
    assert not any(a == b for a, b in p)
    # full duplex within a group
    assert ("sound", "alex") in p and ("alex", "sound") in p


def test_disconnected_or_no_audio_endpoint_gets_no_links():
    cfg, st, c, _ = ctl()
    st["alex"].audio_up = False
    p = pairs(compute_links(cfg, st))
    assert not any("alex" in x for x in p)
    st["alex"].audio_up = True
    st["alex"].connected = False
    assert not any("alex" in x for x in pairs(compute_links(cfg, st)))


def test_mute_stops_transmit_but_not_receive():
    cfg, st, c, _ = ctl()
    c.apply(ControlEvent("alex", "mute:on"))
    p = pairs(compute_links(cfg, st))
    assert not any(a == "alex" for a, _ in p)
    assert ("sound", "alex") in p  # Alex still hears


def test_forced_mute_cannot_be_overridden_by_user():
    cfg, st, c, _ = ctl()
    cfg.endpoint("alex").forced_mute = True
    out = c.apply(ControlEvent("alex", "mute:off"))
    assert not out.accepted
    assert not any(a == "alex" for a, _ in pairs(compute_links(cfg, st)))
    assert ("sound", "alex") in pairs(compute_links(cfg, st))


def test_disabled_endpoint_neither_talks_nor_hears():
    cfg, st, c, _ = ctl()
    cfg.endpoint("alex").enabled = False
    assert not any("alex" in x for x in pairs(compute_links(cfg, st)))


def test_latched_and_ptt_modes():
    cfg, st, c, _ = ctl()
    cfg.endpoint("alex").talk_mode = "latched"
    assert not any(a == "alex" for a, _ in pairs(compute_links(cfg, st)))
    assert c.apply(ControlEvent("alex", "talk:toggle")).accepted
    assert ("alex", "sound") in pairs(compute_links(cfg, st))
    c.apply(ControlEvent("alex", "talk:toggle"))
    assert not any(a == "alex" for a, _ in pairs(compute_links(cfg, st)))

    cfg.endpoint("alex").talk_mode = "ptt"
    assert not any(a == "alex" for a, _ in pairs(compute_links(cfg, st)))
    c.apply(ControlEvent("alex", "ptt:down"))
    assert ("alex", "sound") in pairs(compute_links(cfg, st))
    c.apply(ControlEvent("alex", "ptt:up"))
    assert not any(a == "alex" for a, _ in pairs(compute_links(cfg, st)))


def test_talk_toggle_denied_when_not_latched():
    cfg, st, c, _ = ctl()
    out = c.apply(ControlEvent("alex", "talk:toggle"))
    assert not out.accepted and out.cues[0].kind == "denied"


# ---- selection / permissions -----------------------------------------------
def test_select_changes_talk_group_only_and_cues_only_that_endpoint():
    cfg, st, c, _ = ctl()
    out = c.apply(ControlEvent("sound", "select:stage", "dtmf"))
    assert out.accepted and st["sound"].talk == {"stage"}
    assert st["sound"].listen == {"tech", "stage"}  # still hears both
    assert [(q.endpoint, q.kind, q.group) for q in out.cues] == [("sound", "group", "stage")]
    p = pairs(compute_links(cfg, st))
    assert ("sound", "bo") in p and ("sound", "alex") not in p


def test_select_scope_both_moves_listening_too():
    cfg, st, c, _ = ctl()
    cfg.endpoint("sound").select_scope = "both"
    c.apply(ControlEvent("sound", "select:stage"))
    assert st["sound"].listen == {"stage"}


def test_permission_ceiling_enforced():
    cfg, st, c, _ = ctl()
    out = c.apply(ControlEvent("alex", "select:stage"))
    assert not out.accepted
    assert st["alex"].talk == {"tech"}  # unchanged
    assert out.cues[0].kind == "denied" and out.cues[0].endpoint == "alex"


def test_cannot_drop_last_listen_group():
    cfg, st, c, _ = ctl()
    out = c.apply(ControlEvent("alex", "listen:tech"))
    assert not out.accepted
    assert st["alex"].listen == {"tech"}
    # but an endpoint with two may drop one
    assert c.apply(ControlEvent("cy", "listen:tech")).accepted
    assert st["cy"].listen == {"stage"}


def test_can_select_false_blocks_changes():
    cfg, st, c, _ = ctl()
    cfg.endpoint("cy").can_select = False
    assert not c.apply(ControlEvent("cy", "select:stage")).accepted


# ---- all-call -------------------------------------------------------------
def test_allcall_requires_permission():
    cfg, st, c, _ = ctl()
    out = c.apply(ControlEvent("alex", "allcall:on"))
    assert not out.accepted and not st["alex"].allcall


def test_allcall_reaches_everyone_regardless_of_groups():
    cfg, st, c, _ = ctl()
    c.apply(ControlEvent("sound", "select:tech"))
    assert c.apply(ControlEvent("sound", "allcall:toggle")).accepted
    p = pairs(compute_links(cfg, st))
    assert {("sound", "alex"), ("sound", "bo"), ("sound", "cy")} <= p
    assert all(l.reason == "allcall" for l in compute_links(cfg, st) if l.src == "sound")


def test_allcall_works_for_latched_endpoint_and_ends_on_select():
    cfg, st, c, _ = ctl()
    cfg.endpoint("sound").talk_mode = "latched"
    assert not any(a == "sound" for a, _ in pairs(compute_links(cfg, st)))
    c.apply(ControlEvent("sound", "allcall:on"))
    assert ("sound", "bo") in pairs(compute_links(cfg, st))
    c.apply(ControlEvent("sound", "select:tech"))
    assert not st["sound"].allcall
    assert not any(a == "sound" for a, _ in pairs(compute_links(cfg, st)))


def test_allcall_blocked_while_muted_and_expires():
    cfg, st, c, now = ctl()
    c.apply(ControlEvent("sound", "mute:on"))
    assert not c.apply(ControlEvent("sound", "allcall:on")).accepted
    c.apply(ControlEvent("sound", "mute:off"))
    c.apply(ControlEvent("sound", "allcall:on"))
    now[0] += 19
    assert c.tick() == [] and st["sound"].allcall
    now[0] += 2
    cues = c.tick()
    assert not st["sound"].allcall
    assert [(q.endpoint, q.kind) for q in cues] == [("sound", "allcall_off")]


def test_tone_gate_closes_transmission():
    cfg, st, c, _ = ctl()
    st["sound"].tone_gate = True
    assert not any(a == "sound" for a, _ in pairs(compute_links(cfg, st)))
    st["sound"].tone_gate = False
    assert any(a == "sound" for a, _ in pairs(compute_links(cfg, st)))


# ---- attention --------------------------------------------------------------
def test_attention_does_not_depend_on_audio_or_mute():
    cfg, st, c, _ = ctl()
    st["alex"].muted = True
    out = c.apply(ControlEvent("alex", "attention", "web"))
    assert out.accepted and out.attention and out.attention.active
    # repeated presses collapse into the same alert
    again = c.apply(ControlEvent("alex", "attention", "button"))
    assert again.attention.id == out.attention.id and len(c.attention) == 1
    assert c.ack_attention(out.attention.id, "sound")
    assert not c.active_attention()
    # a new press after ack creates a new alert
    assert c.apply(ControlEvent("alex", "attention")).attention.id != out.attention.id


def test_attention_allowed_for_forced_muted_endpoint():
    cfg, st, c, _ = ctl()
    cfg.endpoint("alex").forced_mute = True
    assert c.apply(ControlEvent("alex", "attention")).accepted


# ---- explain ----------------------------------------------------------------
def test_explain_gives_concrete_reasons():
    cfg, st, c, _ = ctl()
    assert "via group tech" in explain(cfg, st, "alex", "sound")
    assert "listens to" in explain(cfg, st, "alex", "bo")
    st["alex"].muted = True
    assert "muted" in explain(cfg, st, "alex", "sound")
    st["alex"].muted = False
    st["alex"].audio_up = False
    assert "no active two-way audio" in explain(cfg, st, "alex", "sound")


# ---- config validation -------------------------------------------------------
def test_config_validation_rejects_bad_values():
    cfg = make_cfg()
    cfg.endpoints[1].talk = ["nope"]
    with pytest.raises(ConfigError):
        cfg.validate()
    cfg = make_cfg()
    cfg.endpoints[1].talk = ["stage"]  # beyond talk_allowed
    with pytest.raises(ConfigError):
        cfg.validate()
    cfg = make_cfg()
    cfg.endpoints[1].address = "not-a-mac"
    with pytest.raises(ConfigError):
        cfg.validate()
    cfg = make_cfg()
    cfg.dtmf.commands["9"] = "select:missing"
    with pytest.raises(ConfigError):
        cfg.validate()
    cfg = make_cfg()
    cfg.endpoints[2].name = "alex"
    with pytest.raises(ConfigError):
        cfg.validate()


def test_default_config_is_valid_and_roundtrips():
    cfg = default_config()
    again = Config.from_dict(cfg.to_dict())
    assert again.to_dict() == cfg.to_dict()


def test_muting_ends_an_allcall_so_it_cannot_resume_on_unmute():
    cfg, st, c, _ = ctl()
    c.apply(ControlEvent("sound", "allcall:on"))
    assert st["sound"].allcall
    c.apply(ControlEvent("sound", "mute:on"))
    assert not st["sound"].allcall
    c.apply(ControlEvent("sound", "mute:off"))
    assert not st["sound"].allcall
    assert ("sound", "bo") not in pairs(compute_links(cfg, st))
