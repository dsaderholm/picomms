import asyncio

import pytest

from crewline.bluez import SimBluetooth
from crewline.engine import Engine
from crewline.mentions import MentionBook, expand_term, find_term, normalize
from crewline.sim import SimDevice, SimGraph

SOUND, ALEX, BO = "AA:BB:CC:00:00:01", "AA:BB:CC:00:00:02", "AA:BB:CC:00:00:03"


def test_normalize_handles_punctuation_and_possessives():
    assert normalize("DJ's  \"mic\" -- D.J.!") == "dj s mic d j"


def test_acronym_expands_to_spelled_and_spoken_forms():
    v = expand_term("DJ")
    assert {"dj", "d j", "dee jay", "dee j", "d jay"} <= set(v)
    assert expand_term("sound booth") == ["sound booth"]          # phrases stay as written
    assert expand_term("Alex") == ["alex"]                        # ordinary names are not expanded


@pytest.mark.parametrize("text", [
    "DJ the spotlight is flickering", "hey dj", "hey D J can you hear me", "dee jay we need a cue",
    "DJ's mic is off", "Thanks, D.J.!", "ask the dee j about it",
])
def test_dj_is_found_in_common_recogniser_spellings(text):
    assert find_term(text, ["DJ"]) == "DJ"


@pytest.mark.parametrize("text", [
    "we need to adjust the lights", "the dj-less band", "djembe drums on stage", "a jay walked by",
    "the dejay", "adjacent to the stage",
])
def test_no_false_hits_inside_other_words(text):
    # "the dj-less band" contains the word dj separated by punctuation, so it *does* count;
    # everything else must not.
    expected = "DJ" if text == "the dj-less band" else None
    assert find_term(text, ["DJ"]) == expected


def test_multi_word_phrase():
    assert find_term("is the sound  booth ready", ["sound booth"]) == "sound booth"
    assert find_term("booth sound", ["sound booth"]) is None


def test_book_dedupes_interim_and_final_of_one_segment_and_limits_cues():
    b = MentionBook()
    assert b.add("sound", "alex", "DJ", "hey dj", "stage", 7, 100.0)
    assert b.add("sound", "alex", "DJ", "hey dj the", "stage", 7, 100.5) is None      # same utterance
    assert b.add("sound", "alex", "DJ", "dj again", "stage", 8, 101.0)                 # new utterance
    assert b.cue_allowed("sound", 100.0, 8.0)
    assert not b.cue_allowed("sound", 105.0, 8.0)
    assert b.cue_allowed("sound", 109.0, 8.0)
    assert len(b.active(110.0)) == 2
    assert b.ack(None, 110.0) == 2 and not b.active(110.0)
    assert not b.active(1000.0)                                                         # old ones expire


# ---- engine integration (simulation) ------------------------------------------------------
async def until(pred, t=3.0):
    end = asyncio.get_event_loop().time() + t
    while asyncio.get_event_loop().time() < end:
        if pred():
            return True
        await asyncio.sleep(0.02)
    return False


@pytest.fixture
async def eng(tmp_path):
    g = SimGraph(); bt = SimBluetooth(g)
    for a in (SOUND, ALEX, BO):
        g.add_device(SimDevice(a, a))
    e = Engine(tmp_path, g, bt, simulated=True)
    await e.start()
    s = e.store
    s.upsert_endpoint(s.config.endpoint("sound").__dict__ | {"address": SOUND})
    for eid, addr in (("alex", ALEX), ("bo", BO)):
        s.upsert_endpoint({"id": eid, "name": eid.title(), "address": addr, "listen": ["tech"], "talk": ["tech"],
                           "listen_allowed": ["tech"], "talk_allowed": ["tech"]})
    e.kick()
    assert await until(lambda: e.state["sound"].audio_up and e.state["alex"].audio_up)
    yield e, g
    await e.stop()


async def test_mention_alerts_target_only_and_plays_cue_to_target_only(eng):
    e, g = eng
    seen = []
    q = e.bus.subscribe()
    e._on_caption({"seg": 1, "endpoint": "alex", "name": "Alex", "group": "tech", "text": "DJ can you hear me", "final": False})
    e._on_caption({"seg": 1, "endpoint": "alex", "name": "Alex", "group": "tech", "text": "DJ can you hear me now", "final": True})
    await asyncio.sleep(0.2)
    while not q.empty():
        seen.append(q.get_nowait())
    mentions = [x for x in seen if x["type"] == "mention"]
    assert len(mentions) == 1 and mentions[0]["mention"]["target"] == "sound"      # interim+final -> one
    assert [(a, p.rsplit("/", 1)[-1]) for a, p in g.cues] == [(SOUND, "mention.wav")]
    caps = [x for x in seen if x["type"] == "caption"]
    assert caps and all(c["mention"] and c["mention_targets"] == ["sound"] for c in caps)
    assert e.snapshot_state()["mentions"][0]["term"] == "DJ"


async def test_speaker_is_not_alerted_about_their_own_name(eng):
    e, g = eng
    e._on_caption({"seg": 2, "endpoint": "sound", "name": "Sound", "group": "tech", "text": "this is DJ speaking", "final": True})
    await asyncio.sleep(0.1)
    assert e.snapshot_state()["mentions"] == [] and g.cues == []


async def test_earpiece_cue_is_rate_limited_but_visual_alert_is_not(eng):
    e, g = eng
    for i in range(3):
        e._on_caption({"seg": 10 + i, "endpoint": "alex", "name": "Alex", "group": "tech", "text": "dj dj", "final": True})
    await asyncio.sleep(0.2)
    assert len(e.snapshot_state()["mentions"]) == 3
    assert len(g.cues) == 1                       # one cue inside the 8 s cooldown


async def test_cue_can_be_turned_off_per_person_and_other_people_have_their_own_terms(eng):
    e, g = eng
    s = e.store
    s.upsert_endpoint(s.config.endpoint("sound").__dict__ | {"mention_cue": False})
    s.upsert_endpoint(s.config.endpoint("bo").__dict__ | {"mention_terms": ["Bo", "stage manager"]})
    e._on_caption({"seg": 20, "endpoint": "alex", "name": "Alex", "group": "tech", "text": "DJ and bo please standby", "final": True})
    await asyncio.sleep(0.2)
    targets = sorted(m["target"] for m in e.snapshot_state()["mentions"])
    assert targets == ["bo", "sound"]
    assert [a for a, _ in g.cues] == [BO]         # Sound's cue is off; Bo's plays


async def test_test_mention_is_labelled_and_acknowledgeable(eng):
    e, g = eng
    assert e.test_mention("sound")
    m = e.snapshot_state()["mentions"][0]
    assert m["test"] and "(test)" in m["text"]
    await asyncio.sleep(0.1)
    assert [a for a, _ in g.cues] == [SOUND]
    assert e.ack_mentions(None) == 1 and e.snapshot_state()["mentions"] == []


def test_config_validation_of_mention_terms():
    from crewline.model import ConfigError, default_config
    cfg = default_config()
    cfg.endpoint("sound").mention_terms = ["x"] * 9
    with pytest.raises(ConfigError):
        cfg.validate()
    cfg.endpoint("sound").mention_terms = [" "]
    with pytest.raises(ConfigError):
        cfg.validate()
