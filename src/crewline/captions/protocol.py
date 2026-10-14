"""Caption wire protocol v1 (appliance -> caption server over TCP).

Frames:  type (1 byte) | length (4 bytes, big endian) | payload

  0x01 HELLO      JSON {"v": 1, "site": str, "token": str}
  0x02 SEG_START  JSON {"seg": int, "endpoint": str, "name": str, "group": str}
  0x03 AUDIO      seg (4 bytes BE) + signed 16-bit LE mono PCM @ 16 kHz
  0x04 SEG_END    seg (4 bytes BE)

Server -> appliance: newline-delimited JSON on the same connection:
  {"seg": int, "text": str, "final": bool, "proc_ms": int}
  {"hello": true, "engine": str}                      (once, after HELLO)

The appliance initiates the connection, so the caption computer needs no route
back to the appliance. Audio is sent ONLY for detected speech segments.
Neither side stores audio or text unless the operator explicitly turns
retention on (off by default).
"""

from __future__ import annotations

import json
import struct

HELLO, SEG_START, AUDIO, SEG_END = 1, 2, 3, 4
MAX_FRAME = 4 * 1024 * 1024


def pack(kind: int, payload: bytes) -> bytes:
    return struct.pack("!BI", kind, len(payload)) + payload


def pack_json(kind: int, obj: dict) -> bytes:
    return pack(kind, json.dumps(obj, separators=(",", ":")).encode())


def pack_audio(seg: int, pcm: bytes) -> bytes:
    return pack(AUDIO, struct.pack("!I", seg) + pcm)


def pack_end(seg: int) -> bytes:
    return pack(SEG_END, struct.pack("!I", seg))


async def read_frame(reader) -> tuple[int, bytes]:
    head = await reader.readexactly(5)
    kind, n = struct.unpack("!BI", head)
    if n > MAX_FRAME:
        raise ValueError("frame too large")
    return kind, await reader.readexactly(n) if n else b""
