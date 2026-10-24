"""Config flow for food with love."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, ConfigEntry
from homeassistant.const import CONF_CODE
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import FwlApiClient, FwlApiError, FwlAuthError
from .const import (
    CONF_EMAIL,
    CONF_LANGUAGE,
    CONF_LOGIN,
    CONF_REFRESH_TOKEN,
    CONF_UID,
    DEFAULT_LANGUAGE,
    DOMAIN,
    LOGIN_MAGIC_LINK,
    LOGIN_SKIP,
    SUPPORTED_LANGUAGES,
)


class FwlConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for food with love."""

    VERSION = 1

    def __init__(self) -> None:
        self._language = DEFAULT_LANGUAGE
        self._email: str | None = None
        self._reference: str | None = None
        self._reconfigure_entry: ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Language + whether to sign in."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._language = user_input[CONF_LANGUAGE]
            client = FwlApiClient(
                async_get_clientsession(self.hass), language=self._language
            )
            try:
                await client.today()
            except FwlApiError:
                errors["base"] = "cannot_connect"
            else:
                if user_input[CONF_LOGIN] == LOGIN_MAGIC_LINK:
                    return await self.async_step_email()
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="food with love",
                    data={CONF_LANGUAGE: self._language},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LANGUAGE, default=self._language): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=code, label=label)
                                for code, label in SUPPORTED_LANGUAGES.items()
                            ]
                        )
                    ),
                    vol.Required(CONF_LOGIN, default=LOGIN_SKIP): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(
                                    value=LOGIN_SKIP,
                                    label="Public only (recipe of the day)",
                                ),
                                SelectOptionDict(
                                    value=LOGIN_MAGIC_LINK,
                                    label="Sign in with Magic Link (week plan)",
                                ),
                            ]
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_email(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the FWL account email and send a Magic Link code."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            client = FwlApiClient(
                async_get_clientsession(self.hass), language=self._language
            )
            try:
                self._reference = await client.request_magic_link(email)
            except FwlAuthError:
                errors["base"] = "invalid_auth"
            except FwlApiError:
                errors["base"] = "cannot_connect"
            else:
                self._email = email
                return await self.async_step_code()

        return self.async_show_form(
            step_id="email",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.EMAIL)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_code(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Enter the 6-digit code from the Magic Link email."""
        errors: dict[str, str] = {}

        if user_input is not None:
            assert self._email and self._reference
            client = FwlApiClient(
                async_get_clientsession(self.hass), language=self._language
            )
            try:
                tokens = await client.verify_magic_link(
                    email=self._email,
                    reference=self._reference,
                    code=user_input[CONF_CODE],
                )
            except FwlAuthError:
                errors["base"] = "invalid_code"
            except FwlApiError:
                errors["base"] = "cannot_connect"
            else:
                new_data = {
                    CONF_LANGUAGE: self._language,
                    CONF_EMAIL: tokens["email"],
                    CONF_REFRESH_TOKEN: tokens["refresh_token"],
                    CONF_UID: tokens["uid"],
                }
                if self._reconfigure_entry:
                    return self.async_update_reload_and_abort(
                        self._reconfigure_entry,
                        data_updates=new_data,
                    )

                await self.async_set_unique_id(tokens["uid"] or DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"food with love ({self._email})",
                    data=new_data,
                )

        return self.async_show_form(
            step_id="code",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CODE): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.NUMBER)
                    ),
                }
            ),
            description_placeholders={"email": self._email or ""},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow adding Magic Link login to an existing entry."""
        self._reconfigure_entry = self._get_reconfigure_entry()
        self._language = self._reconfigure_entry.data.get(
            CONF_LANGUAGE, DEFAULT_LANGUAGE
        )
        return await self.async_step_email()
