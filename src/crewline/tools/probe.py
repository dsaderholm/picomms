"""crewline-probe: hardware validation helpers (run on the appliance).

  crewline-probe inventory [--json FILE]     versions, USB topology, adapters
  crewline-probe nodes                       Bluetooth voice nodes PipeWire exposes
  crewline-probe sco                         voice (SCO/eSCO) links per adapter (hcitool)
  crewline-probe record ADDR SECS OUT.wav    record an endpoint's microphone (16 kHz mono)
  crewline-probe dtmf-scan FILE.wav          decode tones in a recording and print diagnostics
  crewline-probe click-train OUT.wav         write a click train for latency tests
  crewline-probe latency STEREO.wav          analyse a 2-channel latency recording

Nothing here changes the running system.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import time
import wave
from collections import Counter


def sh(cmd: list[str], timeout: float = 8) -> str:
    if not shutil.which(cmd[0]):
        return f"(not installed: {cmd[0]})"
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except Exception as exc:
        return f"(failed: {exc})"


def cmd_inventory(a) -> None:
    info = {
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "kernel": sh(["uname", "-r"]),
        "os": sh(["sh", "-c", ". /etc/os-release && echo $PRETTY_NAME"]),
        "cpu": sh(["sh", "-c", "grep -m1 'model name' /proc/cpuinfo || grep -m1 Model /proc/cpuinfo"]),
        "pipewire": sh(["pipewire", "--version"]),
        "wireplumber": sh(["wireplumber", "--version"]),
        "bluez": sh(["bluetoothd", "--version"]),
        "usb_topology": sh(["lsusb", "-t"]),
        "usb_bluetooth": sh(["sh", "-c", "lsusb | grep -i -E 'bluetooth|0a12:|0bda:8771|0b05:190e|2357:0604|8087:'"]),
        "btmgmt_info": sh(["btmgmt", "info"]),
        "dmesg_bluetooth": sh(["sh", "-c", "dmesg 2>/dev/null | grep -i -E 'bluetooth|btusb|firmware' | tail -40"]),
    }
    try:
        from ..bluez import BluezDbus

        async def adapters():
            b = BluezDbus(lambda: set())
            await b.start()
            ad, dev = await b.refresh()
            return [x.__dict__ for x in ad], [x.__dict__ for x in dev]
        info["adapters"], info["devices"] = asyncio.run(adapters())
    except Exception as exc:
        info["adapters"] = f"(BlueZ query failed: {exc})"
    print(json.dumps(info, indent=2, default=str))
    if a.json:
        open(a.json, "w").write(json.dumps(info, indent=2, default=str))


def cmd_nodes(a) -> None:
    from ..pwgraph import PipeWireCli

    async def go():
        snap = await PipeWireCli().snapshot()
        print(f"{'address':<19}{'dir':<8}{'profile':<20}{'codec':<7}{'state':<10}name")
        for d in (snap.sources, snap.sinks):
            for addr, n in sorted(d.items()):
                print(f"{addr:<19}{n.direction:<8}{n.profile:<20}{n.codec:<7}{n.state:<10}{n.name}")
        for lid, (s, k) in snap.links.items():
            print(f"link {lid}: {s} (mic) -> {k} (earpiece)")
    asyncio.run(go())


def cmd_sco(a) -> None:
    print(sh(["hcitool", "con"]))
    print("\n(SCO/eSCO entries above are voice links; count them per adapter while all headsets are in a call.)")


def cmd_record(a) -> None:
    from ..pwgraph import PipeWireCli

    async def go():
        cli = PipeWireCli()
        snap = await cli.snapshot()
        node = snap.sources.get(a.address.upper())
        if not node:
            sys.exit(f"no microphone node for {a.address}; run `crewline-probe nodes`")
        proc = await cli.start_tap(node.name)
        buf = bytearray()
        t0 = time.time()
        while time.time() - t0 < a.seconds:
            chunk = await proc.stdout.read(3200)
            if not chunk:
                break
            buf += chunk
        proc.kill()
        with wave.open(a.out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(bytes(buf))
        print(f"wrote {a.out}: {len(buf) / 32000:.1f} s")
    asyncio.run(go())


def cmd_dtmf_scan(a) -> None:
    from ..dtmf import DtmfDecoder

    with wave.open(a.file) as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2, "need mono 16-bit WAV"
        rate = w.getframerate()
        pcm = w.readframes(w.getnframes())
    d = DtmfDecoder(rate=rate)
    reasons: Counter = Counter()
    twists: list[float] = []

    def on_frame(info):
        reasons[info["result"]] += 1
        if info["row_dom_db"] > 6 and info["col_dom_db"] > 6:
            twists.append(info["twist_db"])
        if a.verbose:
            print(f"  t={info['t']:.2f} {info['row_hz']:.0f}/{info['col_hz']:.0f} "
                  f"dom={info['row_dom_db']:.0f}/{info['col_dom_db']:.0f}dB twist={info['twist_db']:.1f}dB "
                  f"pur={info['purity']:.2f} -> {info['result'] or 'ok'}")
    d.on_frame = on_frame
    events = []
    for i in range(0, len(pcm), 640):
        events += d.feed(pcm[i:i + 640])
    for e in events:
        if e.kind == "digit":
            print(f"{e.t:7.2f}s  DIGIT {e.digit}")
    print("\nnon-silent frames by outcome:", dict(reasons))
    if twists:
        twists.sort()
        print(f"twist of well-formed tone frames (dB, +ve = low tone stronger): "
              f"min {twists[0]:.1f}  median {twists[len(twists) // 2]:.1f}  max {twists[-1]:.1f}")
        print("If real digits are rejected as 'normal-twist'/'reverse-twist'/'impure', widen the matching "
              "limit in DtmfDecoder (or the Cell2Jack line level) and re-run.")


def main() -> None:
    ap = argparse.ArgumentParser(prog="crewline-probe", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("inventory"); p.add_argument("--json"); p.set_defaults(fn=cmd_inventory)
    p = sub.add_parser("nodes"); p.set_defaults(fn=cmd_nodes)
    p = sub.add_parser("sco"); p.set_defaults(fn=cmd_sco)
    p = sub.add_parser("record"); p.add_argument("address"); p.add_argument("seconds", type=float)
    p.add_argument("out"); p.set_defaults(fn=cmd_record)
    p = sub.add_parser("dtmf-scan"); p.add_argument("file"); p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=cmd_dtmf_scan)
    p = sub.add_parser("click-train"); p.add_argument("out"); p.add_argument("--count", type=int, default=20)
    p.add_argument("--interval", type=float, default=1.0)
    p.set_defaults(fn=lambda a: __import__("crewline.tools.latency", fromlist=["x"]).click_train_wav(a.out, a.count, a.interval))
    p = sub.add_parser("latency"); p.add_argument("file")
    p.set_defaults(fn=lambda a: print(json.dumps(__import__("crewline.tools.latency", fromlist=["x"]).analyze_stereo(a.file), indent=2)))
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
