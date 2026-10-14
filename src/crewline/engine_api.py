"""Local control API of the engine (unix socket, not reachable from the network).

The web process is the only intended client. Authentication and authorisation
for people happen in the web process; this socket is protected by filesystem
permissions (group ``crewline``).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from aiohttp import web

from .control import ControlEvent
from .model import ConfigError, ConfigLocked, normalize_mac


def _json(data, status: int = 200) -> web.Response:
    return web.json_response(data, status=status, dumps=lambda o: json.dumps(o, default=str))


@web.middleware
async def errors(request: web.Request, handler):
    try:
        return await handler(request)
    except ConfigLocked as exc:
        return _json({"ok": False, "error": str(exc), "locked": True}, 423)
    except (ConfigError, ValueError, KeyError, TypeError) as exc:
        return _json({"ok": False, "error": str(exc)}, 400)
    except web.HTTPException:
        raise
    except Exception as exc:       # pragma: no cover - last resort
        return _json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)


def make_app(eng) -> web.Application:
    app = web.Application(middlewares=[errors])
    r = web.RouteTableDef()

    async def body(req: web.Request) -> dict:
        return await req.json() if req.can_read_body else {}

    @r.get("/state")
    async def state(req):
        return _json(eng.snapshot_state())

    @r.get("/readiness")
    async def readiness(req):
        return _json(eng.readiness())

    @r.get("/diagnose/{id}")
    async def diagnose(req):
        return _json(eng.diagnose(req.match_info["id"]))

    @r.get("/why")
    async def why(req):
        return _json({"why": eng.why(req.query["src"], req.query["dst"])})

    @r.get("/log")
    async def logs(req):
        return _json(list(eng.log_events))

    @r.get("/captions/recent")
    async def recent(req):
        return _json(list(eng.bus.recent_captions))

    @r.get("/events")
    async def events(req):
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
        await resp.prepare(req)
        q = eng.bus.subscribe()
        idle = 0.0
        try:
            await resp.write(b"event: hello\ndata: {}\n\n")
            while True:
                if req.transport is None or req.transport.is_closing():
                    break                          # client went away: free the handler promptly
                try:
                    ev = await asyncio.wait_for(q.get(), 1.0)
                    idle = 0.0
                    await resp.write(f"data: {json.dumps(ev, default=str)}\n\n".encode())
                except asyncio.TimeoutError:
                    idle += 1.0
                    if idle >= 15:
                        idle = 0.0
                        await resp.write(b": keepalive\n\n")
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            eng.bus.unsubscribe(q)
        return resp

    @r.post("/control")
    async def control(req):
        b = await body(req)
        out = await eng.control(ControlEvent(b["endpoint"], b["action"], b.get("source", "web")))
        return _json({"ok": out.accepted, "reason": out.reason, "changed": out.changed,
                      "attention": out.attention.to_dict() if out.attention else None})

    @r.post("/attention/ack")
    async def ack(req):
        b = await body(req)
        n = await eng.ack_attention(b.get("id"), b.get("by", "dashboard"))
        return _json({"ok": True, "acked": n})

    # ---- configuration (every call goes through the show-mode lock) ----------
    @r.post("/config/{op}")
    async def config(req):
        op, b, s = req.match_info["op"], await body(req), eng.store
        ops = {
            "show_mode": lambda: s.set_show_mode(b["on"]),
            "group": lambda: s.upsert_group(b),
            "group_delete": lambda: s.delete_group(b["id"]),
            "endpoint": lambda: s.upsert_endpoint(b),
            "endpoint_delete": lambda: s.delete_endpoint(b["id"]),
            "dtmf": lambda: s.set_dtmf(b),
            "captions": lambda: s.set_captions(b),
            "attention_target": lambda: s.set_attention_target(b["id"]),
            "restore": lambda: s.restore_json(b["json"]),
        }
        if op not in ops:
            raise KeyError(f"unknown config op {op}")
        ops[op]()
        eng.note(f"config: {op}")
        return _json({"ok": True})

    @r.get("/config/export")
    async def export(req):
        return web.Response(text=eng.store.export_json(), content_type="application/json")

    # ---- buttons -----------------------------------------------------------------
    @r.post("/button")
    async def button(req):
        from .buttons import ButtonEvent
        b = await body(req)
        eid = b.get("endpoint")
        if not eid and b.get("address"):
            ep = eng.endpoint_for_address(b["address"])
            eid = ep.id if ep else None
        if not eid:
            return _json({"ok": False, "error": "unknown device"}, 404)
        eng.on_button(ButtonEvent(eid, b["event"], b.get("phase", "tap"), b.get("source", "web"), b.get("raw", "")))
        return _json({"ok": True})

    @r.post("/button/at")
    async def button_at(req):
        b = await body(req)
        eng.on_at(normalize_mac(b["address"]), b["at"])
        return _json({"ok": True})

    @r.post("/buttons/learn")
    async def learn(req):
        b = await body(req)
        eng.buttons.start_learning(b["endpoint"], float(b.get("seconds", 30)))
        return _json({"ok": True})

    @r.get("/buttons/{id}")
    async def buttons_info(req):
        return _json(eng.buttons_info(req.match_info["id"]))

    # ---- Bluetooth -------------------------------------------------------------
    @r.post("/bt/{op}")
    async def bt(req):
        op, b = req.match_info["op"], await body(req)
        locked_ops = {"open_pairing", "pair", "forget", "disconnect"}
        if eng.store.config.show_mode and op in locked_ops:
            raise_locked()
        if op == "open_pairing":
            await eng.bt.open_pairing(b.get("adapter"), int(b.get("seconds", 60)))
            eng.note("pairing window opened")
            return _json({"ok": True})
        if op == "close_pairing":
            await eng.bt.close_pairing()
            eng.note("pairing window closed")
            return _json({"ok": True})
        addr = normalize_mac(b["address"])
        if op == "pair":
            msg = await eng.bt.pair(addr)
            ok = msg.startswith("paired")
            if ok and (b.get("endpoint") or b.get("new_name")):
                _assign(eng, addr, b)
            eng.note(f"pair {addr}: {msg}")
            return _json({"ok": ok, "message": msg})
        if op in ("connect", "disconnect", "forget"):
            msg = await getattr(eng.bt, op)(addr)
            if op == "forget":
                for e in eng.store.config.endpoints:
                    if e.address == addr:
                        d = e.__dict__ | {"address": None}
                        eng.store.upsert_endpoint(d)
            eng.note(f"{op} {addr}: {msg}")
            eng.kick()
            return _json({"ok": True, "message": msg})
        raise KeyError(f"unknown bt op {op}")

    # ---- tests -------------------------------------------------------------------
    @r.post("/test/mic/{id}")
    async def mic(req):
        return _json(await eng.mic_test(req.match_info["id"], float((await body(req)).get("seconds", 4))))

    @r.post("/test/cue/{id}")
    async def cue(req):
        from .control import Cue
        await eng.play([Cue(req.match_info["id"], "status")])
        return _json({"ok": True})

    app.add_routes(r)
    return app


def raise_locked():
    raise ConfigLocked("Show mode is on: pairing and device changes are locked. "
                       "Reconnecting a headset is still allowed.")


def _assign(eng, addr: str, b: dict) -> None:
    """After pairing, bind the address to an existing endpoint or create one."""
    s = eng.store
    if b.get("endpoint"):
        ep = s.config.endpoint(b["endpoint"])
        if ep:
            s.upsert_endpoint(ep.__dict__ | {"address": addr})
        return
    name = b["new_name"].strip()
    base = "".join(c for c in name.lower() if c.isalnum())[:20] or "headset"
    eid, n = base, 2
    while s.config.endpoint(eid):
        eid, n = f"{base}{n}", n + 1
    groups = [g.id for g in s.config.groups]
    s.upsert_endpoint({
        "id": eid, "name": name, "kind": "headset", "address": addr,
        "listen": groups[:1], "talk": groups[:1],
        "listen_allowed": groups[:1], "talk_allowed": groups[:1],
    })


async def serve_unix(eng, path: str) -> web.AppRunner:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    if os.path.exists(path):
        os.unlink(path)
    runner = web.AppRunner(make_app(eng), shutdown_timeout=2.0)
    await runner.setup()
    site = web.UnixSite(runner, path)
    await site.start()
    os.chmod(path, 0o660)
    return runner
