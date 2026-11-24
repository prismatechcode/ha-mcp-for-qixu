"""Types for the Qixu MCP integration."""

from homeassistant.config_entries import ConfigEntry

from .session import SessionManager


class QixuMCPConfigEntry(ConfigEntry):
    """Config entry for Qixu MCP."""

    runtime_data: SessionManager
