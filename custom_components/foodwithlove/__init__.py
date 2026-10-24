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
from .views import async_setup_views

# Always forward all platforms so unload stays stable across public↔auth.
# Calendar/todo skip entity creation when not authenticated.
PLATFORMS = [Platform.SENSOR, Platform.CALENDAR, Platform.TODO]


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

    entry.runtime_data = coordinator
    async_setup_views(hass)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options updates (token rotation is ignored as a no-op refresh)."""
    coordinator: FwlDataUpdateCoordinator | None = getattr(entry, "runtime_data", None)
    if coordinator is None:
        return
    coordinator.apply_options()
    await coordinator.async_request_refresh()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
