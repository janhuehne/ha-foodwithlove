"""The food with love integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import FwlApiClient
from .const import (
    CONF_LANGUAGE,
    CONF_REFRESH_TOKEN,
    CONF_UID,
    DEFAULT_LANGUAGE,
)
from .coordinator import FwlDataUpdateCoordinator

PLATFORMS_PUBLIC = [Platform.SENSOR]
PLATFORMS_AUTH = [Platform.SENSOR, Platform.CALENDAR]


def _platforms_for_entry(entry: ConfigEntry) -> list[Platform]:
    if entry.data.get(CONF_REFRESH_TOKEN):
        return list(PLATFORMS_AUTH)
    return list(PLATFORMS_PUBLIC)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up food with love from a config entry."""
    language = entry.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
    client = FwlApiClient(
        async_get_clientsession(hass),
        language=language,
        refresh_token=entry.data.get(CONF_REFRESH_TOKEN),
        uid=entry.data.get(CONF_UID),
    )
    coordinator = FwlDataUpdateCoordinator(hass, client, entry)
    await coordinator.async_config_entry_first_refresh()

    if client.refresh_token and client.refresh_token != entry.data.get(
        CONF_REFRESH_TOKEN
    ):
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_REFRESH_TOKEN: client.refresh_token,
                CONF_UID: client.uid,
            },
        )

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(
        entry, _platforms_for_entry(entry)
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(
        entry, _platforms_for_entry(entry)
    )
