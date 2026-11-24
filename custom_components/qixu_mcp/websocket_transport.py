"""Outbound WebSocket to the Qixu endpoint; HA acts as the MCP server on it."""

from __future__ import annotations

import asyncio
import logging

import aiohttp
import anyio
from mcp import types
from mcp.shared.message import SessionMessage

from homeassistant.components import conversation
from homeassistant.const import CONF_LLM_HASS_API
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from .const import (
    CONF_CONFIRM_KEYWORDS,
    CONF_ENDPOINT,
    CONF_HOME_ID,
    CONF_TOKEN,
    DEFAULT_CONFIRM_KEYWORDS,
    DOMAIN,
    HEARTBEAT_SECONDS,
    RECONNECT_SECONDS,
)
from .safety import ConfirmGate, parse_keywords
from .server import create_server
from .session import Session
from .types import QixuMCPConfigEntry

_LOGGER = logging.getLogger(__name__)


def status_entity_id(entry: QixuMCPConfigEntry) -> str:
    return f"{DOMAIN}.{entry.entry_id}_status"


def _set_status(hass: HomeAssistant, entry: QixuMCPConfigEntry, state: str) -> None:
    hass.states.async_set(
        status_entity_id(entry),
        state,
        {
            "friendly_name": f"栖序 MCP {entry.data.get(CONF_HOME_ID) or entry.title}",
            "endpoint": entry.data.get(CONF_ENDPOINT),
        },
    )


async def async_setup_entry(hass: HomeAssistant, entry: QixuMCPConfigEntry) -> None:
    """Start the reconnect loop for this entry."""
    gate = ConfirmGate(
        parse_keywords(entry.data.get(CONF_CONFIRM_KEYWORDS, DEFAULT_CONFIRM_KEYWORDS))
    )
    entry.async_create_background_task(
        hass, _connect_loop(hass, entry, gate), f"{DOMAIN}_{entry.entry_id}"
    )


async def _connect_loop(
    hass: HomeAssistant, entry: QixuMCPConfigEntry, gate: ConfirmGate
) -> None:
    while True:
        try:
            if not await _connect_once(hass, entry, gate):
                break
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Qixu WebSocket disconnected or failed: %s", err)
        _set_status(hass, entry, "disconnected")
        await asyncio.sleep(RECONNECT_SECONDS)


async def _connect_once(
    hass: HomeAssistant, entry: QixuMCPConfigEntry, gate: ConfirmGate
) -> bool:
    """Run one connection. Return True to reconnect."""
    endpoint = entry.data.get(CONF_ENDPOINT)
    if not endpoint:
        _LOGGER.error("No Qixu endpoint configured")
        _set_status(hass, entry, "error")
        return False

    headers = {"X-Qixu-Home": entry.data.get(CONF_HOME_ID) or ""}
    token = entry.data.get(CONF_TOKEN)
    if token:
        headers["Authorization"] = f"Bearer {token}"

    _set_status(hass, entry, "connecting")
    context = llm.LLMContext(
        platform=DOMAIN,
        context=None,
        language="*",
        assistant=conversation.DOMAIN,
        device_id=None,
    )
    try:
        server = await create_server(hass, entry.data[CONF_LLM_HASS_API], context, gate)
        options = await hass.async_add_executor_job(server.create_initialization_options)
    except Exception as err:  # noqa: BLE001
        _LOGGER.exception("Failed to create MCP server: %s", err)
        _set_status(hass, entry, "error")
        raise

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    reconnect = True
    session_manager = entry.runtime_data
    async with session_manager.create(Session(read_stream_writer)):
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=15)
        async with aiohttp.ClientSession(timeout=timeout) as client_session:
            _LOGGER.info("Dialing Qixu endpoint %s", endpoint)
            async with client_session.ws_connect(endpoint, headers=headers) as ws:
                _LOGGER.info("Connected to Qixu endpoint %s", endpoint)
                _set_status(hass, entry, "connected")

                async def ws_reader() -> None:
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                message = types.JSONRPCMessage.model_validate(msg.json())
                            except Exception as err:  # noqa: BLE001
                                _LOGGER.error("Invalid message from Qixu: %s", err)
                                continue
                            await read_stream_writer.send(SessionMessage(message))
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            _LOGGER.error("Qixu WebSocket error: %s", ws.exception())
                    _LOGGER.info("Qixu WebSocket closed")
                    tg.cancel_scope.cancel()

                async def ws_writer() -> None:
                    nonlocal reconnect
                    async for session_message in write_stream_reader:
                        await ws.send_str(
                            session_message.message.model_dump_json(
                                by_alias=True, exclude_none=True
                            )
                        )
                    reconnect = False
                    await ws.close()

                async def heartbeat() -> None:
                    while True:
                        await asyncio.sleep(HEARTBEAT_SECONDS)
                        try:
                            await ws.ping()
                        except Exception as err:  # noqa: BLE001
                            _LOGGER.info("Qixu heartbeat failed: %s", err)
                            tg.cancel_scope.cancel()
                            return

                async with anyio.create_task_group() as tg:
                    tg.start_soon(ws_reader)
                    tg.start_soon(ws_writer)
                    tg.start_soon(heartbeat)
                    await server.run(read_stream, write_stream, options)
    return reconnect
