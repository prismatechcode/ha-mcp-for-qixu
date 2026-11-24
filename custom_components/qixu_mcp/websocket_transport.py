"""Outbound WebSocket to the Qixu endpoint; HA acts as the MCP server on it."""

from __future__ import annotations

import asyncio
import logging
import time

import aiohttp
import anyio
from mcp import types
from mcp.shared.message import SessionMessage

from homeassistant.components import conversation
from homeassistant.const import CONF_LLM_HASS_API, __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from homeassistant.util import dt as dt_util

from .connection import (
    AUTH_FAILED_STATUSES,
    backoff_seconds,
    build_headers,
    redact_endpoint,
)
from .const import (
    CONF_CONFIRM_KEYWORDS,
    CONF_ENDPOINT,
    CONF_HOME_ID,
    CONF_TOKEN,
    CONNECT_TIMEOUT_SECONDS,
    DEFAULT_CONFIRM_KEYWORDS,
    DOMAIN,
    HEARTBEAT_SECONDS,
    STABLE_CONNECTION_SECONDS,
)
from .safety import ConfirmGate, parse_keywords
from .server import create_server
from .session import Session
from .types import QixuMCPConfigEntry

_LOGGER = logging.getLogger(__name__)


class AuthFailed(Exception):
    """The Qixu service rejected the token or site ID."""


def status_entity_id(entry: QixuMCPConfigEntry) -> str:
    return f"{DOMAIN}.{entry.entry_id}_status"


def _set_status(hass: HomeAssistant, entry: QixuMCPConfigEntry, state: str) -> None:
    conn = entry.runtime_data.connection
    conn.status = state
    hass.states.async_set(
        status_entity_id(entry),
        state,
        {
            "friendly_name": f"栖序 MCP {entry.data.get(CONF_HOME_ID) or entry.title}",
            "endpoint": redact_endpoint(entry.data.get(CONF_ENDPOINT) or ""),
            "plugin_version": conn.plugin_version,
            "last_error": conn.last_error,
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
    conn = entry.runtime_data.connection
    while True:
        started = time.monotonic()
        try:
            if not await _connect_once(hass, entry, gate):
                break
            conn.last_error = None
        except asyncio.CancelledError:
            raise
        except AuthFailed as err:
            conn.last_error = str(err)
            _LOGGER.error("Qixu rejected the connection (%s); re-authentication required", err)
            _set_status(hass, entry, "auth_failed")
            entry.async_start_reauth(hass)
            return
        except Exception as err:  # noqa: BLE001
            conn.last_error = str(err) or type(err).__name__
            _LOGGER.warning("Qixu WebSocket disconnected or failed: %s", conn.last_error)

        conn.last_disconnected = dt_util.utcnow()
        if time.monotonic() - started >= STABLE_CONNECTION_SECONDS:
            conn.consecutive_failures = 0
        conn.consecutive_failures += 1
        delay = backoff_seconds(conn.consecutive_failures)
        _set_status(hass, entry, "disconnected")
        _LOGGER.info("Reconnecting to Qixu in %.0f s (attempt %d)", delay, conn.consecutive_failures)
        await asyncio.sleep(delay)


async def _connect_once(
    hass: HomeAssistant, entry: QixuMCPConfigEntry, gate: ConfirmGate
) -> bool:
    """Run one connection. Return True to reconnect."""
    conn = entry.runtime_data.connection
    endpoint = entry.data.get(CONF_ENDPOINT)
    if not endpoint:
        _LOGGER.error("No Qixu endpoint configured")
        _set_status(hass, entry, "error")
        return False

    headers = build_headers(
        entry.data.get(CONF_TOKEN),
        entry.data.get(CONF_HOME_ID),
        conn.plugin_version,
        HA_VERSION,
    )

    _set_status(hass, entry, "connecting")
    context = llm.LLMContext(
        platform=DOMAIN,
        context=None,
        language="*",
        assistant=conversation.DOMAIN,
        device_id=None,
    )
    try:
        server = await create_server(
            hass, entry.data[CONF_LLM_HASS_API], context, gate, conn.plugin_version
        )
        options = await hass.async_add_executor_job(server.create_initialization_options)
    except Exception as err:  # noqa: BLE001
        _LOGGER.exception("Failed to create MCP server: %s", err)
        _set_status(hass, entry, "error")
        raise

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    reconnect = True
    async with entry.runtime_data.sessions.create(Session(read_stream_writer)):
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=CONNECT_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as client_session:
            _LOGGER.info("Dialing Qixu endpoint %s", redact_endpoint(endpoint))
            try:
                ws_response = await client_session.ws_connect(endpoint, headers=headers)
            except aiohttp.WSServerHandshakeError as err:
                if err.status in AUTH_FAILED_STATUSES:
                    raise AuthFailed(f"HTTP {err.status}") from err
                raise
            async with ws_response as ws:
                _LOGGER.info("Connected to Qixu endpoint %s", redact_endpoint(endpoint))
                conn.last_connected = dt_util.utcnow()
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
