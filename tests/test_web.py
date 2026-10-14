"""Web process tests: authentication, LAN-only guard, viewer-safe state, remote links."""
import asyncio
from argparse import Namespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from crewline.bluez import SimBluetooth
from crewline.engine import Engine
from crewline.engine_api import serve_unix
from crewline.sim import SimDevice, SimGraph
from crewline.web.app import AUTH, make_app, public_state
from crewline.web.auth import AuthStore, RateLimiter, ip_allowed, DEFAULT_ALLOWED

H = {"X-Requested-With": "crewline"}


@pytest.fixture
async def stack(tmp_path):
    g = SimGraph(); bt = SimBluetooth(g)
    g.add_device(SimDevice("AA:BB:CC:00:00:02", "A"))
    eng = Engine(tmp_path / "state", g, bt, simulated=True)
    await eng.start()
    eng.store.upsert_endpoint({"id": "alex", "name": "Alex", "address": "AA:BB:CC:00:00:02",
                               "listen": ["tech"], "talk": ["tech"], "listen_allowed": ["tech"], "talk_allowed": ["tech"]})
    sock = str(tmp_path / "e.sock")
    runner = await serve_unix(eng, sock)
    cfg = tmp_path / "web.toml"
    cfg.write_text("")
    args = Namespace(socket=sock, state_dir=str(tmp_path / "state"), config=str(cfg))
    app = make_app(args)
    async with TestClient(TestServer(app)) as client:
        pw = (tmp_path / "state" / "FIRST-RUN-ADMIN-PASSWORD.txt").read_text().split("\n")[1]
        yield client, eng, pw, app, tmp_path
    await runner.cleanup()
    await eng.stop()


async def login(client, pw):
    r = await client.post("/api/login", json={"password": pw}, headers=H)
    assert r.status == 200
    return r


async def test_admin_requires_login(stack):
    c, eng, pw, app, _ = stack
    for path in ("/api/admin/state", "/api/admin/readiness", "/api/admin/log", "/api/admin/config/export"):
        assert (await c.get(path)).status == 401, path
    assert (await c.post("/api/admin/config/show_mode", json={"on": True}, headers=H)).status == 401
    assert not eng.store.config.show_mode


async def test_login_wrong_password_and_rate_limit(stack):
    c, eng, pw, app, _ = stack
    r = await c.post("/api/login", json={"password": "nope"}, headers=H)
    assert r.status == 401
    for _ in range(8):
        r = await c.post("/api/login", json={"password": "nope"}, headers=H)
    assert r.status == 429


async def test_state_changing_request_needs_custom_header(stack):
    c, eng, pw, app, _ = stack
    r = await c.post("/api/login", json={"password": pw})          # no header
    assert r.status == 403


async def test_admin_flow_after_login(stack):
    c, eng, pw, app, _ = stack
    await login(c, pw)
    st = await (await c.get("/api/admin/state")).json()
    assert any(e["address"] for e in st["endpoints"]) and all("remote_token" in e for e in st["endpoints"])
    r = await c.post("/api/admin/config/show_mode", json={"on": True}, headers=H)
    assert r.status == 200 and eng.store.config.show_mode
    r = await c.post("/api/admin/config/endpoint", json={"id": "x", "name": "X"}, headers=H)
    assert r.status == 423                                           # show mode lock reaches the UI as 423
    r = await c.get("/api/admin/config/export")
    assert r.status == 200 and "attachment" in r.headers["Content-Disposition"]


async def test_public_state_hides_device_details(stack):
    c, eng, pw, app, _ = stack
    r = await c.get("/api/public/state")
    body = await r.text()
    assert r.status == 200
    assert "AA:BB:CC" not in body and "battery" not in body and "adapter" not in body and "rssi" not in body
    assert "remote_token" not in body


async def test_public_events_hide_admin_only_events(stack):
    c, eng, pw, app, _ = stack
    resp = await c.get("/api/public/events")
    assert resp.status == 200
    await asyncio.sleep(0.3)                      # let the engine-link subscription settle
    eng.bus.publish({"type": "button", "endpoint": "alex", "event": "redial"})
    eng.bus.publish({"type": "log", "t": 0, "level": "info", "msg": "secret admin log"})
    eng.bus.publish({"type": "attention_ack"})
    seen = []
    async def read():
        async for raw in resp.content:
            line = raw.decode().strip()
            if line.startswith("data:"):
                seen.append(line)
                if "attention_ack" in line:
                    return
    await asyncio.wait_for(read(), 5)
    joined = " ".join(seen)
    assert "attention_ack" in joined
    assert "redial" not in joined and "secret admin log" not in joined
    resp.close()


async def test_remote_link_controls_only_its_own_endpoint_within_permissions(stack):
    c, eng, pw, app, _ = stack
    tok = app[AUTH].token_for("alex")
    r = await c.get(f"/api/r/{tok}/state")
    d = await r.json()
    assert d["me"]["id"] == "alex" and "address" not in d["me"]
    # allowed action
    r = await c.post(f"/api/r/{tok}/do", json={"action": "mute:on"}, headers=H)
    assert (await r.json())["ok"] and eng.state["alex"].muted
    # group beyond permission ceiling is refused by the engine, not just the UI
    r = await c.post(f"/api/r/{tok}/do", json={"action": "select:stage"}, headers=H)
    assert not (await r.json())["ok"] and eng.state["alex"].talk == {"tech"}
    # all-call not permitted for this endpoint
    r = await c.post(f"/api/r/{tok}/do", json={"action": "allcall:on"}, headers=H)
    assert not (await r.json())["ok"]
    # actions outside the remote whitelist are rejected outright
    r = await c.post(f"/api/r/{tok}/do", json={"action": "status; rm"}, headers=H)
    assert r.status == 400
    # attention works even while muted
    r = await c.post(f"/api/r/{tok}/do", json={"action": "attention"}, headers=H)
    assert (await r.json())["ok"] and eng.controller.active_attention()


async def test_bad_or_rotated_token_is_rejected(stack):
    c, eng, pw, app, _ = stack
    assert (await c.get("/api/r/not-a-token/state")).status == 404
    old = app[AUTH].token_for("alex")
    new = app[AUTH].rotate_token("alex")
    assert old != new
    assert (await c.get(f"/api/r/{old}/state")).status == 404
    assert (await c.get(f"/api/r/{new}/state")).status == 200


async def test_security_headers_and_no_inline_script_allowed(stack):
    c, *_ = stack
    r = await c.get("/")
    assert r.status == 200
    assert "script-src" not in r.headers["Content-Security-Policy"] or "unsafe-inline" not in r.headers["Content-Security-Policy"].split("script-src")[1]
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Frame-Options"] == "DENY"
    html = await r.text()
    import re
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), "inline script found"


async def test_lan_only_guard_blocks_public_addresses(tmp_path):
    g = SimGraph(); eng = Engine(tmp_path / "s", g, SimBluetooth(g), simulated=True)
    await eng.start()
    sock = str(tmp_path / "e.sock"); runner = await serve_unix(eng, sock)
    cfg = tmp_path / "web.toml"
    cfg.write_text('allowed_networks = ["10.0.0.0/8"]\n')     # test client is 127.0.0.1 -> now "outside"
    app = make_app(Namespace(socket=sock, state_dir=str(tmp_path / "s"), config=str(cfg)))
    async with TestClient(TestServer(app)) as c:
        assert (await c.get("/")).status == 403
        assert (await c.get("/api/public/state")).status == 403
    await runner.cleanup(); await eng.stop()


async def test_engine_offline_gives_clear_503_not_a_crash(tmp_path):
    (tmp_path / "s").mkdir()
    app = make_app(Namespace(socket=str(tmp_path / "nothing.sock"), state_dir=str(tmp_path / "s"), config=""))
    async with TestClient(TestServer(app)) as c:
        r = await c.get("/api/public/state")
        assert r.status == 503 and (await r.json())["engine_offline"]
        assert (await c.get("/")).status == 200                  # static pages still load


async def test_viewer_pin_mode(tmp_path):
    g = SimGraph(); eng = Engine(tmp_path / "s", g, SimBluetooth(g), simulated=True)
    await eng.start()
    sock = str(tmp_path / "e.sock"); runner = await serve_unix(eng, sock)
    cfg = tmp_path / "web.toml"; cfg.write_text('viewer_mode = "pin"\nviewer_pin = "4821"\n')
    app = make_app(Namespace(socket=sock, state_dir=str(tmp_path / "s"), config=str(cfg)))
    async with TestClient(TestServer(app)) as c:
        assert (await c.get("/api/public/state")).status == 401
        assert (await c.get("/api/public/state", headers={"X-Viewer-Pin": "0000"})).status == 401
        assert (await c.get("/api/public/state", headers={"X-Viewer-Pin": "4821"})).status == 200
    await runner.cleanup(); await eng.stop()


# ---- pure helpers -----------------------------------------------------------------------
def test_ip_allowed():
    for ok in ("127.0.0.1", "192.168.1.20", "10.2.3.4", "172.16.5.5", "::1", "fe80::1%eth0", "::ffff:192.168.0.9"):
        assert ip_allowed(ok, DEFAULT_ALLOWED), ok
    for bad in ("8.8.8.8", "172.32.0.1", "2001:4860:4860::8888", "", None, "garbage"):
        assert not ip_allowed(bad, DEFAULT_ALLOWED), bad


def test_sessions_expire_and_tampering_fails(tmp_path):
    a = AuthStore(tmp_path / "a.json"); a.load()
    tok = a.make_session(now=1000)
    assert a.check_session(tok, now=1001)
    assert not a.check_session(tok, now=1000 + 13 * 3600)
    assert not a.check_session(tok[:-2] + "00", now=1001)
    assert not a.check_session("1.2.3", now=1001) and not a.check_session(None)
    a.set_password("a-new-password")
    assert not a.check_session(tok, now=1001), "password change must invalidate old sessions"
    assert a.check_password("a-new-password") and not a.check_password("x")
    with pytest.raises(ValueError):
        a.set_password("short")


def test_auth_file_is_private(tmp_path):
    import os, stat
    a = AuthStore(tmp_path / "a.json"); a.load()
    assert stat.S_IMODE(os.stat(tmp_path / "a.json").st_mode) == 0o600


def test_rate_limiter():
    r = RateLimiter(3, 10)
    assert [r.allow("k", now=t) for t in (1, 2, 3, 4)] == [True, True, True, False]
    assert r.allow("k", now=20)
