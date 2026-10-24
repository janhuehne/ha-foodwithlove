"""DataUpdateCoordinator for food with love."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import FwlApiClient, FwlApiError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class FwlDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll public FWL endpoints for recipe of the day and greeting."""

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
            update_interval=DEFAULT_SCAN_INTERVAL,
            config_entry=entry,
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.fetch_dashboard()
        except FwlApiError as err:
            raise UpdateFailed(str(err)) from err
