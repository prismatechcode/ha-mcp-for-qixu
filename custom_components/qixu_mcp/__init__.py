"""Qixu MCP: Home Assistant dials out to the Qixu voice service over MCP."""

from __future__ import annotations

import logging

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import DOMAIN
from .types import QixuMCPConfigEntry, QixuRuntimeData

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    return True


async def async_setup_entry(hass: HomeAssistant, entry: QixuMCPConfigEntry) -> bool:
    entry.runtime_data = QixuRuntimeData()
    integration = await async_get_integration(hass, DOMAIN)
    entry.runtime_data.connection.plugin_version = str(integration.version or "")

    async def _start(_event: Event | None = None) -> None:
        from . import websocket_transport

        try:
            await websocket_transport.async_setup_entry(hass, entry)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Qixu MCP start failed: %s", err)
            hass.states.async_set(f"{DOMAIN}.{entry.entry_id}_status", "error")

    # Do not wrap listen_once with entry.async_on_unload —
    # that listener is one-shot and cannot be removed.
    if hass.is_running:
        await _start()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _start)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: QixuMCPConfigEntry) -> bool:
    entry.runtime_data.sessions.close()
    hass.states.async_remove(f"{DOMAIN}.{entry.entry_id}_status")
    return True
