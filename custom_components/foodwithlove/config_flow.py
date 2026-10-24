"""Config flow for food with love."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_CODE
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import FwlApiClient, FwlApiError, FwlAuthError
from .const import (
    CONF_DAYS_BACK,
    CONF_DAYS_FORWARD,
    CONF_EMAIL,
    CONF_LANGUAGE,
    CONF_LOGIN,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_UID,
    DEFAULT_DAYS_BACK,
    DEFAULT_DAYS_FORWARD,
    DEFAULT_LANGUAGE,
    DOMAIN,
    LOGIN_MAGIC_LINK,
    LOGIN_SKIP,
    SUPPORTED_LANGUAGES,
)
from .coordinator import default_scan_minutes


class FwlConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for food with love."""

    VERSION = 1

    def __init__(self) -> None:
        self._language = DEFAULT_LANGUAGE
        self._email: str | None = None
        self._reference: str | None = None
        self._reconfigure_entry: ConfigEntry | None = None
        self._reauth_entry: ConfigEntry | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return FwlOptionsFlow()

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
        entry = self._reauth_entry or self._reconfigure_entry
        default_email = self._email or (entry.data.get(CONF_EMAIL) if entry else None)

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

        schema: dict[Any, Any]
        if default_email:
            schema = {
                vol.Required(CONF_EMAIL, default=default_email): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.EMAIL)
                ),
            }
        else:
            schema = {
                vol.Required(CONF_EMAIL): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.EMAIL)
                ),
            }
        return self.async_show_form(
            step_id="email",
            data_schema=vol.Schema(schema),
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
                if self._reauth_entry:
                    await self.async_set_unique_id(tokens["uid"])
                    self._abort_if_unique_id_mismatch(reason="wrong_account")
                    return self.async_update_reload_and_abort(
                        self._reauth_entry,
                        data_updates=new_data,
                        title=f"food with love ({tokens['email']})",
                    )
                if self._reconfigure_entry:
                    existing_uid = self._reconfigure_entry.unique_id
                    await self.async_set_unique_id(tokens["uid"])
                    if existing_uid in (None, DOMAIN):
                        # Public-only → account: claim the UID if free.
                        self._abort_if_unique_id_configured()
                    else:
                        self._abort_if_unique_id_mismatch(reason="wrong_account")
                    return self.async_update_reload_and_abort(
                        self._reconfigure_entry,
                        data_updates=new_data,
                        title=f"food with love ({tokens['email']})",
                        unique_id=tokens["uid"],
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

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Re-authenticate when the refresh token is invalid."""
        self._reauth_entry = self._get_reauth_entry()
        self._language = self._reauth_entry.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
        self._email = self._reauth_entry.data.get(CONF_EMAIL)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm reauth then send a new Magic Link."""
        if user_input is not None:
            return await self.async_step_email()
        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={"email": self._email or ""},
        )


class FwlOptionsFlow(OptionsFlow):
    """Handle options for food with love."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        authenticated = bool(self.config_entry.data.get(CONF_REFRESH_TOKEN))
        defaults = {
            CONF_SCAN_INTERVAL: self.config_entry.options.get(
                CONF_SCAN_INTERVAL, default_scan_minutes(authenticated)
            ),
            CONF_DAYS_BACK: self.config_entry.options.get(
                CONF_DAYS_BACK, DEFAULT_DAYS_BACK
            ),
            CONF_DAYS_FORWARD: self.config_entry.options.get(
                CONF_DAYS_FORWARD, DEFAULT_DAYS_FORWARD
            ),
        }
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL, default=defaults[CONF_SCAN_INTERVAL]
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=5,
                            max=1440,
                            step=5,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="min",
                        )
                    ),
                    vol.Required(
                        CONF_DAYS_BACK, default=defaults[CONF_DAYS_BACK]
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0,
                            max=60,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_DAYS_FORWARD, default=defaults[CONF_DAYS_FORWARD]
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1,
                            max=90,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )
