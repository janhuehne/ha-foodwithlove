"""Sensor platform for food with love."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    APP_RECIPE_URL,
    ATTR_APP_URL,
    ATTR_AUTHENTICATED,
    ATTR_CATEGORIES,
    ATTR_CONTENT,
    ATTR_FAVORITE_COUNT,
    ATTR_FAVORITE_FOLDERS,
    ATTR_GREETING_DATE,
    ATTR_IMAGE_URL,
    ATTR_IS_FREE,
    ATTR_IS_PREMIUM,
    ATTR_NOTE,
    ATTR_PREPARATION_TIME,
    ATTR_RATING,
    ATTR_RATING_COUNT,
    ATTR_RECIPE_ID,
    ATTR_SERVING_TYPE,
    ATTR_SERVINGS,
    ATTR_THUMB_URL,
    ATTR_VIEWER_URL,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)
from .coordinator import FwlDataUpdateCoordinator
from .recipe_html import recipe_viewer_path
from .week_overview import build_week_overview

SENSOR_TODAY = "today"
SENSOR_GREETING = "greeting"
SENSOR_FAVORITES = "favorites"
SENSOR_WEEK_OVERVIEW = "week_overview"

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

FAVORITES_SENSOR = SensorEntityDescription(
    key=SENSOR_FAVORITES,
    translation_key="favorites",
    icon="mdi:heart",
)

WEEK_OVERVIEW_SENSOR = SensorEntityDescription(
    key=SENSOR_WEEK_OVERVIEW,
    translation_key="week_overview",
    icon="mdi:calendar-week",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up food with love sensors."""
    coordinator = entry.runtime_data
    entities: list[FwlSensor] = [
        FwlSensor(coordinator, entry.entry_id, description)
        for description in SENSORS
    ]
    if entry.data.get(CONF_REFRESH_TOKEN):
        entities.append(
            FwlSensor(coordinator, entry.entry_id, FAVORITES_SENSOR)
        )
        entities.append(
            FwlSensor(coordinator, entry.entry_id, WEEK_OVERVIEW_SENSOR)
        )
    async_add_entities(entities)


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
        auth_attrs = {ATTR_AUTHENTICATED: bool(data.get("authenticated"))}

        if key == SENSOR_TODAY:
            recipe = data.get("recipe") or {}
            recipe_id = recipe.get("id")
            self._attr_native_value = recipe.get("title")
            thumb = _first(recipe.get("thumbUrls"))
            image = _first(recipe.get("fullUrls")) or thumb
            self._attr_entity_picture = thumb
            self._attr_extra_state_attributes = {
                ATTR_RECIPE_ID: recipe_id,
                ATTR_PREPARATION_TIME: recipe.get("preparationTime"),
                ATTR_SERVINGS: recipe.get("servingsNumber"),
                ATTR_SERVING_TYPE: recipe.get("servingType"),
                ATTR_CATEGORIES: recipe.get("categories") or [],
                ATTR_THUMB_URL: thumb,
                ATTR_IMAGE_URL: image,
                ATTR_IS_PREMIUM: recipe.get("isPremium"),
                ATTR_IS_FREE: recipe.get("isFree"),
                ATTR_CONTENT: recipe.get("content"),
                ATTR_NOTE: data.get("note"),
                ATTR_APP_URL: (
                    APP_RECIPE_URL.format(recipe_id=recipe_id) if recipe_id else None
                ),
                ATTR_VIEWER_URL: (
                    recipe_viewer_path(recipe_id) if recipe_id else None
                ),
                ATTR_RATING: recipe.get("rating"),
                ATTR_RATING_COUNT: recipe.get("ratingCount"),
                **auth_attrs,
            }
            return

        if key == SENSOR_FAVORITES:
            favorites = data.get("favorites") or {}
            self._attr_native_value = favorites.get("count", 0)
            self._attr_entity_picture = None
            folders = favorites.get("folders") or []
            uncategorized = favorites.get("uncategorized") or []
            self._attr_extra_state_attributes = {
                ATTR_FAVORITE_COUNT: favorites.get("count", 0),
                ATTR_FAVORITE_FOLDERS: folders,
                "uncategorized": uncategorized,
                **auth_attrs,
            }
            return

        if key == SENSOR_WEEK_OVERVIEW:
            days = build_week_overview(
                data.get("weekplan") or [],
                language=self.coordinator.client.language,
                today=dt_util.now().date(),
            )
            today_meals = next(
                (d["meals"] for d in days if d.get("is_today")),
                [],
            )
            if today_meals:
                self._attr_native_value = ", ".join(
                    m["title"] for m in today_meals if m.get("title")
                )
                self._attr_entity_picture = next(
                    (m.get("image_url") for m in today_meals if m.get("image_url")),
                    None,
                )
            else:
                self._attr_native_value = (
                    "Keine Rezepte"
                    if self.coordinator.client.language == "de"
                    else "No recipes"
                )
                self._attr_entity_picture = None
            self._attr_extra_state_attributes = {
                "days": days,
                "meals_this_week": sum(len(d["meals"]) for d in days),
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
            **auth_attrs,
        }


def _first(values: Any) -> str | None:
    if isinstance(values, list) and values:
        item = values[0]
        return item if isinstance(item, str) else None
    return None
