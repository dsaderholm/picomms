#!/usr/bin/env python3
"""Hardware-free check that PipeWire SUMS several links into one sink (validation T3).

Creates three virtual sinks with pactl (pipewire-pulse): A and B receive different
sine tones, and both monitors are linked into MIX with pw-link. We record MIX and
verify that BOTH tones are present at roughly their original levels (a sum, not
"last one wins" and not clipped).

WRITTEN WITHOUT A PIPEWIRE INSTALLATION TO RUN IT ON. Port names such as
`monitor_MONO` / `playback_MONO` are what PipeWire normally creates for mono null
sinks; if your system differs, run `pw-link -io` and adjust the constants below.
Run as the 'crewline' user on the appliance:   python3 tools/pw_mix_selftest.py
"""
import array
import math
import struct
import subprocess
import sys
import time
import wave
import tempfile
import os

RATE = 16000
F_A, F_B = 600.0, 1000.0


def sh(*a, check=True, **kw):
    return subprocess.run(a, check=check, capture_output=True, text=True, **kw)


def tone_wav(path, freq, secs=4.0, amp=0.3):
    n = int(secs * RATE)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes(struct.pack(f"<{n}h", *[int(amp * 32767 * math.sin(2 * math.pi * freq * i / RATE)) for i in range(n)]))


def goertzel_amp(samples, freq):
    n = len(samples)
    k = 2 * math.cos(2 * math.pi * freq / RATE)
    s1 = s2 = 0.0
    for x in samples:
        s0 = x + k * s1 - s2
        s2, s1 = s1, s0
    power = s1 * s1 + s2 * s2 - k * s1 * s2
    return 2 * math.sqrt(max(power, 0)) / n


def main():
    mods = []
    tmp = tempfile.mkdtemp(prefix="cl-mix-")
    procs = []
    try:
        for name in ("cl-test-a", "cl-test-b", "cl-test-mix"):
            mods.append(sh("pactl", "load-module", "module-null-sink", f"sink_name={name}", "channels=1",
                           f"sink_properties=node.name={name}").stdout.strip())
        time.sleep(0.5)
        for src, port in (("cl-test-a", "monitor_MONO"), ("cl-test-b", "monitor_MONO")):
            sh("pw-link", f"{src}:{port}", "cl-test-mix:playback_MONO")
        wa, wb, out = (os.path.join(tmp, n) for n in ("a.wav", "b.wav", "mix.wav"))
        tone_wav(wa, F_A); tone_wav(wb, F_B)
        rec = subprocess.Popen(["pw-cat", "--record", "--target", "cl-test-mix", "--rate", str(RATE),
                                "--channels", "1", "--format", "s16", out])
        time.sleep(0.5)
        procs = [subprocess.Popen(["pw-cat", "--playback", "--target", "cl-test-a", wa]),
                 subprocess.Popen(["pw-cat", "--playback", "--target", "cl-test-b", wb])]
        for p in procs:
            p.wait(timeout=15)
        time.sleep(0.3)
        rec.terminate(); rec.wait(timeout=5)
        with wave.open(out) as w:
            raw = w.readframes(w.getnframes())
        s = array.array("h"); s.frombytes(raw)
        mid = [float(v) / 32768 for v in s[RATE: RATE * 3]]      # steady middle 2 s
        a, b = goertzel_amp(mid, F_A), goertzel_amp(mid, F_B)
        peak = max(abs(v) for v in mid) if mid else 0
        print(f"tone A {F_A:.0f} Hz amplitude {a:.3f} (sent 0.300)")
        print(f"tone B {F_B:.0f} Hz amplitude {b:.3f} (sent 0.300)")
        print(f"peak {peak:.3f} (expected about 0.6 for a clean sum)")
        ok = 0.2 < a < 0.4 and 0.2 < b < 0.4 and peak < 0.95
        print("RESULT:", "PASS - PipeWire sums multiple links into one sink" if ok else "FAIL - see numbers above")
        sys.exit(0 if ok else 1)
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
        for m in mods:
            sh("pactl", "unload-module", m, check=False)


if __name__ == "__main__":
    main()
