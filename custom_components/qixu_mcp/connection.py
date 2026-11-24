"""Connection helpers shared by the config flow and the reconnect loop."""

from __future__ import annotations

import asyncio
import random
from urllib.parse import urlsplit, urlunsplit

import aiohttp

from .const import (
    CONNECT_TIMEOUT_SECONDS,
    HEADER_HA_VERSION,
    HEADER_HOME,
    HEADER_PLUGIN_VERSION,
    RECONNECT_MAX_SECONDS,
    RECONNECT_MIN_SECONDS,
)

AUTH_FAILED_STATUSES = (401, 403)


def build_headers(
    token: str | None, home_id: str | None, plugin_version: str, ha_version: str
) -> dict[str, str]:
    headers = {HEADER_PLUGIN_VERSION: plugin_version, HEADER_HA_VERSION: ha_version}
    if home_id:
        headers[HEADER_HOME] = home_id
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def backoff_seconds(failures: int) -> float:
    """Exponential backoff with jitter so many homes do not reconnect in lockstep."""
    ceiling = min(RECONNECT_MAX_SECONDS, RECONNECT_MIN_SECONDS * 2 ** max(failures - 1, 0))
    return random.uniform(ceiling / 2, ceiling)


def redact_endpoint(endpoint: str) -> str:
    """Drop query and credentials; some services put secrets in the URL."""
    parts = urlsplit(endpoint)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


async def probe(
    session: aiohttp.ClientSession, endpoint: str, headers: dict[str, str]
) -> str | None:
    """Open and close one connection. Return a config flow error key or None."""
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT_SECONDS):
            async with session.ws_connect(endpoint, headers=headers) as ws:
                await ws.close()
    except aiohttp.WSServerHandshakeError as err:
        if err.status in AUTH_FAILED_STATUSES:
            return "invalid_auth"
        return "cannot_connect"
    except (aiohttp.ClientError, TimeoutError, ValueError):
        return "cannot_connect"
    return None
