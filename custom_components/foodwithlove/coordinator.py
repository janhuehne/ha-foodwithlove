"""DataUpdateCoordinator for food with love."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import FwlApiClient, FwlApiError
from .const import (
    CONF_REFRESH_TOKEN,
    CONF_UID,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL_AUTH,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class FwlDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll FWL public endpoints and optional authenticated weekplan."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: FwlApiClient,
        entry: ConfigEntry,
    ) -> None:
        interval = (
            DEFAULT_SCAN_INTERVAL_AUTH
            if client.authenticated
            else DEFAULT_SCAN_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=interval,
            config_entry=entry,
        )
        self.client = client
        self.entry = entry

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self.client.fetch_dashboard()
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
