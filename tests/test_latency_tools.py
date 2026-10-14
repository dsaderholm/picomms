import struct
import wave

from picomms.tools.latency import analyze_stereo, click_train_wav


def test_click_train_and_known_delay_are_measured(tmp_path):
    ref = tmp_path / "ref.wav"
    click_train_wav(str(ref), count=8, interval_s=1.0)
    with wave.open(str(ref)) as w:
        mono = struct.unpack(f"<{w.getnframes()}h", w.readframes(w.getnframes()))
    delay = int(0.153 * 16000)                       # 153 ms synthetic latency
    cap = [0] * delay + [int(v * 0.3) for v in mono]
    cap = cap[: len(mono)]
    out = tmp_path / "st.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(16000)
        inter = [x for pair in zip(mono, cap) for x in pair]
        w.writeframes(struct.pack(f"<{len(inter)}h", *inter))
    r = analyze_stereo(str(out))
    assert r["matched"] == 8
    assert abs(r["median_ms"] - 153) < 3 and r["jitter_ms"] < 2
