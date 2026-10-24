"""DataUpdateCoordinator for food with love."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import FwlApiClient, FwlApiError, FwlAuthError
from .const import (
    CONF_DAYS_BACK,
    CONF_DAYS_FORWARD,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_UID,
    DEFAULT_DAYS_BACK,
    DEFAULT_DAYS_FORWARD,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL_AUTH,
    DEFAULT_SCAN_INTERVAL_AUTH_MINUTES,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _interval_for_entry(client: FwlApiClient, entry: ConfigEntry) -> timedelta:
    minutes = entry.options.get(CONF_SCAN_INTERVAL)
    if minutes is not None:
        return timedelta(minutes=int(minutes))
    if client.authenticated:
        return DEFAULT_SCAN_INTERVAL_AUTH
    return DEFAULT_SCAN_INTERVAL


class FwlDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll FWL public endpoints and optional authenticated account data."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: FwlApiClient,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=_interval_for_entry(client, entry),
            config_entry=entry,
        )
        self.client = client
        self.entry = entry

    def apply_options(self) -> None:
        """Refresh poll interval after options change."""
        self.update_interval = _interval_for_entry(self.client, self.entry)

    async def _async_update_data(self) -> dict[str, Any]:
        days_back = int(self.entry.options.get(CONF_DAYS_BACK, DEFAULT_DAYS_BACK))
        days_forward = int(
            self.entry.options.get(CONF_DAYS_FORWARD, DEFAULT_DAYS_FORWARD)
        )
        try:
            data = await self.client.fetch_dashboard(
                days_back=days_back,
                days_forward=days_forward,
            )
        except FwlAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except FwlApiError as err:
            raise UpdateFailed(str(err)) from err

        if self.client.refresh_token and self.client.refresh_token != self.entry.data.get(
            CONF_REFRESH_TOKEN
        ):
            self.hass.config_entries.async_update_entry(
                self.entry,
                data={
                    **self.entry.data,
                    CONF_REFRESH_TOKEN: self.client.refresh_token,
                    CONF_UID: self.client.uid,
                },
            )
        return data


def default_scan_minutes(authenticated: bool) -> int:
    """Default scan interval in minutes for options form."""
    if authenticated:
        return DEFAULT_SCAN_INTERVAL_AUTH_MINUTES
    return DEFAULT_SCAN_INTERVAL_MINUTES
