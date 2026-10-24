"""Home Assistant services for food with love."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .api import FwlApiError, FwlAuthError
from .const import DOMAIN
from .coordinator import FwlDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_REMOVE_WEEKPLAN_MEAL = "remove_weekplan_meal"
SERVICE_ADD_WEEKPLAN_MEAL = "add_weekplan_meal"
_DATA_SERVICES = f"{DOMAIN}_services"

SERVICE_REMOVE_SCHEMA = vol.Schema(
    {
        vol.Required("date"): cv.date,
        vol.Optional("recipe_id"): cv.string,
        vol.Optional("title"): cv.string,
        vol.Optional("custom", default=False): cv.boolean,
    }
)

SERVICE_ADD_SCHEMA = vol.Schema(
    {
        vol.Required("date"): cv.date,
        vol.Optional("recipe_id"): cv.string,
        vol.Optional("title"): cv.string,
        vol.Optional("custom", default=False): cv.boolean,
    }
)


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register domain services once."""
    if hass.data.get(_DATA_SERVICES):
        return
    hass.data[_DATA_SERVICES] = True

    async def _handle_remove(call: ServiceCall) -> None:
        await _async_set_weekplan_meal(hass, call.data, enabled=False)

    async def _handle_add(call: ServiceCall) -> None:
        await _async_set_weekplan_meal(hass, call.data, enabled=True)

    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE_WEEKPLAN_MEAL,
        _handle_remove,
        schema=SERVICE_REMOVE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_WEEKPLAN_MEAL,
        _handle_add,
        schema=SERVICE_ADD_SCHEMA,
    )


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unregister services when the last config entry unloads."""
    if not hass.data.pop(_DATA_SERVICES, None):
        return
    hass.services.async_remove(DOMAIN, SERVICE_REMOVE_WEEKPLAN_MEAL)
    hass.services.async_remove(DOMAIN, SERVICE_ADD_WEEKPLAN_MEAL)


async def _async_set_weekplan_meal(
    hass: HomeAssistant, data: dict[str, Any], *, enabled: bool
) -> None:
    coordinator = _primary_coordinator(hass)
    if coordinator is None:
        raise HomeAssistantError("food with love is not configured")
    if not coordinator.client.authenticated:
        raise HomeAssistantError("food with love is not signed in")

    day = data["date"]
    if isinstance(day, datetime):
        day = day.date()
    custom = bool(data.get("custom"))
    if custom:
        key = (data.get("title") or "").strip()
        if not key:
            raise HomeAssistantError("title is required for custom weekplan entries")
    else:
        key = (data.get("recipe_id") or "").strip()
        if not key:
            raise HomeAssistantError("recipe_id is required")

    try:
        await coordinator.client.set_weekplan_day(
            key, day, enabled=enabled, custom=custom
        )
    except FwlAuthError as err:
        coordinator.entry.async_start_reauth(hass)
        raise HomeAssistantError("food with love authentication expired") from err
    except FwlApiError as err:
        raise HomeAssistantError(str(err)) from err

    await coordinator.async_request_refresh()
    _LOGGER.info(
        "%s weekplan meal %s on %s (custom=%s)",
        "Added" if enabled else "Removed",
        key,
        day.isoformat(),
        custom,
    )


def _primary_coordinator(hass: HomeAssistant) -> FwlDataUpdateCoordinator | None:
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return None
    return getattr(entries[0], "runtime_data", None)
