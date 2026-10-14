"""Crewline web process: dashboard, pocket remote and admin UI.

This process holds no audio and no device state. It talks to the engine over a
local unix socket and can crash, restart or be switched off without affecting
anyone's audio. It is LAN-only by design (see ``ip_allowed``).
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import os
import time
import tomllib
from pathlib import Path

import aiohttp
from aiohttp import web

from ..buttons import ACTION_LABELS, EVENT_LABELS
from .auth import DEFAULT_ALLOWED, AuthStore, RateLimiter, ip_allowed

log = logging.getLogger("crewline.web")
STATIC = Path(__file__).parent / "static"
LINK = web.AppKey("link", object)
AUTH = web.AppKey("auth", object)

# What a pocket-remote link may do, for ITS OWN endpoint only. Permissions
# (allowed groups, all-call) are enforced again by the engine's controller.
REMOTE_ACTIONS = {
    "ptt:down", "ptt:up", "talk:toggle", "mute:on", "mute:off", "mute:toggle",
    "allcall:on", "allcall:off", "allcall:toggle", "attention", "status",
}


class EngineLink:
    """Unix-socket client for the engine plus a fan-out of its event stream."""

    def __init__(self, sock: str) -> None:
        self.sock = sock
        self.ok = False
        self._subs: set[asyncio.Queue] = set()
        self._task: asyncio.Task | None = None

    def session(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=self.sock),
                                     timeout=aiohttp.ClientTimeout(total=15))

    async def call(self, method: str, path: str, body: dict | None = None):
        try:
            async with self.session() as s:
                async with s.request(method, "http://engine" + path, json=body) as r:
                    ctype = r.headers.get("Content-Type", "")
                    data = await r.json() if "json" in ctype else await r.text()
                    self.ok = True
                    return r.status, data
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            self.ok = False
            return 503, {"ok": False, "error": "engine offline (audio is not affected; controls are unavailable)",
                         "engine_offline": True}

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(self._pump())

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=300)
        self._subs.add(q)
        return q

    def unsubscribe(self, q) -> None:
        self._subs.discard(q)

    def _fan(self, ev: dict) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                self._subs.discard(q)

    async def _pump(self) -> None:
        backoff = 0.5
        while True:
            try:
                async with aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=self.sock),
                                                 timeout=aiohttp.ClientTimeout(total=None, sock_read=40)) as s:
                    async with s.get("http://engine/events") as r:
                        self.ok = True
                        self._fan({"type": "engine", "ok": True})
                        backoff = 0.5
                        async for raw in r.content:
                            line = raw.decode(errors="replace").strip()
                            if line.startswith("data:"):
                                try:
                                    self._fan(json.loads(line[5:]))
                                except json.JSONDecodeError:
                                    pass
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            if self.ok:
                self.ok = False
                self._fan({"type": "engine", "ok": False})
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 5)


def public_state(st: dict) -> dict:
    """What a dashboard viewer may see: no addresses, adapters, batteries or tokens."""
    return {
        "simulated": st["simulated"], "show_mode": st["show_mode"],
        "groups": st["groups"],
        "attention_target": st["attention_target"],
        "attention": [a for a in st["attention"] if a["active"]],
        "captions": {k: st["captions"].get(k) for k in ("enabled", "connected")},
        "endpoints": [{
            "id": e["id"], "name": e["name"], "kind": e["kind"], "enabled": e["enabled"],
            "connected": e["connected"], "audio_up": e["audio_up"], "muted": e["muted"] or e["forced_mute"],
            "forced_mute": e["forced_mute"], "transmitting": e["transmitting"], "speaking": e["speaking"],
            "allcall": e["allcall"], "talk": e["talk"], "listen": e["listen"], "talk_mode": e["talk_mode"],
            "level_db": e["level_db"],
        } for e in st["endpoints"]],
    }


def build_cheatsheet(ep: dict, binfo: dict, groups: list[dict]) -> dict:
    gname = {g["id"]: g["name"] for g in groups}
    observed = {o["event"]: o for o in binfo.get("observed", [])}
    rows = []
    for event, action in binfo.get("mappings", {}).items():
        base = event.removesuffix(":long")
        label = EVENT_LABELS.get(base, base) + (" (hold)" if event.endswith(":long") else "")
        text = ACTION_LABELS.get(action)
        if text is None and ":" in action:
            kind, _, arg = action.partition(":")
            text = {"select": f"Talk to {gname.get(arg, arg)}", "listen": f"Listen to {gname.get(arg, arg)} on/off"}.get(kind, action)
        rows.append({"button": label, "does": text or action,
                     "verified": base in observed, "seen": observed.get(base, {}).get("count", 0)})
    hint = binfo.get("profile_hint")
    return {
        "mapped": rows,
        "unmapped_seen": [{"button": EVENT_LABELS.get(k, k), "seen": v["count"]}
                          for k, v in observed.items() if k not in binfo.get("mappings", {})],
        "local_only": (hint or {}).get("known_local", []),
        "note": "Headset buttons are shortcuts. Everything they do is also available on this page.",
        "dial_codes": [],
    }


def make_app(args) -> web.Application:
    cfg = {"allowed_networks": DEFAULT_ALLOWED, "viewer_mode": "open", "viewer_pin": "",
           "ack_requires_admin": False}
    if args.config and Path(args.config).exists():
        cfg.update(tomllib.loads(Path(args.config).read_text()))
    auth = AuthStore(Path(args.state_dir) / "web-auth.json")
    first = auth.load()
    if first:
        note = Path(args.state_dir) / "FIRST-RUN-ADMIN-PASSWORD.txt"
        note.write_text(f"Admin password (change it with `crewline-web --set-password`):\n{first}\n")
        os.chmod(note, 0o600)
        log.warning("Generated first-run admin password; see %s", note)
    link = EngineLink(args.socket)
    login_limit = RateLimiter(6, 60)
    remote_limit = RateLimiter(40, 10)

    @web.middleware
    async def guard(request: web.Request, handler):
        peer = request.transport.get_extra_info("peername") if request.transport else None
        ip = peer[0] if peer else None
        if not ip_allowed(ip, cfg["allowed_networks"]):
            return web.Response(status=403, text="Crewline is available on the local network only.")
        if request.method in ("POST", "PUT", "DELETE") and request.headers.get("X-Requested-With") != "crewline":
            return web.json_response({"ok": False, "error": "missing X-Requested-With header"}, status=403)
        resp = await handler(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Content-Security-Policy",
                                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                                "frame-ancestors 'none'")
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    app = web.Application(middlewares=[guard])
    app[LINK] = link
    app[AUTH] = auth

    def is_admin(req: web.Request) -> bool:
        return auth.check_session(req.cookies.get("crewline_session"))

    def need_admin(req: web.Request) -> None:
        if not is_admin(req):
            raise web.HTTPUnauthorized(text=json.dumps({"ok": False, "error": "login required"}),
                                       content_type="application/json")

    def viewer_ok(req: web.Request) -> bool:
        if is_admin(req) or cfg["viewer_mode"] == "open":
            return True
        pin = req.headers.get("X-Viewer-Pin") or req.query.get("pin", "")
        return bool(cfg["viewer_pin"]) and pin == cfg["viewer_pin"]

    def need_viewer(req: web.Request) -> None:
        if not viewer_ok(req):
            raise web.HTTPUnauthorized(text=json.dumps({"ok": False, "error": "viewer PIN required", "pin": True}),
                                       content_type="application/json")

    def page(name: str):
        async def h(req: web.Request) -> web.StreamResponse:
            return web.FileResponse(STATIC / name, headers={"Cache-Control": "no-store"})
        return h

    routes = web.RouteTableDef()

    # ---- pages -----------------------------------------------------------------
    routes.get("/")(page("dashboard.html"))
    routes.get("/admin")(page("admin.html"))
    routes.get("/help")(page("help.html"))
    routes.get("/r/{token}")(page("remote.html"))
    routes.static("/static", STATIC)

    # ---- auth --------------------------------------------------------------------
    @routes.post("/api/login")
    async def login(req):
        ip = req.transport.get_extra_info("peername")[0]
        if not login_limit.allow(ip):
            return web.json_response({"ok": False, "error": "too many attempts; wait a minute"}, status=429)
        b = await req.json()
        if not auth.check_password(str(b.get("password", ""))):
            await asyncio.sleep(0.5)
            return web.json_response({"ok": False, "error": "wrong password"}, status=401)
        resp = web.json_response({"ok": True})
        resp.set_cookie("crewline_session", auth.make_session(), httponly=True, samesite="Strict", max_age=12 * 3600)
        return resp

    @routes.post("/api/logout")
    async def logout(req):
        resp = web.json_response({"ok": True})
        resp.del_cookie("crewline_session")
        return resp

    @routes.get("/api/me")
    async def me(req):
        return web.json_response({"admin": is_admin(req), "viewer_ok": viewer_ok(req),
                                  "viewer_mode": cfg["viewer_mode"], "engine_ok": link.ok})

    # ---- public (dashboard) ----------------------------------------------------------
    @routes.get("/api/public/state")
    async def pstate(req):
        need_viewer(req)
        status, st = await link.call("GET", "/state")
        if status != 200:
            return web.json_response({"engine_offline": True}, status=503)
        return web.json_response(public_state(st))

    @routes.get("/api/public/captions")
    async def pcaps(req):
        need_viewer(req)
        status, data = await link.call("GET", "/captions/recent")
        return web.json_response(data if status == 200 else [])

    async def sse(req: web.Request, allow) -> web.StreamResponse:
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-store",
                                           "X-Accel-Buffering": "no"})
        await resp.prepare(req)
        q = link.subscribe()
        idle = 0.0
        try:
            await resp.write(f"data: {json.dumps({'type': 'engine', 'ok': link.ok})}\n\n".encode())
            while True:
                if req.transport is None or req.transport.is_closing():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), 1.0)
                except asyncio.TimeoutError:
                    idle += 1.0
                    if idle >= 15:
                        idle = 0.0
                        await resp.write(b": keepalive\n\n")
                    continue
                idle = 0.0
                out = allow(ev)
                if out:
                    await resp.write(f"data: {json.dumps(out)}\n\n".encode())
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            link.unsubscribe(q)
        return resp

    def viewer_event(ev: dict):
        t = ev.get("type")
        if t in ("state", "attention", "attention_ack", "config", "engine", "caption", "speaking"):
            return ev
        return None            # button/log events are admin-only

    @routes.get("/api/public/events")
    async def pevents(req):
        need_viewer(req)
        return await sse(req, viewer_event)

    @routes.post("/api/public/attention/ack")
    async def pack(req):
        if cfg["ack_requires_admin"]:
            need_admin(req)
        else:
            need_viewer(req)
        status, data = await link.call("POST", "/attention/ack", {"by": "dashboard", **(await req.json())})
        return web.json_response(data, status=status)

    # ---- pocket remote -----------------------------------------------------------------
    def ep_for_token(req: web.Request) -> str:
        eid = auth.endpoint_for_token(req.match_info["token"])
        if not eid:
            raise web.HTTPNotFound(text=json.dumps({"ok": False, "error": "this link is no longer valid"}),
                                   content_type="application/json")
        return eid

    @routes.get("/api/r/{token}/state")
    async def rstate(req):
        eid = ep_for_token(req)
        status, st = await link.call("GET", "/state")
        if status != 200:
            return web.json_response({"engine_offline": True}, status=503)
        me_ = next((e for e in st["endpoints"] if e["id"] == eid), None)
        if not me_:
            raise web.HTTPNotFound()
        _, binfo = await link.call("GET", f"/buttons/{eid}")
        pub = public_state(st)
        mine = {k: me_[k] for k in ("id", "name", "enabled", "connected", "audio_up", "muted", "forced_mute",
                                    "latched_on", "ptt_down", "allcall", "transmitting", "talk_mode",
                                    "can_allcall", "can_select", "talk", "listen", "listen_allowed",
                                    "talk_allowed", "tone_control")}
        mine["dial_codes"] = []
        if me_["tone_control"]:
            cmds = st["dtmf"]["commands"]
            gname = {g["id"]: g["name"] for g in st["groups"]}
            for d, a in sorted(cmds.items()):
                kind, _, arg = a.partition(":")
                text = ACTION_LABELS.get(a) or {"select": f"Talk to {gname.get(arg, arg)}",
                                                "listen": f"Listen to {gname.get(arg, arg)} on/off"}.get(kind, a)
                mine["dial_codes"].append({"digit": d, "does": text})
            mine["dial_prefix"] = st["dtmf"]["prefix"]
        return web.json_response({"me": mine, "groups": st["groups"], "endpoints": pub["endpoints"],
                                  "attention": pub["attention"], "show_mode": st["show_mode"],
                                  "simulated": st["simulated"],
                                  "cheatsheet": build_cheatsheet(me_, binfo if isinstance(binfo, dict) else {}, st["groups"])})

    @routes.post("/api/r/{token}/do")
    async def rdo(req):
        eid = ep_for_token(req)
        ip = req.transport.get_extra_info("peername")[0]
        if not remote_limit.allow(ip + eid):
            return web.json_response({"ok": False, "error": "slow down"}, status=429)
        b = await req.json()
        action = str(b.get("action", ""))
        kind, _, arg = action.partition(":")
        if action not in REMOTE_ACTIONS and kind not in ("select", "listen"):
            return web.json_response({"ok": False, "error": "action not allowed from a remote link"}, status=400)
        status, data = await link.call("POST", "/control", {"endpoint": eid, "action": action, "source": "remote"})
        return web.json_response(data, status=status)

    @routes.get("/api/r/{token}/events")
    async def revents(req):
        ep_for_token(req)
        return await sse(req, viewer_event)

    @routes.get("/api/r/{token}/captions")
    async def rcaps(req):
        ep_for_token(req)
        status, data = await link.call("GET", "/captions/recent")
        return web.json_response(data if status == 200 else [])

    # ---- admin (everything below requires a login) ---------------------------------------------
    async def proxy(req: web.Request, method: str, path: str):
        need_admin(req)
        body = await req.json() if req.can_read_body and method == "POST" else None
        status, data = await link.call(method, path, body)
        if isinstance(data, str):
            return web.Response(text=data, status=status, content_type="application/json")
        return web.json_response(data, status=status)

    @routes.get("/api/admin/state")
    async def astate(req):
        need_admin(req)
        status, st = await link.call("GET", "/state")
        if status == 200:
            auth.prune({e["id"] for e in st["endpoints"]})
            for e in st["endpoints"]:
                e["remote_token"] = auth.token_for(e["id"])
        return web.json_response(st, status=status)

    @routes.get("/api/admin/readiness")
    async def areadiness(req):
        return await proxy(req, "GET", "/readiness")

    @routes.get("/api/admin/diagnose/{id}")
    async def adiagnose(req):
        return await proxy(req, "GET", f"/diagnose/{req.match_info['id']}")

    @routes.get("/api/admin/why")
    async def awhy(req):
        return await proxy(req, "GET", f"/why?src={req.query['src']}&dst={req.query['dst']}")

    @routes.get("/api/admin/log")
    async def alog(req):
        return await proxy(req, "GET", "/log")

    @routes.get("/api/admin/buttons/{id}")
    async def abuttons(req):
        return await proxy(req, "GET", f"/buttons/{req.match_info['id']}")

    @routes.get("/api/admin/config/export")
    async def aexport(req):
        need_admin(req)
        status, data = await link.call("GET", "/config/export")
        return web.Response(text=data if isinstance(data, str) else json.dumps(data),
                            content_type="application/json", status=status,
                            headers={"Content-Disposition": f'attachment; filename="crewline-config-{time.strftime("%Y%m%d-%H%M")}.json"'})

    @routes.post("/api/admin/{area}/{op}")
    async def apost(req):
        area, op = req.match_info["area"], req.match_info["op"]
        if area not in ("config", "bt", "test", "buttons", "control", "attention"):
            raise web.HTTPNotFound()
        return await proxy(req, "POST", f"/{area}/{op}")

    @routes.post("/api/admin/control")
    async def acontrol(req):
        return await proxy(req, "POST", "/control")

    @routes.post("/api/admin/remote/rotate")
    async def rotate(req):
        need_admin(req)
        b = await req.json()
        return web.json_response({"ok": True, "token": auth.rotate_token(b["endpoint"])})

    @routes.get("/api/admin/qr/{token}.svg")
    async def qr(req):
        need_admin(req)
        try:
            import segno
        except ImportError:
            raise web.HTTPNotFound(text="QR support not installed (pip install segno)")
        host = req.headers.get("Host", "")
        url = f"http://{host}/r/{req.match_info['token']}"
        buf = io.BytesIO()
        segno.make(url, error="m").save(buf, kind="svg", scale=6, border=2, xmldecl=False, svgns=True)
        return web.Response(body=buf.getvalue(), content_type="image/svg+xml")

    app.add_routes(routes)

    async def on_start(app):
        link.start()

    async def on_stop(app):
        if link._task:
            link._task.cancel()
            try:
                await link._task
            except (asyncio.CancelledError, Exception):
                pass

    app.on_startup.append(on_start)
    app.on_cleanup.append(on_stop)
    return app


def main() -> None:
    ap = argparse.ArgumentParser(description="Crewline web UI")
    ap.add_argument("--listen", default=os.environ.get("CREWLINE_LISTEN", "0.0.0.0:8080"))
    ap.add_argument("--socket", default=os.environ.get("CREWLINE_SOCKET", "/run/crewline/engine.sock"))
    ap.add_argument("--state-dir", default=os.environ.get("CREWLINE_STATE", "/var/lib/crewline"))
    ap.add_argument("--config", default=os.environ.get("CREWLINE_WEB_CONFIG", "/etc/crewline/web.toml"))
    ap.add_argument("--set-password", action="store_true", help="set the admin password and exit")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if a.set_password:
        import getpass
        store = AuthStore(Path(a.state_dir) / "web-auth.json")
        store.load()
        pw = getpass.getpass("New admin password (min 8 chars): ")
        if pw != getpass.getpass("Again: "):
            raise SystemExit("passwords differ")
        store.set_password(pw)
        print("password updated; existing sessions are invalidated")
        return
    host, _, port = a.listen.rpartition(":")
    web.run_app(make_app(a), host=host or "0.0.0.0", port=int(port), print=None, shutdown_timeout=3.0)


if __name__ == "__main__":
    main()
