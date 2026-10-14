"""Browser end-to-end tests (headless Chromium) against the simulated backends.

They drive the real HTML/JS of the dashboard, pocket remote and admin pages.
Skipped automatically when Playwright or a Chromium binary is not available.
Like all sim tests, they say nothing about real Bluetooth hardware.
"""
import asyncio
import glob
import os
from argparse import Namespace

import pytest

pw = pytest.importorskip("playwright.async_api")
from aiohttp import web

from crewline.bluez import SimBluetooth
from crewline.engine import Engine
from crewline.engine_api import serve_unix
from crewline.sim import SimDevice, SimGraph
from crewline.web.app import AUTH, make_app


def chromium_path():
    p = os.environ.get("CREWLINE_TEST_CHROMIUM")
    if p:
        return p
    for pat in ("/opt/pw-browsers/chromium-*/chrome-linux/chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
                "/usr/bin/google-chrome"):
        m = sorted(glob.glob(pat))
        if m:
            return m[-1]
    return None


pytestmark = pytest.mark.skipif(chromium_path() is None, reason="no Chromium available")


async def until(pred, timeout=6.0):
    t = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - t < timeout:
        if pred():
            return True
        await asyncio.sleep(0.05)
    return False


@pytest.fixture
async def site(tmp_path):
    g = SimGraph(); bt = SimBluetooth(g)
    g.add_device(SimDevice("AA:BB:CC:00:00:01", "Rotary"))
    g.add_device(SimDevice("AA:BB:CC:00:00:02", "Alex's headset"))
    bt.discovered["AA:BB:CC:00:00:09"] = "JLab GO Work 9"
    eng = Engine(tmp_path / "state", g, bt, simulated=True)
    await eng.start()
    s = eng.store
    s.upsert_endpoint(s.config.endpoint("sound").__dict__ | {"address": "AA:BB:CC:00:00:01"})
    s.upsert_endpoint({"id": "alex", "name": "Alex", "address": "AA:BB:CC:00:00:02", "listen": ["tech"], "talk": ["tech"],
                       "listen_allowed": ["tech", "stage"], "talk_allowed": ["tech", "stage"], "talk_mode": "ptt"})
    sock = str(tmp_path / "e.sock")
    runner = await serve_unix(eng, sock)
    cfg = tmp_path / "web.toml"; cfg.write_text("")
    app = make_app(Namespace(socket=sock, state_dir=str(tmp_path / "state"), config=str(cfg)))
    wr = web.AppRunner(app, shutdown_timeout=1.0)
    await wr.setup()
    ws = web.TCPSite(wr, "127.0.0.1", 0)
    await ws.start()
    port = ws._server.sockets[0].getsockname()[1]
    pwtext = (tmp_path / "state" / "FIRST-RUN-ADMIN-PASSWORD.txt").read_text().split("\n")[1]
    await until(lambda: eng.state["alex"].audio_up)
    yield f"http://127.0.0.1:{port}", eng, pwtext, app
    await wr.cleanup()
    await runner.cleanup()
    await eng.stop()


@pytest.fixture
async def browser():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=chromium_path(), args=["--no-sandbox"])
        yield b
        await b.close()


async def new_page(browser, errors, **kw):
    ctx = await browser.new_context(**kw)
    page = await ctx.new_page()
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    return page


async def admin_login(page, base, pw):
    await page.goto(base + "/admin")
    await page.fill("#pw", pw)
    await page.click("#login-form button")
    await page.wait_for_selector("#tabs button")


async def tab(page, name):
    await page.click(f"#tabs button:has-text('{name}')")
    await page.wait_for_timeout(300)


async def test_pairing_flow_creates_endpoint(site, browser):
    base, eng, pw_, app = site
    errors = []
    page = await new_page(browser, errors)
    await admin_login(page, base, pw_)
    await tab(page, "Devices")
    await page.click("text=Open pairing window")
    await page.wait_for_selector("text=JLab GO Work 9", timeout=8000)
    await page.click("button:has-text('Pair as')")
    await page.fill("#pn", "Casey (Stage right)")
    await page.click("#dlg-body button:has-text('Pair')")
    assert await until(lambda: eng.store.config.endpoint("caseystageright") is not None)
    assert eng.store.config.endpoint("caseystageright").address == "AA:BB:CC:00:00:09"
    assert not errors, errors


async def test_edit_endpoint_groups_and_dial_codes(site, browser):
    base, eng, pw_, app = site
    errors = []
    page = await new_page(browser, errors)
    await admin_login(page, base, pw_)
    # add a group
    await tab(page, "Groups")
    await page.click("button:has-text('Add group')")
    await page.fill("#dlg-body input >> nth=0", "Lights")
    await page.click("#dlg-body button:has-text('Save')")
    assert await until(lambda: eng.store.config.group("lights") is not None)
    # edit Alex: latched mode, may talk to lights
    await tab(page, "Endpoints")
    row = page.locator("tr", has_text="Alex")
    await row.locator("button:has-text('Edit')").click()
    await page.select_option("#e-mode", "latched")
    await page.locator(".checks[data-name='talk_allowed'] input[value='lights']").check()
    await page.click("#dlg-body button:has-text('Save')")
    assert await until(lambda: eng.store.config.endpoint("alex").talk_mode == "latched")
    assert "lights" in eng.store.config.endpoint("alex").talk_allowed
    # dial code 3 -> talk to lights
    await tab(page, "Dial codes")
    await page.select_option("#dt-3", "select:lights")
    await page.fill("#dt-ac", "30")
    await page.click("button:has-text('Save dial codes')")
    assert await until(lambda: eng.store.config.dtmf.commands.get("3") == "select:lights")
    assert eng.store.config.dtmf.allcall_timeout_s == 30
    assert not errors, errors


async def test_show_mode_locks_configuration_in_the_ui_but_not_controls(site, browser):
    base, eng, pw_, app = site
    errors = []
    page = await new_page(browser, errors)
    await admin_login(page, base, pw_)
    await page.click("#show-toggle")
    assert await until(lambda: eng.store.config.show_mode)
    await tab(page, "Endpoints")
    await page.wait_for_selector("text=Show mode is on")
    assert await page.locator("button:has-text('Add endpoint without a device')").is_disabled()
    await tab(page, "Devices")
    assert await page.locator("button:has-text('Open pairing window')").is_disabled()
    # reconnect stays available
    assert await page.locator("button:has-text('Reconnect')").first.is_enabled()
    # the pocket remote still works in show mode
    tok = app[AUTH].token_for("alex")
    rp = await new_page(browser, errors)
    await rp.goto(f"{base}/r/{tok}")
    await rp.wait_for_selector("#mute")
    await rp.click("#mute")
    assert await until(lambda: eng.state["alex"].muted)
    assert not errors, errors


async def test_remote_push_to_talk_and_call_sound_and_dashboard_ack(site, browser):
    base, eng, pw_, app = site
    errors = []
    tok = app[AUTH].token_for("alex")
    rp = await new_page(browser, errors, viewport={"width": 390, "height": 844}, has_touch=True)
    await rp.goto(f"{base}/r/{tok}")
    await rp.wait_for_selector("#talk")
    assert (await rp.inner_text("#talk")).startswith("HOLD TO TALK")
    box = await rp.locator("#talk").bounding_box()
    await rp.mouse.move(box["x"] + 20, box["y"] + 20)
    await rp.mouse.down()
    assert await until(lambda: eng.state["alex"].ptt_down)
    assert any(l[0] == "AA:BB:CC:00:00:02" for l in eng.links_now)     # transmitting while held
    await rp.mouse.up()
    assert await until(lambda: not eng.state["alex"].ptt_down)
    # Call Sound -> dashboard banner -> acknowledge
    await rp.click("#call")
    assert await until(lambda: eng.controller.active_attention())
    dash = await new_page(browser, errors)
    await dash.goto(base + "/")
    await dash.wait_for_selector(".alert")
    assert "CALLING SOUND" in (await dash.inner_text(".alert")).upper()
    await dash.click(".alert button")
    assert await until(lambda: not eng.controller.active_attention())
    assert not errors, errors


async def test_button_learn_and_mapping_via_ui(site, browser):
    base, eng, pw_, app = site
    errors = []
    page = await new_page(browser, errors)
    await admin_login(page, base, pw_)
    eng.on_at("AA:BB:CC:00:00:02", "AT+BLDN")                      # headset sends 'redial'
    await tab(page, "Endpoints")
    await page.locator("tr", has_text="Alex").locator("button:has-text('Buttons')").click()
    await page.wait_for_selector("text=seen 1")
    await page.select_option("#dlg-body select[data-ev='redial']", "attention")
    await page.click("#dlg-body button:has-text('Save mapping')")
    assert await until(lambda: eng.store.config.endpoint("alex").buttons.get("redial") == "attention")
    eng.on_at("AA:BB:CC:00:00:02", "AT+BLDN")
    assert await until(lambda: eng.controller.active_attention())
    assert not errors, errors


async def test_diagnostics_and_backup_download(site, browser):
    base, eng, pw_, app = site
    errors = []
    page = await new_page(browser, errors)
    await admin_login(page, base, pw_)
    eng.graph.devices["AA:BB:CC:00:00:02"].sco_ok = False           # paired, but no voice link
    eng.kick()
    await until(lambda: not eng.state["alex"].audio_up)
    await tab(page, "Diagnostics")
    await page.select_option("#dx-ep", "alex")
    await page.click("button:has-text('Diagnose')")
    await page.wait_for_selector("text=no voice nodes")
    await tab(page, "Backup")
    async with page.expect_download() as dl:
        await page.click("a:has-text('Download backup')")
    d = await dl.value
    assert d.suggested_filename.startswith("crewline-config-")
    assert not errors, errors


async def test_no_literal_null_or_undefined_anywhere(site, browser):
    base, eng, pw_, app = site
    errors = []
    page = await new_page(browser, errors)
    await admin_login(page, base, pw_)
    for t in ("Status", "Devices", "Endpoints", "Groups", "Dial codes", "Captions", "Diagnostics", "Backup"):
        await tab(page, t)
        txt = await page.inner_text("body")
        for bad in ("null", "undefined", "NaN", "[object"):
            assert bad not in txt, (t, bad)
    for url in ("/", "/help", f"/r/{app[AUTH].token_for('alex')}"):
        await page.goto(base + url)
        await page.wait_for_timeout(500)
        txt = await page.inner_text("body")
        for bad in ("null", "undefined", "NaN", "[object"):
            assert bad not in txt, (url, bad)
    assert not errors, errors
