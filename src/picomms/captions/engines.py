"""Speech-recognition engine adapters (run on the caption computer).

Each engine exposes ``open_session()`` returning a session with
``accept(pcm) -> interim text | None`` and ``finish() -> final text``.
Streaming engines (sherpa-onnx transducer) produce interim text as audio
arrives; offline engines (Whisper, Moonshine) decode when the segment ends
(and optionally on a timer for interim text).

Status: adapters are functionally exercised by ``picomms-asr-bench`` and
``tests/test_captions.py`` (echo engine only in CI). Accuracy/latency on the
*target* hardware and *real* booth audio is NOT yet measured -- see
docs/04-validation-plan.md test T11.
"""

from __future__ import annotations

import time
from array import array
from pathlib import Path
from typing import Protocol


class Session(Protocol):
    def accept(self, pcm: bytes) -> str | None: ...
    def finish(self) -> str: ...


class Engine(Protocol):
    name: str
    def open_session(self) -> Session: ...


def _float_samples(pcm: bytes):
    import numpy as np
    return np.frombuffer(pcm[: len(pcm) - (len(pcm) % 2)], dtype="<i2").astype("float32") / 32768.0


# --- trivial engine for tests / wiring checks ---------------------------------
class EchoEngine:
    name = "echo"

    class _S:
        def __init__(self) -> None:
            self.n = 0

        def accept(self, pcm: bytes) -> str | None:
            self.n += len(pcm)
            return None

        def finish(self) -> str:
            return f"[{self.n / 32000:.1f}s of speech]"

    def open_session(self) -> "EchoEngine._S":
        return EchoEngine._S()


# --- sherpa-onnx streaming transducer (true streaming) ------------------------
class SherpaStreaming:
    name = "sherpa-streaming"

    def __init__(self, model_dir: str, threads: int = 2, int8: bool = True) -> None:
        import sherpa_onnx
        d = Path(model_dir)
        suffix = ".int8.onnx" if int8 else ".onnx"

        def pick(prefix: str) -> str:
            c = sorted(d.glob(f"{prefix}*{suffix}"))
            if not c:
                raise FileNotFoundError(f"{prefix}*{suffix} not found in {d}")
            return str(c[0])

        self._rec = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(d / "tokens.txt"),
            encoder=pick("encoder"), decoder=pick("decoder"), joiner=pick("joiner"),
            num_threads=threads, sample_rate=16000, feature_dim=80,
            decoding_method="greedy_search",
        )

    class _S:
        def __init__(self, rec) -> None:
            self.rec = rec
            self.stream = rec.create_stream()
            self.last = ""

        def _decode(self) -> str:
            while self.rec.is_ready(self.stream):
                self.rec.decode_stream(self.stream)
            r = self.rec.get_result(self.stream)
            return (r if isinstance(r, str) else getattr(r, "text", "")).strip()

        def accept(self, pcm: bytes) -> str | None:
            self.stream.accept_waveform(16000, _float_samples(pcm))
            text = self._decode()
            if text and text != self.last:
                self.last = text
                return text
            return None

        def finish(self) -> str:
            import numpy as np
            self.stream.accept_waveform(16000, np.zeros(int(0.6 * 16000), dtype="float32"))  # flush tail
            self.stream.input_finished()
            return self._decode()

    def open_session(self):
        return SherpaStreaming._S(self._rec)


# --- offline engines through sherpa-onnx (Whisper, Moonshine) -----------------
class _OfflineSession:
    def __init__(self, decode, interim_every_s: float = 0.0) -> None:
        self._decode = decode
        self._buf = bytearray()
        self._every = interim_every_s
        self._next = interim_every_s
        self._last = ""

    def accept(self, pcm: bytes) -> str | None:
        self._buf += pcm
        if self._every and len(self._buf) / 32000 >= self._next:
            self._next += self._every
            text = self._decode(bytes(self._buf))
            if text and text != self._last:
                self._last = text
                return text
        return None

    def finish(self) -> str:
        return self._decode(bytes(self._buf)) if self._buf else ""


class SherpaWhisper:
    name = "sherpa-whisper"

    def __init__(self, model_dir: str, prefix: str = "tiny.en", threads: int = 2, interim_every_s: float = 0.0) -> None:
        import sherpa_onnx
        d = Path(model_dir)
        self._rec = sherpa_onnx.OfflineRecognizer.from_whisper(
            encoder=str(d / f"{prefix}-encoder.int8.onnx"),
            decoder=str(d / f"{prefix}-decoder.int8.onnx"),
            tokens=str(d / f"{prefix}-tokens.txt"),
            language="en", task="transcribe", num_threads=threads,
        )
        self._interim = interim_every_s

    def _decode(self, pcm: bytes) -> str:
        s = self._rec.create_stream()
        s.accept_waveform(16000, _float_samples(pcm))
        self._rec.decode_stream(s)
        return s.result.text.strip()

    def open_session(self):
        return _OfflineSession(self._decode, self._interim)


class SherpaMoonshine:
    name = "sherpa-moonshine"

    def __init__(self, model_dir: str, threads: int = 2, interim_every_s: float = 0.0) -> None:
        import sherpa_onnx
        d = Path(model_dir)
        self._rec = sherpa_onnx.OfflineRecognizer.from_moonshine(
            preprocessor=str(d / "preprocess.onnx"),
            encoder=str(d / "encode.int8.onnx"),
            uncached_decoder=str(d / "uncached_decode.int8.onnx"),
            cached_decoder=str(d / "cached_decode.int8.onnx"),
            tokens=str(d / "tokens.txt"), num_threads=threads,
        )
        self._interim = interim_every_s

    def _decode(self, pcm: bytes) -> str:
        s = self._rec.create_stream()
        s.accept_waveform(16000, _float_samples(pcm))
        self._rec.decode_stream(s)
        return s.result.text.strip()

    def open_session(self):
        return _OfflineSession(self._decode, self._interim)


class FasterWhisper:
    """faster-whisper (CTranslate2). Needs a local model dir (offline use)."""

    name = "faster-whisper"

    def __init__(self, model: str, threads: int = 4, compute_type: str = "int8",
                 interim_every_s: float = 0.0) -> None:
        from faster_whisper import WhisperModel
        self._m = WhisperModel(model, device="cpu", cpu_threads=threads, compute_type=compute_type)
        self._interim = interim_every_s

    def _decode(self, pcm: bytes) -> str:
        segs, _ = self._m.transcribe(_float_samples(pcm), language="en", beam_size=1,
                                     vad_filter=False, condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segs).strip()

    def open_session(self):
        return _OfflineSession(self._decode, self._interim)


def build_engine(spec: str) -> Engine:
    """``echo`` | ``sherpa-streaming:DIR`` | ``sherpa-whisper:DIR[:prefix]`` |
    ``sherpa-moonshine:DIR`` | ``faster-whisper:MODEL``"""
    kind, _, rest = spec.partition(":")
    if kind == "echo":
        return EchoEngine()
    if kind == "sherpa-streaming":
        return SherpaStreaming(rest)
    if kind == "sherpa-whisper":
        d, _, prefix = rest.partition(":")
        return SherpaWhisper(d, prefix or "tiny.en")
    if kind == "sherpa-moonshine":
        return SherpaMoonshine(rest)
    if kind == "faster-whisper":
        return FasterWhisper(rest)
    raise ValueError(f"unknown engine spec {spec!r}")
