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
    await page.click("button[type=submit]")
    await page.wait_for_selector("[data-testid=nav-overview]")


async def goto(page, base, name):
    await page.goto(f"{base}/admin#/{name}")
    await page.wait_for_timeout(250)


def tid(x):
    return f"[data-testid='{x}']"


async def test_pairing_flow_creates_person(site, browser):
    base, eng, pw_, app = site
    errors = []
    page = await new_page(browser, errors)
    await admin_login(page, base, pw_)
    await goto(page, base, "devices")
    await page.click(tid("open-pairing"))
    await page.click(tid("pair-AA:BB:CC:00:00:09"), timeout=8000)
    await page.fill(tid("pair-name"), "Casey (Stage right)")
    await page.click(tid("pair-confirm"))
    assert await until(lambda: eng.store.config.endpoint("caseystageright") is not None)
    assert eng.store.config.endpoint("caseystageright").address == "AA:BB:CC:00:00:09"
    assert not errors, errors


async def test_edit_person_groups_and_dial_codes(site, browser):
    base, eng, pw_, app = site
    errors = []
    page = await new_page(browser, errors)
    await admin_login(page, base, pw_)
    await goto(page, base, "groups")
    await page.click("button:has-text('Add group')")
    await page.fill(tid("group-name"), "Lights")
    await page.click(tid("group-save"))
    assert await until(lambda: eng.store.config.group("lights") is not None)
    # Alex: latched mic, may talk to Lights
    await goto(page, base, "people")
    await page.click(tid("edit-alex"))
    await page.select_option(tid("person-mode"), "latched")
    await page.check("input[aria-label='May talk to: Lights']")
    await page.click(tid("person-save"))
    assert await until(lambda: eng.store.config.endpoint("alex").talk_mode == "latched")
    assert "lights" in eng.store.config.endpoint("alex").talk_allowed
    # dial code 3 -> talk to Lights
    await goto(page, base, "dial")
    await page.click(tid("key-3"))
    await page.select_option(tid("key-action"), "select:lights")
    await page.click("dialog[open] button:has-text('Done')")
    await page.click(tid("dial-save"))
    assert await until(lambda: eng.store.config.dtmf.commands.get("3") == "select:lights")
    assert not errors, errors


async def test_show_mode_locks_settings_but_not_controls(site, browser):
    base, eng, pw_, app = site
    errors = []
    page = await new_page(browser, errors)
    await admin_login(page, base, pw_)
    await page.click("#show-mode-switch")
    assert await until(lambda: eng.store.config.show_mode)
    await goto(page, base, "people")
    assert await page.locator(tid("add-person")).is_disabled()
    await goto(page, base, "devices")
    assert await page.locator(tid("open-pairing")).is_disabled()
    # the pocket remote still works in show mode
    tok = app[AUTH].token_for("alex")
    rp = await new_page(browser, errors)
    await rp.goto(f"{base}/r/{tok}")
    await rp.wait_for_selector(tid("mute"))
    await rp.click(tid("mute"))
    assert await until(lambda: eng.state["alex"].muted)
    assert not errors, errors


async def test_remote_push_to_talk_call_sound_and_dashboard_ack(site, browser):
    base, eng, pw_, app = site
    errors = []
    tok = app[AUTH].token_for("alex")
    rp = await new_page(browser, errors, viewport={"width": 390, "height": 844}, has_touch=True)
    await rp.goto(f"{base}/r/{tok}")
    await rp.wait_for_selector(tid("talk"))
    assert "hold to talk" in (await rp.inner_text(tid("talk"))).lower()
    box = await rp.locator(tid("talk")).bounding_box()
    await rp.mouse.move(box["x"] + 20, box["y"] + 20)
    await rp.mouse.down()
    assert await until(lambda: eng.state["alex"].ptt_down)
    assert await until(lambda: any(l[0] == "AA:BB:CC:00:00:02" for l in eng.links_now))   # transmitting while held
    await rp.mouse.up()
    assert await until(lambda: not eng.state["alex"].ptt_down)
    await rp.click(tid("call"))
    assert await until(lambda: eng.controller.active_attention())
    dash = await new_page(browser, errors)
    await dash.goto(base + "/")
    await dash.wait_for_selector(tid("call-alert"))
    assert "alex" in (await dash.inner_text(tid("call-alert"))).lower()
    await dash.click(tid("call-alert") + " button")
    assert await until(lambda: not eng.controller.active_attention())
    assert not errors, errors


async def test_name_mention_flashes_the_right_dashboard_and_can_be_cleared(site, browser):
    base, eng, pw_, app = site
    errors = []
    dash = await new_page(browser, errors)
    await dash.goto(base + "/")
    await dash.wait_for_selector(tid("station-alex"))
    # the dashboard follows the Sound operator by default, so a mention of Sound shows up here
    assert eng.test_mention("sound")
    await dash.wait_for_selector(tid("mention-alert"), timeout=6000)
    assert await dash.locator(".glow.mention.on").count() == 1
    await dash.click(tid("mention-alert") + " button")
    await dash.wait_for_selector(tid("mention-alert"), state="detached", timeout=6000)
    assert not errors, errors


async def test_button_learn_and_mapping_via_ui(site, browser):
    base, eng, pw_, app = site
    errors = []
    page = await new_page(browser, errors)
    await admin_login(page, base, pw_)
    await goto(page, base, "people")
    await page.click(tid("edit-alex"))
    await page.click("button:has-text('Learn and assign buttons')")
    eng.on_at("AA:BB:CC:00:00:02", "AT+BLDN")                      # headset sends 'redial'
    await page.click("button:has-text('Refresh')")
    await page.wait_for_selector("text=seen 1")
    await page.select_option("select[aria-label='redial']", "attention")
    await page.click("button:has-text('Save assignments')")
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
    await goto(page, base, "diagnostics")
    await page.select_option("#dx-ep", "alex")
    await page.click(tid("diagnose"))
    await page.wait_for_selector("text=no voice nodes")
    await goto(page, base, "settings")
    async with page.expect_download() as dl:
        await page.click(tid("backup-download"))
    d = await dl.value
    assert d.suggested_filename.startswith("crewline-config-")
    assert not errors, errors


async def test_theme_choice_is_remembered_and_night_is_red_only(site, browser):
    base, eng, pw_, app = site
    errors = []
    page = await new_page(browser, errors)
    await page.goto(base + "/")
    await page.wait_for_selector(tid("station-alex"))
    assert await page.evaluate("document.documentElement.dataset.theme") == "dark"   # the booth default
    await page.evaluate("localStorage.setItem('crewline.theme','night')")
    await page.reload()
    await page.wait_for_selector(tid("station-alex"))
    assert await page.evaluate("document.documentElement.dataset.theme") == "night"
    # in night mode no text colour may carry green or blue light
    bad = await page.evaluate("""() => { const out = []; for (const el of document.querySelectorAll('body *')) {
        const m = getComputedStyle(el).color.match(/[0-9.]+/g); if (!m) continue; const [r, g, b] = m.map(Number);
        if (el.textContent.trim() && (b > r || g > r)) out.push(el.className + ':' + getComputedStyle(el).color); } return out.slice(0, 5); }""")
    assert not bad, bad
    assert not errors, errors


async def test_no_literal_null_or_undefined_anywhere(site, browser):
    base, eng, pw_, app = site
    errors = []
    page = await new_page(browser, errors)
    await admin_login(page, base, pw_)
    for t in ("overview", "setup", "devices", "people", "groups", "dial", "alerts", "captions", "network", "diagnostics", "settings", "print"):
        await goto(page, base, t)
        await page.wait_for_timeout(300)
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
