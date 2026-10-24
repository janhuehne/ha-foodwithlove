"""Config flow for food with love."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import SelectOptionDict, SelectSelector, SelectSelectorConfig

from .api import FwlApiClient, FwlApiError
from .const import CONF_LANGUAGE, DEFAULT_LANGUAGE, DOMAIN, SUPPORTED_LANGUAGES

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_LANGUAGE, default=DEFAULT_LANGUAGE): SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(value=code, label=label)
                    for code, label in SUPPORTED_LANGUAGES.items()
                ]
            )
        ),
    }
)


class FwlConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for food with love."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            language = user_input[CONF_LANGUAGE]
            client = FwlApiClient(async_get_clientsession(self.hass), language=language)
            try:
                await client.today()
            except FwlApiError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="food with love",
                    data={CONF_LANGUAGE: language},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
