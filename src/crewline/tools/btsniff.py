"""crewline-btsniff: forward HFP AT commands seen by btmon to the engine.

Runs as its own service so that a parsing problem can never touch the audio or
the engine. Needs permission to open the HCI monitor channel (CAP_NET_RAW).
Use ``--log`` to keep the raw btmon text for the validation record (T4/T5);
that file contains device addresses and AT commands only (no audio).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys

from ..buttons import BtmonParser


async def run(args) -> None:
    import aiohttp
    btmon = shutil.which("btmon")
    if not btmon:
        sys.exit("btmon not installed (package: bluez)")
    proc = await asyncio.create_subprocess_exec(
        btmon, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    conn = aiohttp.UnixConnector(path=args.socket)
    log = open(args.log, "a") if args.log else None

    async def lines():
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                return
            line = raw.decode(errors="replace").rstrip("\n")
            if log:
                log.write(line + "\n")
            yield line

    parser = BtmonParser()
    async with aiohttp.ClientSession(connector=conn) as sess:
        async for line in lines():
            for addr, at in parser.feed(line):
                try:
                    await sess.post("http://engine/button/at", json={"address": addr, "at": at})
                except Exception:
                    pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--socket", default=os.environ.get("CREWLINE_SOCKET", "/run/crewline/engine.sock"))
    ap.add_argument("--log", help="append raw btmon text here (for validation records)")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
