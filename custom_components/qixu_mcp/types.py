"""Types for the Qixu MCP integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from homeassistant.config_entries import ConfigEntry

from .session import SessionManager


@dataclass
class ConnectionState:
    """What the reconnect loop knows about the Qixu connection."""

    status: str = "connecting"
    plugin_version: str = ""
    last_connected: datetime | None = None
    last_disconnected: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    tool_count: int = 0


@dataclass
class QixuRuntimeData:
    sessions: SessionManager = field(default_factory=SessionManager)
    connection: ConnectionState = field(default_factory=ConnectionState)


class QixuMCPConfigEntry(ConfigEntry):
    """Config entry for Qixu MCP."""

    runtime_data: QixuRuntimeData
