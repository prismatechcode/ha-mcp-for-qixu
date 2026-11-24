"""Config flow for Qixu MCP."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_LLM_HASS_API
from homeassistant.helpers import llm
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_CONFIRM_KEYWORDS,
    CONF_ENDPOINT,
    CONF_HOME_ID,
    CONF_TOKEN,
    DEFAULT_CONFIRM_KEYWORDS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class QixuMCPConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Qixu MCP."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        llm_apis = {api.id: api.name for api in llm.async_get_apis(self.hass)}

        if user_input is not None:
            endpoint = (user_input.get(CONF_ENDPOINT) or "").strip()
            if not endpoint.startswith(("ws://", "wss://")):
                errors[CONF_ENDPOINT] = "invalid_endpoint"
            elif not user_input.get(CONF_LLM_HASS_API):
                errors[CONF_LLM_HASS_API] = "llm_api_required"
            else:
                user_input[CONF_ENDPOINT] = endpoint
                home_id = (user_input.get(CONF_HOME_ID) or "").strip()
                await self.async_set_unique_id(f"{endpoint}|{home_id}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=home_id or endpoint,
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ENDPOINT): TextSelector(),
                    vol.Optional(CONF_TOKEN, default=""): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(CONF_HOME_ID, default=""): TextSelector(),
                    vol.Optional(
                        CONF_LLM_HASS_API, default=[llm.LLM_API_ASSIST]
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(label=name, value=api_id)
                                for api_id, name in llm_apis.items()
                            ],
                            multiple=True,
                        )
                    ),
                    vol.Optional(
                        CONF_CONFIRM_KEYWORDS, default=DEFAULT_CONFIRM_KEYWORDS
                    ): TextSelector(),
                }
            ),
            errors=errors,
        )
