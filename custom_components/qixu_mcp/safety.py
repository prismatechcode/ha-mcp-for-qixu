"""Hold L3 actions (unlock, dispatch) until the user confirms."""

from __future__ import annotations

from dataclasses import dataclass
import json
import secrets
import time
from typing import Any

from .const import CONFIRM_TTL_SECONDS


def parse_keywords(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts = raw.replace("，", ",").replace("、", ",").split(",")
    return [p.strip() for p in parts if p.strip()]


@dataclass
class PendingAction:
    tool_name: str
    arguments: dict[str, Any]
    label: str
    expires_at: float


class ConfirmGate:
    """Per config entry store of actions waiting for confirmation."""

    def __init__(self, keywords: list[str], ttl: int = CONFIRM_TTL_SECONDS) -> None:
        self._keywords = keywords
        self._ttl = ttl
        self._pending: dict[str, PendingAction] = {}

    def matched_keyword(
        self, tool_name: str, tool_description: str, arguments: dict[str, Any]
    ) -> str | None:
        haystack = " ".join(
            [tool_name, tool_description, json.dumps(arguments or {}, ensure_ascii=False)]
        )
        for keyword in self._keywords:
            if keyword in haystack:
                return keyword
        return None

    def hold(self, tool_name: str, arguments: dict[str, Any], label: str) -> str:
        self._expire()
        confirm_id = secrets.token_hex(4)
        self._pending[confirm_id] = PendingAction(
            tool_name=tool_name,
            arguments=dict(arguments or {}),
            label=label,
            expires_at=time.monotonic() + self._ttl,
        )
        return confirm_id

    def take(self, confirm_id: str) -> PendingAction | None:
        self._expire()
        return self._pending.pop(confirm_id, None)

    def _expire(self) -> None:
        now = time.monotonic()
        for key in [k for k, v in self._pending.items() if v.expires_at < now]:
            self._pending.pop(key, None)
