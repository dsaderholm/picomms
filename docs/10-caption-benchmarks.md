# 10. Caption engine benchmark (SANDBOX ONLY — not target hardware)

Run on 2026-10-14 in the build sandbox (4 vCPU Intel Xeon @ 2.8 GHz VM, shared),
sherpa-onnx 1.13.8, CPU, int8 models, 2 threads. Raw data: `docs/results/asr-sandbox-2026-10-14.json`.
Tool: `tools/asr_bench.py` (reusable on the real caption computer).

**Treat as a functional smoke test and a rough guide to which engine family to prefer, not as a
measurement of your system.** Caveats, all important:

* One 11-second clip of one speaker — the famous JFK excerpt. Whisper-family models have likely
  *seen this exact audio*, so Whisper's 0.00 WER is optimistic.
* "whisper-proxy" is **synthetic**: the speech envelope excited by noise, not real whispering.
* "noise" is synthetic low-pass noise at 10 dB SNR, not production sound.
* Timing is on a shared cloud VM; RTF = processing time ÷ audio time; "delay" = time from end of the
  last audio chunk to final text.

| Engine | Condition | WER | RTF | Delay after last audio (s) |
|---|---|---|---|---|
| zipformer-20M (streaming) | clean | 0.18 | 0.045 | 0.03 |
| zipformer-20M (streaming) | quiet(-35dB) | 0.23 | 0.049 | 0.03 |
| zipformer-20M (streaming) | whisper-proxy(-38dB) | 0.59 | 0.051 | 0.03 |
| zipformer-20M (streaming) | clean+noise(10dB) | 0.23 | 0.045 | 0.03 |
| zipformer-20M (streaming) | whisper-proxy+noise(10dB) | 0.95 | 0.042 | 0.02 |
| whisper tiny.en | clean | 0.00 | 0.133 | 1.46 |
| whisper tiny.en | quiet(-35dB) | 0.00 | 0.123 | 1.36 |
| whisper tiny.en | whisper-proxy(-38dB) | 0.00 | 0.093 | 1.02 |
| whisper tiny.en | clean+noise(10dB) | 0.14 | 0.092 | 1.01 |
| whisper tiny.en | whisper-proxy+noise(10dB) | 0.14 | 0.087 | 0.96 |
| moonshine tiny (int8) | clean | 0.05 | 0.029 | 0.32 |
| moonshine tiny (int8) | quiet(-35dB) | 0.05 | 0.027 | 0.30 |
| moonshine tiny (int8) | whisper-proxy(-38dB) | 0.14 | 0.029 | 0.32 |
| moonshine tiny (int8) | clean+noise(10dB) | 0.09 | 0.025 | 0.27 |
| moonshine tiny (int8) | whisper-proxy+noise(10dB) | 0.18 | 0.029 | 0.32 |

## What this suggests (to confirm in T11)

* The small **streaming** Zipformer is fast but fell apart on quiet/whisper-like input and lost the first
  words — a poor fit for whispering booth users.
* **Moonshine-tiny** and **Whisper-tiny.en** were much more robust here; Moonshine was ~4× faster than
  Whisper-tiny for similar accuracy. Both are *segment* decoders: text appears after a pause (≈0.3–1.5 s
  for an 11 s segment; shorter for typical short crew phrases). That matches the design: the engine cuts
  speech segments with a 0.5 s pre-roll and the server returns interim text for long segments.
* Default engine proposed: **`sherpa-moonshine`** with Whisper as the accuracy fallback. Revisit after T11.
* Every model here is English-only; the tools make adding others a one-line change in
  `crewline/captions/engines.py`.

Reproduce on your caption computer:

```
pip install sherpa-onnx numpy
# download model archives from the sherpa-onnx GitHub release "asr-models" and extract each in its own directory
python tools/asr_bench.py --wav your_audio_16k_mono.wav --ref "exact transcript" \
  --engine sherpa-moonshine:/models/sherpa-onnx-moonshine-tiny-en-int8 \
  --engine sherpa-whisper:/models/sherpa-onnx-whisper-tiny.en:tiny.en --json results.json
```
