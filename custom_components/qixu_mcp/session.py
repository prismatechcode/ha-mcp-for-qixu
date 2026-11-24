"""MCP sessions carried over the outbound Qixu WebSocket."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
import logging

from anyio.streams.memory import MemoryObjectSendStream
from mcp.shared.message import SessionMessage

from homeassistant.util import ulid as ulid_util

_LOGGER = logging.getLogger(__name__)


@dataclass
class Session:
    """A single MCP session."""

    read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception]


class SessionManager:
    """Track open sessions so unload can close them."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    @asynccontextmanager
    async def create(self, session: Session) -> AsyncGenerator[str]:
        session_id = ulid_util.ulid_now()
        _LOGGER.debug("Creating session: %s", session_id)
        self._sessions[session_id] = session
        try:
            yield session_id
        finally:
            _LOGGER.debug("Closing session: %s", session_id)
            self._sessions.pop(session_id, None)

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def close(self) -> None:
        for session in self._sessions.values():
            session.read_stream_writer.close()
        self._sessions.clear()
