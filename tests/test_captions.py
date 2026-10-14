import asyncio

import pytest

from picomms.captions.client import CaptionClient
from picomms.captions.engines import EchoEngine
from picomms.captions.server import CaptionServer


async def start_server(token=""):
    srv = CaptionServer(EchoEngine(), token=token)
    server = await asyncio.start_server(srv.handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


@pytest.mark.asyncio
async def test_round_trip_segment_gets_final_caption():
    server, port = await start_server("s3cret")
    got = []
    c = CaptionClient(got.append, token="s3cret")
    c.configure(f"127.0.0.1:{port}")
    for _ in range(100):
        if c.connected:
            break
        await asyncio.sleep(0.02)
    assert c.connected and c.engine == "echo"
    seg = c.start_segment("alex", "Alex", "tech")
    c.audio(seg, b"\x00\x00" * 16000)    # 1 s
    c.end_segment(seg)
    for _ in range(100):
        if got:
            break
        await asyncio.sleep(0.02)
    assert got and got[0]["final"] and got[0]["name"] == "Alex" and "1.0s" in got[0]["text"]
    c.configure("")
    server.close()


@pytest.mark.asyncio
async def test_bad_token_never_connects():
    server, port = await start_server("right")
    c = CaptionClient(lambda m: None, token="wrong")
    c.configure(f"127.0.0.1:{port}")
    await asyncio.sleep(0.5)
    assert not c.connected
    c.configure("")
    server.close()


@pytest.mark.asyncio
async def test_unreachable_server_never_blocks_or_raises():
    c = CaptionClient(lambda m: None)
    c.configure("127.0.0.1:1")      # nothing listens
    seg = c.start_segment("alex", "Alex", "tech")
    for _ in range(1000):
        c.audio(seg, b"\x00" * 6400)
    c.end_segment(seg)
    await asyncio.sleep(0.2)
    h = c.health()
    assert h["enabled"] and not h["connected"] and h["dropped_kb"] > 0
    c.configure("")


@pytest.mark.asyncio
async def test_disabled_client_is_a_noop():
    c = CaptionClient(lambda m: None)
    seg = c.start_segment("a", "A", "g")
    c.audio(seg, b"\x00\x00")
    c.end_segment(seg)
    assert not c.health()["enabled"]
