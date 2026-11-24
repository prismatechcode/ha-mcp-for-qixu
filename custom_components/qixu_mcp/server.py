"""MCP server exposing Home Assistant LLM tools to the Qixu voice service."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import json
import logging
from typing import Any, cast

from mcp import types
from mcp.server import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from pydantic import AnyUrl
import voluptuous as vol
from voluptuous_openapi import convert

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm

from .const import CONFIRM_TOOL_NAME, CONFIRM_TTL_SECONDS, STATELESS_LLM_API
from .safety import ConfirmGate

_LOGGER = logging.getLogger(__name__)

SNAPSHOT_RESOURCE_URI = "homeassistant://assist/context-snapshot"
SNAPSHOT_RESOURCE_URL = AnyUrl(SNAPSHOT_RESOURCE_URI)
SNAPSHOT_RESOURCE_MIME_TYPE = "text/plain"
LIVE_CONTEXT_TOOL_NAME = "homeassistant__GetLiveContext"


def _has_live_context_tool(llm_api: llm.APIInstance) -> bool:
    return any(tool.name == LIVE_CONTEXT_TOOL_NAME for tool in llm_api.tools)


def _format_tool(
    tool: llm.Tool, custom_serializer: Callable[[Any], Any] | None
) -> types.Tool:
    input_schema = convert(tool.parameters, custom_serializer=custom_serializer)
    return types.Tool(
        name=tool.name,
        description=tool.description or "",
        inputSchema={
            "type": "object",
            "properties": input_schema["properties"],
        },
    )


def _text(payload: Any) -> list[types.TextContent]:
    if not isinstance(payload, str):
        payload = json.dumps(payload, ensure_ascii=False)
    return [types.TextContent(type="text", text=payload)]


async def create_server(
    hass: HomeAssistant,
    llm_api_id: str | list[str],
    llm_context: llm.LLMContext,
    gate: ConfirmGate,
) -> Server:
    """Create the MCP server for one Qixu connection."""
    if llm_api_id == STATELESS_LLM_API:
        llm_api_id = llm.LLM_API_ASSIST

    server = Server[Any]("qixu-home-assistant")

    async def get_api_instance() -> llm.APIInstance:
        return await llm.async_get_api(hass, llm_api_id, llm_context)

    async def run_ha_tool(name: str, arguments: dict[str, Any]) -> Any:
        llm_api = await get_api_instance()
        tool_input = llm.ToolInput(tool_name=name, tool_args=arguments)
        _LOGGER.debug("Tool call: %s(%s)", name, arguments)
        try:
            return await llm_api.async_call_tool(tool_input)
        except (HomeAssistantError, vol.Invalid) as err:
            raise HomeAssistantError(f"Error calling tool: {err}") from err

    @server.list_prompts()  # type: ignore[no-untyped-call,untyped-decorator]
    async def handle_list_prompts() -> list[types.Prompt]:
        llm_api = await get_api_instance()
        return [
            types.Prompt(
                name=llm_api.api.name,
                description=f"Default prompt for Home Assistant {llm_api.api.name} API",
            )
        ]

    @server.get_prompt()  # type: ignore[no-untyped-call,untyped-decorator]
    async def handle_get_prompt(
        name: str, arguments: dict[str, str] | None
    ) -> types.GetPromptResult:
        llm_api = await get_api_instance()
        if name != llm_api.api.name:
            raise ValueError(f"Unknown prompt: {name}")
        return types.GetPromptResult(
            description=f"Default prompt for Home Assistant {llm_api.api.name} API",
            messages=[
                types.PromptMessage(
                    role="assistant",
                    content=types.TextContent(type="text", text=llm_api.api_prompt),
                )
            ],
        )

    @server.list_resources()  # type: ignore[no-untyped-call,untyped-decorator]
    async def handle_list_resources() -> list[types.Resource]:
        llm_api = await get_api_instance()
        if not _has_live_context_tool(llm_api):
            return []
        return [
            types.Resource(
                uri=SNAPSHOT_RESOURCE_URL,
                name="assist_context_snapshot",
                title="Assist context snapshot",
                description=(
                    "A snapshot of the current Assist context, matching the"
                    " existing homeassistant__GetLiveContext tool output."
                ),
                mimeType=SNAPSHOT_RESOURCE_MIME_TYPE,
            )
        ]

    @server.read_resource()  # type: ignore[no-untyped-call,untyped-decorator]
    async def handle_read_resource(uri: AnyUrl) -> Sequence[ReadResourceContents]:
        if str(uri) != SNAPSHOT_RESOURCE_URI:
            raise ValueError(f"Unknown resource: {uri}")
        llm_api = await get_api_instance()
        if not _has_live_context_tool(llm_api):
            raise ValueError(f"Unknown resource: {uri}")
        tool_response = await llm_api.async_call_tool(
            llm.ToolInput(tool_name=LIVE_CONTEXT_TOOL_NAME, tool_args={})
        )
        if not tool_response.get("success"):
            raise HomeAssistantError(cast(str, tool_response["error"]))
        return [
            ReadResourceContents(
                content=cast(str, tool_response["result"]),
                mime_type=SNAPSHOT_RESOURCE_MIME_TYPE,
            )
        ]

    @server.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
    async def list_tools() -> list[types.Tool]:
        llm_api = await get_api_instance()
        tools = [_format_tool(tool, llm_api.custom_serializer) for tool in llm_api.tools]
        tools.append(
            types.Tool(
                name=CONFIRM_TOOL_NAME,
                description=(
                    "执行一个等待确认的安防动作（开锁、出车等）。"
                    "只有在用户明确说了「确认」之后才调用，confirm_id 来自上一次工具返回。"
                    f"确认在 {CONFIRM_TTL_SECONDS} 秒内有效。"
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "confirm_id": {
                            "type": "string",
                            "description": "上一次工具返回的确认编号",
                        }
                    },
                    "required": ["confirm_id"],
                },
            )
        )
        return tools

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict) -> Sequence[types.TextContent]:
        arguments = arguments or {}

        if name == CONFIRM_TOOL_NAME:
            pending = gate.take(str(arguments.get("confirm_id") or ""))
            if pending is None:
                return _text(
                    {
                        "success": False,
                        "speech": "确认已过期或编号不对，请重新说一次指令。",
                    }
                )
            _LOGGER.info("Confirmed L3 action %s %s", pending.tool_name, pending.arguments)
            return _text(await run_ha_tool(pending.tool_name, pending.arguments))

        llm_api = await get_api_instance()
        tool = next((t for t in llm_api.tools if t.name == name), None)
        description = (tool.description or "") if tool else ""
        if name.startswith("script__"):
            state = hass.states.get(f"script.{name.removeprefix('script__')}")
            if state is not None:
                description = " ".join(
                    filter(None, [state.attributes.get("friendly_name"), description])
                )
        keyword = gate.matched_keyword(name, description, arguments)
        if keyword:
            label = description or name
            confirm_id = gate.hold(name, arguments, label)
            _LOGGER.info("Held L3 action %s (%s) as %s", name, keyword, confirm_id)
            return _text(
                {
                    "success": False,
                    "requires_confirmation": True,
                    "confirm_id": confirm_id,
                    "action": label,
                    "speech": f"这是安防动作：{label}。请确认后再执行。",
                    "next": (
                        f"先问用户是否确认；用户说确认后调用 {CONFIRM_TOOL_NAME}，"
                        f"confirm_id={confirm_id}，{CONFIRM_TTL_SECONDS} 秒内有效。"
                    ),
                }
            )

        return _text(await run_ha_tool(name, arguments))

    return server
