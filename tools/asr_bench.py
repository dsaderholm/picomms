#!/usr/bin/env python3
"""Benchmark caption engines on a WAV + reference transcript.

Run this ON THE CAPTION COMPUTER with representative audio. It reports, per
engine and per condition: word error rate (WER), wall time, real-time factor
(RTF = processing time / audio time) and, for streaming engines, the delay
between the end of the audio and the final text.

Conditions (all derived from the input WAV):
  clean      the WAV as is
  quiet      scaled to -35 dBFS RMS-ish (quiet talker / far from boom mic)
  whisper*   *SYNTHETIC proxy*: speech spectrum envelope excited by noise (no
             pitch), at low level. This is NOT real whispered speech. Real
             whispers recorded in your booth are required (T6/T11).
  +noise     any of the above mixed with stationary noise at a given SNR
             (stand-in for HVAC/fans). Real production sound is required (T6).

Usage:
  python tools/asr_bench.py --wav tests/data/jfk_16k.wav \
      --ref "and so my fellow americans ask not what your country can do for you ask what you can do for your country" \
      --engine sherpa-streaming:/models/zipformer --engine sherpa-whisper:/models/whisper:tiny.en

Output is printed as a table and, with --json, saved for the validation log.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from crewline.captions.engines import build_engine  # noqa: E402


def read_wav(path: str) -> np.ndarray:
    with wave.open(path) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2, \
            "need 16 kHz mono 16-bit WAV"
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0


def to_pcm(x: np.ndarray) -> bytes:
    return (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()


def rms_db(x: np.ndarray) -> float:
    return 20 * math.log10(max(1e-9, float(np.sqrt(np.mean(x ** 2)))))


def set_rms(x: np.ndarray, db: float) -> np.ndarray:
    return x * 10 ** ((db - rms_db(x)) / 20)


def whisper_proxy(x: np.ndarray, n_fft: int = 512, hop: int = 128, seed: int = 0) -> np.ndarray:
    """Replace the excitation with noise while keeping the spectral envelope."""
    rng = np.random.default_rng(seed)
    win = np.hanning(n_fft).astype(np.float32)
    out = np.zeros(len(x) + n_fft, dtype=np.float32)
    norm = np.zeros_like(out)
    for i in range(0, len(x) - n_fft, hop):
        spec = np.fft.rfft(x[i:i + n_fft] * win)
        mag = np.abs(spec)
        # smooth magnitude -> envelope (removes pitch harmonics)
        k = 9
        env = np.convolve(mag, np.ones(k) / k, mode="same")
        phase = rng.uniform(0, 2 * np.pi, len(mag))
        frame = np.fft.irfft(env * np.exp(1j * phase), n_fft).astype(np.float32)
        out[i:i + n_fft] += frame * win
        norm[i:i + n_fft] += win ** 2
    return (out / np.maximum(norm, 1e-6))[: len(x)]


def add_noise(x: np.ndarray, snr_db: float, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = rng.standard_normal(len(x)).astype(np.float32)
    # crude low-pass tilt: fans/HVAC are low-frequency heavy
    n = np.convolve(n, np.ones(8) / 8, mode="same")
    n = set_rms(n, rms_db(x) - snr_db)
    return x + n


def norm_words(s: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]+", " ", s.lower()).split()


def wer(ref: str, hyp: str) -> float:
    r, h = norm_words(ref), norm_words(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev = cur
    return d[len(h)] / max(1, len(r))


def run_engine(engine, pcm: bytes, chunk_ms: int = 100) -> tuple[str, float, float]:
    """Feed audio in real-time-sized chunks as fast as possible; return (text, wall_s, tail_delay_s)."""
    sess = engine.open_session()
    step = 32 * chunk_ms
    t0 = time.perf_counter()
    last = ""
    for i in range(0, len(pcm), step):
        r = sess.accept(pcm[i:i + step])
        if r:
            last = r
    t_end_audio = time.perf_counter()
    text = sess.finish()
    t1 = time.perf_counter()
    return text or last, t1 - t0, t1 - t_end_audio


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", required=True)
    ap.add_argument("--ref", required=True)
    ap.add_argument("--engine", action="append", required=True)
    ap.add_argument("--snr", type=float, default=10.0)
    ap.add_argument("--json")
    a = ap.parse_args()

    x = read_wav(a.wav)
    secs = len(x) / 16000
    conds = {
        "clean": x,
        "quiet(-35dB)": set_rms(x, -35.0),
        "whisper-proxy(-38dB)": set_rms(whisper_proxy(x), -38.0),
        f"clean+noise({a.snr:g}dB)": add_noise(set_rms(x, -26.0), a.snr),
        f"whisper-proxy+noise({a.snr:g}dB)": add_noise(set_rms(whisper_proxy(x), -38.0), a.snr),
    }
    results = []
    print(f"audio: {secs:.1f}s   (condition 'whisper-proxy' is SYNTHETIC, not real whispers)\n")
    print(f"{'engine':<28}{'condition':<34}{'WER':>6}{'RTF':>8}{'tail s':>8}  text")
    for spec in a.engine:
        t = time.perf_counter()
        eng = build_engine(spec)
        load = time.perf_counter() - t
        for cname, sig in conds.items():
            text, wall, tail = run_engine(eng, to_pcm(sig))
            w = wer(a.ref, text)
            results.append(dict(engine=spec, condition=cname, wer=w, rtf=wall / secs, tail_s=tail,
                                load_s=load, text=text))
            print(f"{spec.split('/')[-1][:27]:<28}{cname:<34}{w:>6.2f}{wall / secs:>8.3f}{tail:>8.2f}  {text[:60]}")
    if a.json:
        Path(a.json).write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
