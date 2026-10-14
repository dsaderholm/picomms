import array

from conftest import noise_pcm, silence_pcm, tone_pcm
from crewline.activity import ActivityMeter, Segmenter


def run(meter, pcm):
    return meter.feed_frames(pcm)


def quiet_voice(dur, amp):
    # amplitude-modulated 200 Hz "voiced" signal at the given linear amplitude
    return tone_pcm([200, 400, 600], dur, amp=amp)


def test_loud_speech_detected_and_ends_after_hangover():
    m = ActivityMeter()
    run(m, noise_pcm(1.0, 0.0005))
    r = run(m, quiet_voice(0.5, 0.2))
    assert r[-1][2] is True
    r = run(m, noise_pcm(1.0, 0.0005))
    assert r[0][2] is True      # still in hangover right after speech
    assert r[-1][2] is False


def test_whisper_level_speech_is_detected():
    """A whisper is ~30 dB below normal speech; it must still count as activity."""
    m = ActivityMeter()
    run(m, noise_pcm(1.5, 0.0006))             # very quiet booth, ~ -64 dBFS
    r = run(m, quiet_voice(0.6, 0.008))        # ~ -42 dBFS
    assert any(f[2] for f in r), "whisper not detected"


def test_steady_noise_does_not_trigger():
    m = ActivityMeter()
    r = run(m, noise_pcm(5.0, 0.01))
    # may trigger once at the very start while the floor adapts, not afterwards
    assert not any(f[2] for f in r[len(r) // 2:])


def test_segmenter_preroll_preserves_onset():
    m = ActivityMeter()
    s = Segmenter(preroll_ms=500)
    pcm = noise_pcm(1.0, 0.0006) + quiet_voice(0.6, 0.1) + noise_pcm(1.2, 0.0006)
    events = []
    for frame, _lvl, speaking in run(m, pcm):
        events += s.push(frame.tobytes(), speaking)
    kinds = [e.kind for e in events]
    assert kinds[0] == "start" and kinds[-1] == "end" and kinds.count("start") == 1
    audio = b"".join(e.pcm for e in events if e.kind == "audio")
    # at least pre-roll (500 ms) + voiced part; 16 kHz * 2 bytes
    assert len(audio) >= (0.5 + 0.55) * 32000


def test_segmenter_cuts_long_segments():
    s = Segmenter(max_segment_s=1.0)
    frame = b"\x01\x00" * 320
    kinds = []
    for _ in range(120):
        kinds += [e.kind for e in s.push(frame, True)]
    assert kinds.count("start") >= 2 and kinds.count("end") >= 1
