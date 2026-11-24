#!/usr/bin/env python3
"""Plugin pieces that do not need Home Assistant: backoff, headers, probe, labels."""

from __future__ import annotations

import asyncio
import importlib
import sys
import types as pytypes
from pathlib import Path

import aiohttp
from aiohttp import web

ROOT = Path(__file__).resolve().parents[1]
_pkg = pytypes.ModuleType("qixu_mcp")
_pkg.__path__ = [str(ROOT / "custom_components" / "qixu_mcp")]
sys.modules["qixu_mcp"] = _pkg
connection = importlib.import_module("qixu_mcp.connection")
safety = importlib.import_module("qixu_mcp.safety")

PORT = 18792


def check(cond: bool, label: str) -> None:
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        raise SystemExit(1)


def test_backoff() -> None:
    first = [connection.backoff_seconds(1) for _ in range(200)]
    check(all(2.5 <= d <= 5 for d in first), "first retry waits 2.5-5 s")
    fourth = [connection.backoff_seconds(4) for _ in range(200)]
    check(all(20 <= d <= 40 for d in fourth), "fourth retry waits 20-40 s")
    late = [connection.backoff_seconds(50) for _ in range(200)]
    check(all(150 <= d <= 300 for d in late), "backoff capped at 300 s")
    check(len({round(d, 3) for d in late}) > 50, "retries are jittered")


def test_headers_and_redaction() -> None:
    h = connection.build_headers("tok", "", "0.2.0", "2026.11.0")
    check(h["Authorization"] == "Bearer tok", "token sent as bearer")
    check("X-Qixu-Home" not in h, "empty site ID not sent")
    check(h["X-Qixu-Plugin-Version"] == "0.2.0" and h["X-HA-Version"] == "2026.11.0", "versions sent")
    h = connection.build_headers("", "office", "0.2.0", "x")
    check("Authorization" not in h and h["X-Qixu-Home"] == "office", "site ID without token")
    check(
        connection.redact_endpoint("wss://u:p@host.example:8443/mcp/?token=secret")
        == "wss://host.example:8443/mcp/",
        "endpoint query and credentials redacted",
    )


def test_labels() -> None:
    label = safety.action_label
    check(label("da_kai_men_suo", "打开门锁", {}) == "打开门锁", "script uses friendly name")
    check(label("HassTurnOn", None, {"name": "客厅灯"}) == "打开客厅灯", "turn on label")
    check(label("HassTurnOff", None, {"name": "大门锁"}) == "打开大门锁", "lock turn off means unlock")
    check(label("HassTurnOn", None, {"name": "大门锁"}) == "锁上大门锁", "lock turn on means lock")
    check(label("assist__HassTurnOn", None, {"area": "车库"}) == "打开车库", "merged API prefix stripped")
    check(label("da_kai_men_suo", None, {}) == "da_kai_men_suo", "fallback to tool name")


async def test_probe() -> None:
    async def mcp(request: web.Request) -> web.StreamResponse:
        if request.headers.get("Authorization") != "Bearer good":
            return web.Response(status=401)
        if request.headers.get("X-Qixu-Home", "office") != "office":
            return web.Response(status=403)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for _ in ws:
            pass
        return ws

    app = web.Application()
    app.router.add_get("/mcp", mcp)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", PORT).start()
    url = f"ws://127.0.0.1:{PORT}/mcp"
    try:
        async with aiohttp.ClientSession() as session:

            async def run(token: str, home: str, endpoint: str = url):
                return await connection.probe(
                    session, endpoint, connection.build_headers(token, home, "0.2.0", "x")
                )

            check(await run("good", "office") is None, "probe ok")
            check(await run("good", "") is None, "probe ok without site ID")
            check(await run("bad", "office") == "invalid_auth", "bad token -> invalid_auth")
            check(await run("good", "elsewhere") == "invalid_auth", "wrong site -> invalid_auth")
            check(await run("good", "", f"ws://127.0.0.1:{PORT}/nope") == "cannot_connect", "404 -> cannot_connect")
            check(await run("good", "", "ws://127.0.0.1:1/mcp") == "cannot_connect", "refused -> cannot_connect")
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    test_backoff()
    test_headers_and_redaction()
    test_labels()
    asyncio.run(test_probe())
    print("ALL PASS")
