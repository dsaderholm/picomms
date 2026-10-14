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
from .network import default_ssid, new_passphrase


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
            "site_name": lambda: s.set_site_name(b["name"]),
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

    @r.post("/announce")
    async def announce(req):
        b = await body(req)
        return _json({"ok": True, "announcement": eng.announce(b["text"], b.get("by", ""))})

    @r.post("/mention/ack")
    async def mention_ack(req):
        b = await body(req)
        return _json({"ok": True, "acked": eng.ack_mentions(b.get("id"))})

    @r.post("/test/mention/{id}")
    async def test_mention(req):
        return _json({"ok": eng.test_mention(req.match_info["id"])})

    # ---- network (hotspot, uplink, passthrough) ---------------------------------------
    def need_unlocked():
        if eng.store.config.show_mode:
            raise ConfigLocked("Show mode is on: network changes are locked (they would disconnect every phone). "
                               "Turn show mode off first.")

    def need_net():
        if eng.net is None:
            raise ValueError("network control is not configured on this appliance")

    @r.get("/network")
    async def net_info(req):
        await eng.refresh_network()
        return _json(eng.network_info())

    @r.post("/network/suggest")
    async def net_suggest(req):
        return _json({"ssid": default_ssid(), "password": new_passphrase()})

    @r.post("/network/settings")
    async def net_settings(req):
        need_unlocked()
        eng.store.set_network(await body(req))
        eng.note("config: network settings")
        return _json({"ok": True})

    @r.post("/network/ap/start")
    async def net_ap_start(req):
        need_unlocked(); need_net()
        n = eng.store.config.network
        if not n.ap_ssid or not n.ap_password:
            raise ValueError("set a hotspot name and password first")
        eng.store.set_network({"ap_enabled": True})
        msg = await eng.net.apply_ap(eng.store.config.network)
        eng.note(f"hotspot: {msg}")
        await eng.refresh_network()
        return _json({"ok": msg == "hotspot started", "message": msg})

    @r.post("/network/ap/stop")
    async def net_ap_stop(req):
        need_unlocked(); need_net()
        eng.store.set_network({"ap_enabled": False})
        msg = await eng.net.stop_ap()
        eng.note(f"hotspot: {msg}")
        await eng.refresh_network()
        return _json({"ok": True, "message": msg})

    @r.get("/network/scan")
    async def net_scan(req):
        need_net()
        return _json(await eng.net.scan(req.query.get("iface", "")))

    @r.post("/network/join")
    async def net_join(req):
        need_unlocked(); need_net()
        b = await body(req)
        msg = await eng.net.join(b["iface"], b["ssid"], b.get("password", ""))
        eng.note(f"uplink Wi-Fi {b['ssid']}: {msg}")
        await eng.refresh_network()
        return _json({"ok": msg == "connected", "message": msg})

    @r.post("/network/forget")
    async def net_forget(req):
        need_unlocked(); need_net()
        msg = await eng.net.forget((await body(req))["name"])
        await eng.refresh_network()
        return _json({"ok": True, "message": msg})

    @r.post("/network/passthrough")
    async def net_passthrough(req):
        need_unlocked(); need_net()
        on = bool((await body(req))["on"])
        eng.store.set_network({"passthrough": on})
        iface = (eng.net_status.get("ap") or {}).get("interface") or eng.store.config.network.ap_interface
        msg = await eng.net.set_passthrough(on, iface) if iface else "saved; applies when the hotspot starts"
        eng.note(f"internet passthrough {'on' if on else 'off'}: {msg}")
        eng._passthrough_applied = (iface, on)
        return _json({"ok": True, "message": msg})

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
