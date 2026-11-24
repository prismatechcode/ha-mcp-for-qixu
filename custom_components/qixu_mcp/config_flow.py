"""Config flow for Qixu MCP."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_LLM_HASS_API, __version__ as HA_VERSION
from homeassistant.helpers import llm
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.loader import async_get_integration

from .connection import build_headers, probe, redact_endpoint
from .const import (
    CONF_CONFIRM_KEYWORDS,
    CONF_ENDPOINT,
    CONF_HOME_ID,
    CONF_TOKEN,
    DEFAULT_CONFIRM_KEYWORDS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


class QixuMCPConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Qixu MCP."""

    VERSION = 1

    async def _probe(self, endpoint: str, token: str | None, home_id: str | None) -> str | None:
        integration = await async_get_integration(self.hass, DOMAIN)
        headers = build_headers(token, home_id, str(integration.version or ""), HA_VERSION)
        return await probe(async_get_clientsession(self.hass), endpoint, headers)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        llm_apis = {api.id: api.name for api in llm.async_get_apis(self.hass)}

        if user_input is not None:
            endpoint = (user_input.get(CONF_ENDPOINT) or "").strip()
            token = (user_input.get(CONF_TOKEN) or "").strip()
            home_id = (user_input.get(CONF_HOME_ID) or "").strip()
            if not endpoint.startswith(("ws://", "wss://")):
                errors[CONF_ENDPOINT] = "invalid_endpoint"
            elif not user_input.get(CONF_LLM_HASS_API):
                errors[CONF_LLM_HASS_API] = "llm_api_required"
            elif error := await self._probe(endpoint, token, home_id):
                errors["base"] = error
            else:
                user_input.update({CONF_ENDPOINT: endpoint, CONF_TOKEN: token, CONF_HOME_ID: home_id})
                await self.async_set_unique_id(f"{endpoint}|{home_id}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=home_id or redact_endpoint(endpoint),
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_ENDPOINT): TextSelector(),
                        vol.Optional(CONF_TOKEN, default=""): PASSWORD,
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
                user_input,
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            token = (user_input.get(CONF_TOKEN) or "").strip()
            home_id = (user_input.get(CONF_HOME_ID) or "").strip()
            error = await self._probe(entry.data[CONF_ENDPOINT], token, home_id)
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_TOKEN: token, CONF_HOME_ID: home_id}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TOKEN): PASSWORD,
                    vol.Optional(
                        CONF_HOME_ID, default=entry.data.get(CONF_HOME_ID) or ""
                    ): TextSelector(),
                }
            ),
            description_placeholders={
                "endpoint": redact_endpoint(entry.data.get(CONF_ENDPOINT) or "")
            },
            errors=errors,
        )
