#!/usr/bin/env python3
"""End to end: hub <-ws- fake HA, then drive tools over the hub's HTTP API."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import aiohttp
from aiohttp import web

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hub"))
sys.path.insert(0, str(ROOT / "tests"))

import fake_ha  # noqa: E402
from qixu_hub import build_app  # noqa: E402

TOKEN = "test-token"
PORT = 18791
BASE = f"http://127.0.0.1:{PORT}"


def check(cond: bool, label: str) -> None:
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        raise SystemExit(1)


async def main() -> None:
    runner = web.AppRunner(build_app(TOKEN))
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", PORT).start()

    ha = asyncio.create_task(fake_ha.run(f"ws://127.0.0.1:{PORT}/mcp", TOKEN, "office"))
    auth = {"Authorization": f"Bearer {TOKEN}"}

    async with aiohttp.ClientSession(headers=auth) as http:
        homes = []
        for _ in range(50):
            async with http.get(f"{BASE}/homes") as r:
                homes = await r.json()
            if homes and homes[0]["tool_count"]:
                break
            await asyncio.sleep(0.1)
        check(bool(homes) and homes[0]["home_id"] == "office", "HA connected as home 'office'")
        check(homes[0]["tool_count"] == 3, f"tools listed ({homes[0]['tool_count']})")

        async with aiohttp.ClientSession() as anon:
            async with anon.get(f"{BASE}/homes") as r:
                check(r.status == 401, "missing token rejected")

        async def call(name, args):
            async with http.post(f"{BASE}/homes/office/call", json={"name": name, "arguments": args}) as r:
                body = await r.json()
            return json.loads(body["result"]["content"][0]["text"])

        r = await call("HassTurnOn", {"name": "办公室灯"})
        check(r.get("ran") == "HassTurnOn", "L1 light runs directly")

        r = await call("da_kai_men_suo", {})
        check(r.get("requires_confirmation") is True, "door unlock held for confirmation")
        check(("da_kai_men_suo", {}) not in fake_ha.CALLS, "door not executed before confirm")

        r2 = await call("QixuConfirmAction", {"confirm_id": "wrong"})
        check(r2.get("success") is False, "wrong confirm id refused")

        r3 = await call("QixuConfirmAction", {"confirm_id": r["confirm_id"]})
        check(r3.get("ran") == "da_kai_men_suo", "door runs after confirm")

        r4 = await call("QixuConfirmAction", {"confirm_id": r["confirm_id"]})
        check(r4.get("success") is False, "confirm id is single use")

    ha.cancel()
    await runner.cleanup()
    print("ALL PASS")


if __name__ == "__main__":
    asyncio.run(main())
