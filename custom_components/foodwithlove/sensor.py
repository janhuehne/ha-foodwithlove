"""Sensor platform for food with love."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_CATEGORIES,
    ATTR_CONTENT,
    ATTR_GREETING_DATE,
    ATTR_IMAGE_URL,
    ATTR_IS_FREE,
    ATTR_IS_PREMIUM,
    ATTR_PREPARATION_TIME,
    ATTR_RECIPE_ID,
    ATTR_SERVING_TYPE,
    ATTR_SERVINGS,
    ATTR_THUMB_URL,
    ATTR_AUTHENTICATED,
    ATTR_EMAIL,
    ATTR_TRANSLATIONS,
    CONF_EMAIL,
    DOMAIN,
)
from .coordinator import FwlDataUpdateCoordinator

SENSOR_TODAY = "today"
SENSOR_GREETING = "greeting"

SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key=SENSOR_TODAY,
        translation_key="today",
        icon="mdi:chef-hat",
    ),
    SensorEntityDescription(
        key=SENSOR_GREETING,
        translation_key="greeting",
        icon="mdi:hand-wave",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up food with love sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        FwlSensor(coordinator, entry.entry_id, description) for description in SENSORS
    )


class FwlSensor(CoordinatorEntity[FwlDataUpdateCoordinator], SensorEntity):
    """Representation of a food with love sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FwlDataUpdateCoordinator,
        entry_id: str,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="food with love",
            manufacturer="fwl connect GmbH",
            model="Unofficial API",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._update_from_coordinator()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_from_coordinator()
        self.async_write_ha_state()

    def _update_from_coordinator(self) -> None:
        data = self.coordinator.data or {}
        key = self.entity_description.key

        auth_attrs = {
            ATTR_AUTHENTICATED: bool(data.get("authenticated")),
            ATTR_EMAIL: self.coordinator.entry.data.get(CONF_EMAIL),
        }

        if key == SENSOR_TODAY:
            recipe = data.get("recipe") or {}
            self._attr_native_value = recipe.get("title")
            thumb = _first(recipe.get("thumbUrls"))
            image = _first(recipe.get("fullUrls")) or thumb
            self._attr_entity_picture = thumb
            self._attr_extra_state_attributes = {
                ATTR_RECIPE_ID: recipe.get("id") or recipe.get("_today_recipe_id"),
                ATTR_PREPARATION_TIME: recipe.get("preparationTime"),
                ATTR_SERVINGS: recipe.get("servingsNumber"),
                ATTR_SERVING_TYPE: recipe.get("servingType"),
                ATTR_CATEGORIES: recipe.get("categories") or [],
                ATTR_THUMB_URL: thumb,
                ATTR_IMAGE_URL: image,
                ATTR_IS_PREMIUM: recipe.get("isPremium"),
                ATTR_IS_FREE: recipe.get("isFree"),
                ATTR_CONTENT: recipe.get("content"),
                **auth_attrs,
            }
            return

        greeting = data.get("greeting") or {}
        body = greeting.get("body")
        translations = greeting.get("translations") or {}
        language = self.coordinator.client.language
        if language != "de" and language in translations:
            body = translations[language]
        self._attr_native_value = body
        self._attr_entity_picture = None
        self._attr_extra_state_attributes = {
            ATTR_GREETING_DATE: greeting.get("date"),
            ATTR_TRANSLATIONS: translations,
            **auth_attrs,
        }


def _first(values: Any) -> str | None:
    if isinstance(values, list) and values:
        item = values[0]
        return item if isinstance(item, str) else None
    return None
