"""Appliance-side caption forwarder.

Contract with the audio engine: ``submit_*`` NEVER blocks and NEVER raises.
If the server is down or slow, audio is dropped (bounded queue) and a health
state says so. Captions are best-effort by design.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from typing import Callable

from . import protocol as P

log = logging.getLogger("crewline.captionclient")


class CaptionClient:
    def __init__(self, on_text: Callable[[dict], None], site: str = "crewline", token: str = "",
                 max_queue_bytes: int = 2_000_000) -> None:
        self.on_text = on_text
        self.site = site
        self.token = token
        self.addr: tuple[str, int] | None = None
        self._q: deque[bytes] = deque()
        self._q_bytes = 0
        self._max = max_queue_bytes
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._seg_ids = 0
        self.connected = False
        self.engine = ""
        self.last_ok = 0.0
        self.last_error = ""
        self.dropped_bytes = 0
        self.last_result_ms: int | None = None
        self._meta: dict[int, dict] = {}

    # -- configuration --------------------------------------------------------
    def configure(self, server: str) -> None:
        """``host:port`` or empty to disable."""
        new = None
        if server:
            host, _, port = server.rpartition(":")
            new = (host, int(port))
        if new != self.addr:
            self.addr = new
            if self._task:
                self._task.cancel()
                self._task = None
            self.connected = False
            if new:
                self._task = asyncio.get_running_loop().create_task(self._run())

    @property
    def enabled(self) -> bool:
        return self.addr is not None

    def health(self) -> dict:
        return {
            "enabled": self.enabled, "connected": self.connected, "engine": self.engine,
            "last_error": self.last_error, "dropped_kb": self.dropped_bytes // 1024,
            "last_result_ms": self.last_result_ms,
            "last_ok_age_s": (time.monotonic() - self.last_ok) if self.last_ok else None,
        }

    # -- producer side (called from the audio engine, must never block) -------
    def start_segment(self, endpoint: str, name: str, group: str) -> int:
        self._seg_ids += 1
        seg = self._seg_ids
        self._meta[seg] = {"endpoint": endpoint, "name": name, "group": group}
        if len(self._meta) > 200:
            for k in sorted(self._meta)[:100]:
                self._meta.pop(k, None)
        self._enqueue(P.pack_json(P.SEG_START, {"seg": seg, **self._meta[seg]}))
        return seg

    def audio(self, seg: int, pcm: bytes) -> None:
        self._enqueue(P.pack_audio(seg, pcm))

    def end_segment(self, seg: int) -> None:
        self._enqueue(P.pack_end(seg))

    def _enqueue(self, frame: bytes) -> None:
        if not self.enabled or not self.connected:
            # Do not buffer audio while the server is away: stale captions are useless.
            if self.enabled:
                self.dropped_bytes += len(frame)
            return
        while self._q_bytes + len(frame) > self._max and self._q:
            old = self._q.popleft()
            self._q_bytes -= len(old)
            self.dropped_bytes += len(old)
        self._q.append(frame)
        self._q_bytes += len(frame)
        self._wake.set()

    # -- connection loop ------------------------------------------------------
    async def _run(self) -> None:
        backoff = 1.0
        while True:
            try:
                host, port = self.addr
                reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), 5)
                writer.write(P.pack_json(P.HELLO, {"v": 1, "site": self.site, "token": self.token}))
                await writer.drain()
                line = await asyncio.wait_for(reader.readline(), 5)
                hello = json.loads(line)
                self.engine = hello.get("engine", "")
                self.connected = True
                self.last_ok = time.monotonic()
                self.last_error = ""
                backoff = 1.0
                await asyncio.gather(self._send_loop(writer), self._recv_loop(reader))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"[:200]
            finally:
                self.connected = False
                self._q.clear()
                self._q_bytes = 0
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 15.0)

    async def _send_loop(self, writer: asyncio.StreamWriter) -> None:
        while True:
            while self._q:
                frame = self._q.popleft()
                self._q_bytes -= len(frame)
                writer.write(frame)
            await writer.drain()
            self._wake.clear()
            if not self._q:
                await self._wake.wait()

    async def _recv_loop(self, reader: asyncio.StreamReader) -> None:
        while True:
            line = await reader.readline()
            if not line:
                raise ConnectionError("server closed the connection")
            msg = json.loads(line)
            if "seg" in msg:
                self.last_ok = time.monotonic()
                self.last_result_ms = msg.get("proc_ms")
                meta = self._meta.get(msg["seg"], {})
                self.on_text({**meta, **msg})
