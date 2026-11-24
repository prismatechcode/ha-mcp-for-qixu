#!/usr/bin/env python3
"""Qixu endpoint for local development.

Home Assistant (qixu_mcp) dials in over WebSocket and acts as the MCP server.
This hub is the MCP client: it initializes the session, lists tools, and lets
the voice service call them over HTTP.

    python hub/qixu_hub.py --port 8791 --token <token>

    HA endpoint:  ws://<this-pc>:8791/mcp
    GET  /homes
    GET  /homes/{home}/tools
    POST /homes/{home}/call      {"name": "...", "arguments": {...}}
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import logging
import time
from typing import Any

from aiohttp import WSMsgType, web

PROTOCOL_VERSION = "2025-06-18"
REQUEST_TIMEOUT = 30

_LOGGER = logging.getLogger("qixu_hub")


class HomeLink:
    """One connected Home Assistant."""

    def __init__(self, home_id: str, ws: web.WebSocketResponse) -> None:
        self.home_id = home_id
        self.ws = ws
        self.connected_at = time.time()
        self.server_info: dict[str, Any] = {}
        self.tools: list[dict[str, Any]] = []
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}

    async def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        req_id = next(self._ids)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            msg["params"] = params
        await self.ws.send_str(json.dumps(msg, ensure_ascii=False))
        try:
            return await asyncio.wait_for(fut, REQUEST_TIMEOUT)
        finally:
            self._pending.pop(req_id, None)

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        await self.ws.send_str(json.dumps(msg))

    async def handle(self, data: dict[str, Any]) -> None:
        if "id" in data and ("result" in data or "error" in data):
            fut = self._pending.get(data["id"])
            if fut and not fut.done():
                if "error" in data:
                    fut.set_exception(RuntimeError(json.dumps(data["error"], ensure_ascii=False)))
                else:
                    fut.set_result(data["result"])
            return
        if "method" in data and "id" in data:
            # Server-to-client requests (ping, etc.): answer with an empty result.
            await self.ws.send_str(json.dumps({"jsonrpc": "2.0", "id": data["id"], "result": {}}))
            return
        if data.get("method") == "notifications/tools/list_changed":
            asyncio.create_task(self.refresh_tools())

    async def initialize(self) -> None:
        result = await self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "qixu-hub", "version": "0.1.0"},
            },
        )
        self.server_info = result.get("serverInfo") or {}
        await self.notify("notifications/initialized")
        await self.refresh_tools()

    async def refresh_tools(self) -> None:
        result = await self.request("tools/list", {})
        self.tools = result.get("tools") or []
        _LOGGER.info("home=%s tools=%d", self.home_id, len(self.tools))

    async def call(self, name: str, arguments: dict[str, Any]) -> Any:
        return await self.request("tools/call", {"name": name, "arguments": arguments})


class Hub:
    def __init__(self, token: str) -> None:
        self.token = token
        self.homes: dict[str, HomeLink] = {}

    def _authorized(self, request: web.Request) -> bool:
        if not self.token:
            return True
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer ") and auth[7:].strip() == self.token:
            return True
        return request.query.get("token") == self.token

    async def mcp_ws(self, request: web.Request) -> web.StreamResponse:
        if not self._authorized(request):
            return web.Response(status=401, text="unauthorized")
        home_id = (
            request.headers.get("X-Qixu-Home") or request.query.get("home") or "default"
        ).strip() or "default"

        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        link = HomeLink(home_id, ws)
        old = self.homes.get(home_id)
        if old is not None:
            await old.ws.close()
        self.homes[home_id] = link
        _LOGGER.info("home=%s connected from %s", home_id, request.remote)

        init_task = asyncio.create_task(link.initialize())
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        await link.handle(json.loads(msg.data))
                    except Exception as err:  # noqa: BLE001
                        _LOGGER.warning("bad message from %s: %s", home_id, err)
                elif msg.type == WSMsgType.ERROR:
                    _LOGGER.warning("home=%s ws error %s", home_id, ws.exception())
        finally:
            init_task.cancel()
            if self.homes.get(home_id) is link:
                self.homes.pop(home_id, None)
            _LOGGER.info("home=%s disconnected", home_id)
        return ws

    def _home(self, request: web.Request) -> HomeLink:
        link = self.homes.get(request.match_info["home"])
        if link is None:
            raise web.HTTPNotFound(text="home not connected")
        return link

    async def list_homes(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            raise web.HTTPUnauthorized()
        return web.json_response(
            [
                {
                    "home_id": h.home_id,
                    "server": h.server_info,
                    "tool_count": len(h.tools),
                    "connected_at": h.connected_at,
                }
                for h in self.homes.values()
            ]
        )

    async def list_tools(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            raise web.HTTPUnauthorized()
        link = self._home(request)
        if request.query.get("refresh"):
            await link.refresh_tools()
        return web.json_response(link.tools, dumps=lambda o: json.dumps(o, ensure_ascii=False))

    async def call_tool(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            raise web.HTTPUnauthorized()
        link = self._home(request)
        body = await request.json()
        name = (body.get("name") or "").strip()
        if not name:
            raise web.HTTPBadRequest(text="name required")
        try:
            result = await link.call(name, body.get("arguments") or {})
        except Exception as err:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(err)}, status=502)
        return web.json_response(
            {"ok": not result.get("isError"), "result": result},
            dumps=lambda o: json.dumps(o, ensure_ascii=False),
        )

    async def voice_home(self, request: web.Request) -> web.Response:
        """Natural language → tool plan → HA via MCP."""
        if not self._authorized(request):
            raise web.HTTPUnauthorized()
        link = self._home(request)
        body = await request.json()
        text = (body.get("text") or body.get("q") or body.get("command") or "").strip()
        from voice_agent import run_voice_turn

        try:
            payload = await run_voice_turn(link, text)
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("voice turn failed")
            return web.json_response(
                {"ok": False, "reply": f"执行失败：{err}", "executed": False, "actions": []},
                status=502,
            )
        payload["home_id"] = link.home_id
        payload["session_id"] = body.get("session_id") or ""
        return web.json_response(payload, dumps=lambda o: json.dumps(o, ensure_ascii=False))

    async def voice_default(self, request: web.Request) -> web.Response:
        """Product path: POST /v1/voice → connected home (default office)."""
        if not self._authorized(request):
            raise web.HTTPUnauthorized()
        home_id = (request.query.get("home") or "").strip()
        if home_id:
            link = self.homes.get(home_id)
            if link is None:
                raise web.HTTPNotFound(text="home not connected")
        elif not self.homes:
            return web.json_response(
                {
                    "ok": False,
                    "reply": "没有已连接的 Home Assistant。",
                    "executed": False,
                    "actions": [],
                },
                status=503,
            )
        else:
            home_id = "office" if "office" in self.homes else next(iter(self.homes))
            link = self.homes[home_id]

        body = await request.json()
        text = (body.get("text") or body.get("q") or body.get("command") or "").strip()
        from voice_agent import run_voice_turn

        try:
            payload = await run_voice_turn(link, text)
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("voice turn failed")
            return web.json_response(
                {"ok": False, "reply": f"执行失败：{err}", "executed": False, "actions": []},
                status=502,
            )
        payload["home_id"] = home_id
        payload["session_id"] = body.get("session_id") or ""
        return web.json_response(payload, dumps=lambda o: json.dumps(o, ensure_ascii=False))

    async def health(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "ok": True,
                "homes": list(self.homes.keys()),
                "mcp": "/mcp",
                "voice": "/v1/voice",
            }
        )


def build_app(token: str) -> web.Application:
    hub = Hub(token)
    app = web.Application()
    app["hub"] = hub
    app.router.add_get("/health", hub.health)
    app.router.add_get("/mcp", hub.mcp_ws)
    app.router.add_get("/homes", hub.list_homes)
    app.router.add_get("/homes/{home}/tools", hub.list_tools)
    app.router.add_post("/homes/{home}/call", hub.call_tool)
    app.router.add_post("/homes/{home}/voice", hub.voice_home)
    app.router.add_post("/v1/voice", hub.voice_default)
    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--token", default="")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(f"Qixu hub http://{args.host}:{args.port}/  mcp=/mcp  voice=/v1/voice")
    web.run_app(build_app(args.token), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
