from crewline.dtmf import DtmfDecoder
from conftest import (
    DTMF, RATE, dtmf_pcm, mix_pcm, noise_pcm, silence_pcm, tone_pcm,
)


def run(pcm, chunk=640, **kw):
    d = DtmfDecoder(**kw)
    ev = []
    for i in range(0, len(pcm), chunk):
        ev += d.feed(pcm[i : i + chunk])
    return ev


def digits(ev):
    return [e.digit for e in ev if e.kind == "digit"]


def test_all_sixteen_keys_decode():
    for k in DTMF:
        pcm = silence_pcm(0.1) + dtmf_pcm(k, 0.1) + silence_pcm(0.2)
        assert digits(run(pcm)) == [k], k


def test_sequence_with_gaps():
    pcm = b"".join(dtmf_pcm(k, 0.08) + silence_pcm(0.08) for k in "1203")
    assert digits(run(pcm + silence_pcm(0.3))) == list("1203")


def test_gate_opens_before_digit_confirms_and_closes_after_hold():
    pcm = silence_pcm(0.1) + dtmf_pcm("1", 0.1) + silence_pcm(0.5)
    ev = run(pcm)
    kinds = [e.kind for e in ev]
    assert kinds == ["gate_on", "digit", "gate_off"]
    on, dg, off = ev
    assert on.t <= dg.t + 1e-9
    # gate closes roughly gate_hold_ms (150) after the tone ended at 0.2 s
    assert 0.3 <= off.t <= 0.45


def test_short_blip_is_not_a_digit_but_still_gated():
    pcm = silence_pcm(0.1) + dtmf_pcm("5", 0.02) + silence_pcm(0.5)
    ev = run(pcm)
    assert digits(ev) == []


def test_tone_with_background_noise():
    for k in "0127":
        pcm = mix_pcm(dtmf_pcm(k, 0.12, amp=0.3), noise_pcm(0.12, amp=0.02))
        assert digits(run(silence_pcm(0.05) + pcm + silence_pcm(0.3))) == [k]


def test_quiet_tone_down_to_low_level():
    pcm = silence_pcm(0.05) + dtmf_pcm("2", 0.12, amp=0.02) + silence_pcm(0.3)
    assert digits(run(pcm)) == ["2"]


def test_normal_twist_accepted_reverse_twist_rejected():
    ok = silence_pcm(0.05) + dtmf_pcm("1", 0.12, twist_db=6.0) + silence_pcm(0.3)
    assert digits(run(ok)) == ["1"]
    bad = silence_pcm(0.05) + dtmf_pcm("1", 0.12, twist_db=-9.0) + silence_pcm(0.3)
    assert digits(run(bad)) == []


def test_single_frequency_is_not_dtmf():
    pcm = tone_pcm([1000], 0.3) + silence_pcm(0.2)
    assert digits(run(pcm)) == []
    pcm = tone_pcm([697], 0.3) + silence_pcm(0.2)
    assert digits(run(pcm)) == []


def test_two_row_tones_are_not_dtmf():
    pcm = tone_pcm([697, 770], 0.3) + silence_pcm(0.2)
    assert digits(run(pcm)) == []


def test_second_harmonic_rich_signal_rejected():
    """Voiced speech has strong even harmonics; pure DTMF has none."""
    import math, struct
    n = int(0.3 * RATE)
    out = []
    for i in range(n):
        v = 0.0
        for f in (697, 1209):
            v += math.sin(2 * math.pi * f * i / RATE)
            v += 0.7 * math.sin(2 * math.pi * 2 * f * i / RATE)
        out.append(int(v * 0.1 * 32767))
    assert digits(run(struct.pack(f"<{n}h", *out))) == []


def test_square_wave_generators_are_accepted():
    """Cheap phones may synthesise DTMF with square waves (odd harmonics only).

    The harmonic check deliberately targets *second* harmonics so such phones
    keep working. Real Cell2Jack tones must be checked in test T4.
    """
    import math, struct
    n = int(0.12 * RATE)
    out = []
    for i in range(n):
        v = 0.0
        for f in (697, 1209):
            v += 1 if math.sin(2 * math.pi * f * i / RATE) >= 0 else -1
        out.append(int(v * 0.05 * 32767))
    pcm = silence_pcm(0.05) + struct.pack(f"<{n}h", *out) + silence_pcm(0.3)
    assert digits(run(pcm)) == ["1"]


def test_chunking_does_not_matter():
    pcm = silence_pcm(0.1) + dtmf_pcm("8", 0.1) + silence_pcm(0.3)
    assert digits(run(pcm, chunk=2)) == digits(run(pcm, chunk=100000)) == ["8"]


def test_speech_talk_off(jfk_pcm):
    """Real speech (JFK clip, ~11 s) must not produce commands.

    This is a *single clip*: it is a regression guard, not proof that speech
    can never trigger a command. Production-room talk-off is measured by
    docs/04-validation-plan.md test T4b with the real room audio.
    """
    ev = run(jfk_pcm)
    assert digits(ev) == []
    # even spurious *gating* should be rare in speech (gate = muting the talker)
    gates = [e for e in ev if e.kind == "gate_on"]
    assert len(gates) <= 2, f"too many spurious gate events: {len(gates)}"


def test_speech_with_tone_inserted(jfk_pcm):
    mid = len(jfk_pcm) // 2
    mid -= mid % 2
    pcm = jfk_pcm[:mid] + dtmf_pcm("1", 0.1, amp=0.2) + jfk_pcm[mid : mid + 16000]
    assert digits(run(pcm)) == ["1"]


def test_diagnostics_hook_reports_rejection_reasons():
    d = DtmfDecoder()
    seen = []
    d.on_frame = seen.append
    d.feed(dtmf_pcm("1", 0.1, twist_db=-9.0))
    assert seen and all(f["result"] == "reverse-twist" for f in seen)
    seen.clear()
    d.feed(dtmf_pcm("1", 0.1))
    assert any(f["result"] == "ok" and f["digit"] == "1" for f in seen)
