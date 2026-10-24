"""Calendar platform for food with love week plan."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import FwlDataUpdateCoordinator


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
        uid=f"{item.get('day_key')}_{item.get('recipe_id')}",
    )
