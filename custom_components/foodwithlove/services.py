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
from .sanitize import is_valid_recipe_id

_LOGGER = logging.getLogger(__name__)

SERVICE_REMOVE_WEEKPLAN_MEAL = "remove_weekplan_meal"
SERVICE_ADD_WEEKPLAN_MEAL = "add_weekplan_meal"
SERVICE_CREATE_FAVORITE_FOLDER = "create_favorite_folder"
SERVICE_DELETE_FAVORITE_FOLDER = "delete_favorite_folder"
SERVICE_MOVE_FAVORITE = "move_favorite"
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

SERVICE_CREATE_FOLDER_SCHEMA = vol.Schema(
    {vol.Required("name"): cv.string}
)

SERVICE_DELETE_FOLDER_SCHEMA = vol.Schema(
    {vol.Required("folder_id"): cv.string}
)

SERVICE_MOVE_FAVORITE_SCHEMA = vol.Schema(
    {
        vol.Required("recipe_id"): cv.string,
        vol.Optional("folder_id"): vol.Any(None, cv.string),
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

    async def _handle_create_folder(call: ServiceCall) -> None:
        await _async_create_favorite_folder(hass, call.data)

    async def _handle_delete_folder(call: ServiceCall) -> None:
        await _async_delete_favorite_folder(hass, call.data)

    async def _handle_move_favorite(call: ServiceCall) -> None:
        await _async_move_favorite(hass, call.data)

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
    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_FAVORITE_FOLDER,
        _handle_create_folder,
        schema=SERVICE_CREATE_FOLDER_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_FAVORITE_FOLDER,
        _handle_delete_folder,
        schema=SERVICE_DELETE_FOLDER_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_MOVE_FAVORITE,
        _handle_move_favorite,
        schema=SERVICE_MOVE_FAVORITE_SCHEMA,
    )


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unregister services when the last config entry unloads."""
    if not hass.data.pop(_DATA_SERVICES, None):
        return
    for name in (
        SERVICE_REMOVE_WEEKPLAN_MEAL,
        SERVICE_ADD_WEEKPLAN_MEAL,
        SERVICE_CREATE_FAVORITE_FOLDER,
        SERVICE_DELETE_FAVORITE_FOLDER,
        SERVICE_MOVE_FAVORITE,
    ):
        hass.services.async_remove(DOMAIN, name)


async def _async_set_weekplan_meal(
    hass: HomeAssistant, data: dict[str, Any], *, enabled: bool
) -> None:
    coordinator = _require_coordinator(hass)

    day = data["date"]
    if isinstance(day, datetime):
        day = day.date()
    custom = bool(data.get("custom"))
    if custom:
        key = (data.get("title") or "").strip()
        if not key or len(key) > 200:
            raise HomeAssistantError("title is required for custom weekplan entries")
        if any(ch in key for ch in ("\x00", "\n", "\r", "`")):
            raise HomeAssistantError("title contains invalid characters")
    else:
        key = (data.get("recipe_id") or "").strip()
        if not is_valid_recipe_id(key):
            raise HomeAssistantError("recipe_id is invalid")

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


async def _async_create_favorite_folder(
    hass: HomeAssistant, data: dict[str, Any]
) -> None:
    coordinator = _require_coordinator(hass)
    name = (data.get("name") or "").strip()
    try:
        folder_id = await coordinator.client.create_favorite_folder(name)
    except FwlAuthError as err:
        coordinator.entry.async_start_reauth(hass)
        raise HomeAssistantError("food with love authentication expired") from err
    except FwlApiError as err:
        raise HomeAssistantError(str(err)) from err
    await coordinator.async_request_refresh()
    _LOGGER.info("Created favorite folder %s (%s)", name, folder_id)


async def _async_delete_favorite_folder(
    hass: HomeAssistant, data: dict[str, Any]
) -> None:
    coordinator = _require_coordinator(hass)
    folder_id = (data.get("folder_id") or "").strip()
    if not is_valid_recipe_id(folder_id):
        raise HomeAssistantError("folder_id is invalid")
    try:
        await coordinator.client.delete_favorite_folder(folder_id)
    except FwlAuthError as err:
        coordinator.entry.async_start_reauth(hass)
        raise HomeAssistantError("food with love authentication expired") from err
    except FwlApiError as err:
        raise HomeAssistantError(str(err)) from err
    await coordinator.async_request_refresh()
    _LOGGER.info("Deleted favorite folder %s", folder_id)


async def _async_move_favorite(hass: HomeAssistant, data: dict[str, Any]) -> None:
    coordinator = _require_coordinator(hass)
    recipe_id = (data.get("recipe_id") or "").strip()
    if not is_valid_recipe_id(recipe_id):
        raise HomeAssistantError("recipe_id is invalid")
    raw_folder = data.get("folder_id")
    folder_id: str | None
    if raw_folder is None or str(raw_folder).strip() in ("", "__uncategorized__"):
        folder_id = None
    else:
        folder_id = str(raw_folder).strip()
        if not is_valid_recipe_id(folder_id):
            raise HomeAssistantError("folder_id is invalid")
    try:
        await coordinator.client.move_favorite(recipe_id, to_folder_id=folder_id)
    except FwlAuthError as err:
        coordinator.entry.async_start_reauth(hass)
        raise HomeAssistantError("food with love authentication expired") from err
    except FwlApiError as err:
        raise HomeAssistantError(str(err)) from err
    await coordinator.async_request_refresh()
    _LOGGER.info("Moved favorite %s to folder %s", recipe_id, folder_id)


def _require_coordinator(hass: HomeAssistant) -> FwlDataUpdateCoordinator:
    coordinator = _primary_coordinator(hass)
    if coordinator is None:
        raise HomeAssistantError("food with love is not configured")
    if not coordinator.client.authenticated:
        raise HomeAssistantError("food with love is not signed in")
    return coordinator


def _primary_coordinator(hass: HomeAssistant) -> FwlDataUpdateCoordinator | None:
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return None
    return getattr(entries[0], "runtime_data", None)
