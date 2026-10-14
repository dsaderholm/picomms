"""Caption server: runs on the caption computer (or, if you accept the risk, the
appliance itself). Audio engine independence: this process can crash, lag or be
switched off without affecting any intercom audio."""

from __future__ import annotations

import argparse
import asyncio
import hmac
import json
import logging
import struct
import time
from concurrent.futures import ThreadPoolExecutor

from . import protocol as P
from .engines import Engine, build_engine

log = logging.getLogger("crewline.captionsrv")


class CaptionServer:
    def __init__(self, engine: Engine, token: str = "", workers: int = 2,
                 interim_min_gap_s: float = 0.4) -> None:
        self.engine = engine
        self.token = token
        self.pool = ThreadPoolExecutor(max_workers=workers)
        self.interim_gap = interim_min_gap_s

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        sessions: dict[int, object] = {}
        last_interim: dict[int, float] = {}
        loop = asyncio.get_running_loop()
        lock = asyncio.Lock()    # serialise per-connection engine use (sessions are not thread safe)

        async def send(obj: dict) -> None:
            writer.write(json.dumps(obj, separators=(",", ":")).encode() + b"\n")
            await writer.drain()

        try:
            kind, payload = await P.read_frame(reader)
            if kind != P.HELLO:
                return
            hello = json.loads(payload)
            if self.token and not hmac.compare_digest(str(hello.get("token", "")), self.token):
                log.warning("bad token from %s", peer)
                return
            await send({"hello": True, "engine": self.engine.name})
            while True:
                kind, payload = await P.read_frame(reader)
                if kind == P.SEG_START:
                    seg = json.loads(payload)["seg"]
                    sessions[seg] = self.engine.open_session()
                elif kind == P.AUDIO:
                    seg = struct.unpack("!I", payload[:4])[0]
                    s = sessions.get(seg)
                    if s is None:
                        continue
                    now = time.monotonic()
                    t0 = now
                    async with lock:
                        text = await loop.run_in_executor(self.pool, s.accept, payload[4:])
                    if text and now - last_interim.get(seg, 0) >= self.interim_gap:
                        last_interim[seg] = now
                        await send({"seg": seg, "text": text, "final": False,
                                    "proc_ms": int((time.monotonic() - t0) * 1000)})
                elif kind == P.SEG_END:
                    seg = struct.unpack("!I", payload[:4])[0]
                    s = sessions.pop(seg, None)
                    last_interim.pop(seg, None)
                    if s is None:
                        continue
                    t0 = time.monotonic()
                    async with lock:
                        text = await loop.run_in_executor(self.pool, s.finish)
                    await send({"seg": seg, "text": text, "final": True,
                                "proc_ms": int((time.monotonic() - t0) * 1000)})
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        except Exception:
            log.exception("caption connection failed")
        finally:
            writer.close()

    async def serve(self, host: str, port: int) -> None:
        srv = await asyncio.start_server(self.handle, host, port)
        log.info("caption server on %s:%s engine=%s", host, port, self.engine.name)
        async with srv:
            await srv.serve_forever()


def main() -> None:
    ap = argparse.ArgumentParser(description="Crewline caption server")
    ap.add_argument("--listen", default="0.0.0.0:7070")
    ap.add_argument("--engine", default="echo",
                    help="echo | sherpa-streaming:DIR | sherpa-whisper:DIR[:prefix] | "
                         "sherpa-moonshine:DIR | faster-whisper:MODEL")
    ap.add_argument("--token", default="", help="shared secret (strongly recommended)")
    ap.add_argument("--token-file", help="read the shared secret from this file")
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    token = a.token
    if a.token_file:
        from pathlib import Path
        token = Path(a.token_file).read_text().strip()
    host, _, port = a.listen.rpartition(":")
    asyncio.run(CaptionServer(build_engine(a.engine), token, a.workers).serve(host or "0.0.0.0", int(port)))


if __name__ == "__main__":
    main()
