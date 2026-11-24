"""Diagnostics download for Qixu MCP (Settings → Devices & services → ⋮ → Download diagnostics)."""

from __future__ import annotations

from typing import Any

from homeassistant.components import conversation
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_LLM_HASS_API, __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from .connection import redact_endpoint
from .const import CONF_ENDPOINT, CONF_TOKEN, DOMAIN, STATELESS_LLM_API
from .types import QixuMCPConfigEntry

TO_REDACT = {CONF_TOKEN}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: QixuMCPConfigEntry
) -> dict[str, Any]:
    data = async_redact_data(dict(entry.data), TO_REDACT)
    data[CONF_ENDPOINT] = redact_endpoint(entry.data.get(CONF_ENDPOINT) or "")

    conn = entry.runtime_data.connection
    api_ids = entry.data.get(CONF_LLM_HASS_API) or []
    if api_ids == STATELESS_LLM_API:
        api_ids = llm.LLM_API_ASSIST
    tools: list[str] | str
    try:
        api = await llm.async_get_api(
            hass,
            api_ids,
            llm.LLMContext(
                platform=DOMAIN,
                context=None,
                language="*",
                assistant=conversation.DOMAIN,
                device_id=None,
            ),
        )
        tools = sorted(tool.name for tool in api.tools)
    except Exception as err:  # noqa: BLE001
        tools = f"unavailable: {err}"

    return {
        "entry": data,
        "versions": {"plugin": conn.plugin_version, "home_assistant": HA_VERSION},
        "connection": {
            "status": conn.status,
            "last_connected": conn.last_connected,
            "last_disconnected": conn.last_disconnected,
            "last_error": conn.last_error,
            "consecutive_failures": conn.consecutive_failures,
        },
        "tools": tools,
    }
