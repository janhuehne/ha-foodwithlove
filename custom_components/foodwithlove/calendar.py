"""Calendar platform for food with love week plan."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.calendar import (
    CalendarEntity,
    CalendarEntityFeature,
    CalendarEvent,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import FwlApiError, FwlAuthError
from .const import DOMAIN
from .coordinator import FwlDataUpdateCoordinator

_RECIPE_ID_RE = re.compile(r"recipe_id=([A-Za-z0-9_-]{1,128})")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the week plan calendar when authenticated."""
    coordinator: FwlDataUpdateCoordinator = entry.runtime_data
    if not coordinator.client.authenticated:
        return
    async_add_entities([FwlWeekplanCalendar(coordinator, entry.entry_id)])


class FwlWeekplanCalendar(
    CoordinatorEntity[FwlDataUpdateCoordinator], CalendarEntity
):
    """Expose the FWL week plan as a Home Assistant calendar."""

    _attr_has_entity_name = True
    _attr_translation_key = "weekplan"
    _attr_icon = "mdi:calendar-month"
    _attr_supported_features = (
        CalendarEntityFeature.CREATE_EVENT | CalendarEntityFeature.DELETE_EVENT
    )

    def __init__(
        self, coordinator: FwlDataUpdateCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_weekplan"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="food with love",
            manufacturer="fwl connect GmbH",
            model="Unofficial API",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming meal."""
        now = dt_util.now().date()
        for item in self.coordinator.data.get("weekplan") or []:
            day: date = item["date"]
            if day >= now:
                return _to_event(item)
        return None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""
        start = start_date.date()
        end = end_date.date()
        events: list[CalendarEvent] = []
        for item in self.coordinator.data.get("weekplan") or []:
            day: date = item["date"]
            if start <= day < end:
                events.append(_to_event(item))
        return events

    async def async_create_event(self, **kwargs: Any) -> None:
        """Add a recipe to the week plan.

        Put ``recipe_id=<id>`` in the description for a catalog recipe.
        Otherwise the summary is stored as a custom weekplan entry (app shape).
        """
        start = kwargs["dtstart"]
        day = start.date() if isinstance(start, datetime) else start
        description = kwargs.get("description") or ""
        match = _RECIPE_ID_RE.search(description)
        try:
            if match:
                await self.coordinator.client.set_weekplan_day(
                    match.group(1), day, enabled=True, custom=False
                )
            else:
                title = (kwargs.get("summary") or "custom").strip() or "custom"
                await self.coordinator.client.set_weekplan_day(
                    title, day, enabled=True, custom=True
                )
        except FwlAuthError as err:
            self.coordinator.entry.async_start_reauth(self.hass)
            raise HomeAssistantError("food with love authentication expired") from err
        except FwlApiError as err:
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_request_refresh()

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Remove a meal from the week plan using the typed event UID."""
        parsed = _parse_event_uid(uid)
        if parsed is None:
            raise HomeAssistantError(f"Unsupported weekplan event id: {uid}")
        kind, day_key, key = parsed
        day = datetime.strptime(day_key, "%Y%m%d").date()
        try:
            await self.coordinator.client.set_weekplan_day(
                key, day, enabled=False, custom=(kind == "c")
            )
        except FwlAuthError as err:
            self.coordinator.entry.async_start_reauth(self.hass)
            raise HomeAssistantError("food with love authentication expired") from err
        except FwlApiError as err:
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_request_refresh()


def _event_uid(*, custom: bool, day_key: str, key: str) -> str:
    """Stable UID: ``w_{day}_{recipeId}`` or ``c_{day}_{urlencoded title}``."""
    prefix = "c" if custom else "w"
    safe_key = quote_uid_part(key)
    return f"{prefix}_{day_key}_{safe_key}"


def quote_uid_part(value: str) -> str:
    return value.replace("%", "%25").replace("_", "%5F").replace("/", "%2F")


def unquote_uid_part(value: str) -> str:
    return (
        value.replace("%2F", "/")
        .replace("%5F", "_")
        .replace("%25", "%")
    )


def _parse_event_uid(uid: str) -> tuple[str, str, str] | None:
    if uid.startswith(("w_", "c_")) and len(uid) > 12:
        kind = uid[0]
        rest = uid[2:]
        day_key, _, key = rest.partition("_")
        if len(day_key) == 8 and day_key.isdigit() and key:
            return kind, day_key, unquote_uid_part(key)
    # Legacy UID from v0.3: ``{day_key}_{recipe_id}`` — assume catalog.
    if "_" in uid:
        day_key, recipe_id = uid.split("_", 1)
        if len(day_key) == 8 and day_key.isdigit() and recipe_id:
            return "w", day_key, recipe_id
    return None


def _to_event(item: dict[str, Any]) -> CalendarEvent:
    day: date = item["date"]
    title = item.get("title") or item.get("recipe_id") or "FWL"
    description_parts = []
    if item.get("recipe_id") and not item.get("custom"):
        description_parts.append(f"recipe_id={item['recipe_id']}")
    if item.get("custom"):
        description_parts.append("custom")
    return CalendarEvent(
        start=day,
        end=day + timedelta(days=1),
        summary=title,
        description="; ".join(description_parts) or None,
        uid=_event_uid(
            custom=bool(item.get("custom")),
            day_key=item.get("day_key") or day.strftime("%Y%m%d"),
            key=item.get("recipe_id") or title,
        ),
    )
