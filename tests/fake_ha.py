#!/usr/bin/env python3
"""Stand-in for Home Assistant: dials the hub like qixu_mcp and serves two tools.

Uses the same mcp==1.26 server API and the real safety.ConfirmGate, so the
hub, the JSON-RPC framing and the L3 confirmation flow are exercised without HA.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import types as pytypes
from pathlib import Path

import aiohttp
import anyio
from mcp import types
from mcp.server import Server
from mcp.shared.message import SessionMessage

ROOT = Path(__file__).resolve().parents[1]

# Register the integration folder as a package without running __init__.py,
# which needs Home Assistant. safety.py and const.py are plain Python.
_pkg = pytypes.ModuleType("qixu_mcp")
_pkg.__path__ = [str(ROOT / "custom_components" / "qixu_mcp")]
sys.modules["qixu_mcp"] = _pkg
safety = importlib.import_module("qixu_mcp.safety")

TOOLS = {
    "HassTurnOn": "Turns on/opens a device or entity",
    "da_kai_men_suo": "打开门锁",
}
CALLS: list[tuple[str, dict]] = []


def build_server(gate) -> Server:
    server = Server("fake-ha")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        tools = [
            types.Tool(name=n, description=d, inputSchema={"type": "object", "properties": {"name": {"type": "string"}}})
            for n, d in TOOLS.items()
        ]
        tools.append(
            types.Tool(
                name="QixuConfirmAction",
                description="confirm",
                inputSchema={"type": "object", "properties": {"confirm_id": {"type": "string"}}},
            )
        )
        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        arguments = arguments or {}
        if name == "QixuConfirmAction":
            pending = gate.take(str(arguments.get("confirm_id") or ""))
            if pending is None:
                return [types.TextContent(type="text", text=json.dumps({"success": False, "speech": "确认已过期"}, ensure_ascii=False))]
            CALLS.append((pending.tool_name, pending.arguments))
            return [types.TextContent(type="text", text=json.dumps({"success": True, "ran": pending.tool_name}))]
        keyword = gate.matched_keyword(name, TOOLS.get(name, ""), arguments)
        if keyword:
            cid = gate.hold(name, arguments, TOOLS.get(name, name))
            return [types.TextContent(type="text", text=json.dumps({"requires_confirmation": True, "confirm_id": cid}, ensure_ascii=False))]
        CALLS.append((name, arguments))
        return [types.TextContent(type="text", text=json.dumps({"success": True, "ran": name, "args": arguments}, ensure_ascii=False))]

    return server


async def run(endpoint: str, token: str, home: str) -> None:
    gate = safety.ConfirmGate(safety.parse_keywords("门锁,开锁,出车"))
    server = build_server(gate)
    options = server.create_initialization_options()
    read_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_reader = anyio.create_memory_object_stream(0)
    headers = {"Authorization": f"Bearer {token}", "X-Qixu-Home": home}
    async with aiohttp.ClientSession() as http:
        async with http.ws_connect(endpoint, headers=headers) as ws:

            async def reader():
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await read_writer.send(SessionMessage(types.JSONRPCMessage.model_validate(msg.json())))
                tg.cancel_scope.cancel()

            async def writer():
                async for sm in write_reader:
                    await ws.send_str(sm.message.model_dump_json(by_alias=True, exclude_none=True))

            async with anyio.create_task_group() as tg:
                tg.start_soon(reader)
                tg.start_soon(writer)
                await server.run(read_stream, write_stream, options)


if __name__ == "__main__":
    asyncio.run(run(sys.argv[1], sys.argv[2], sys.argv[3]))
