"""Todo platform for food with love shopping list."""

from __future__ import annotations

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import FwlApiError
from .const import DOMAIN
from .coordinator import FwlDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the shopping list todo when authenticated."""
    coordinator: FwlDataUpdateCoordinator = entry.runtime_data
    if not coordinator.client.authenticated:
        return
    async_add_entities([FwlShoppingTodo(coordinator, entry.entry_id)])


class FwlShoppingTodo(
    CoordinatorEntity[FwlDataUpdateCoordinator], TodoListEntity
):
    """Expose FWL shopping list ingredients as a todo list."""

    _attr_has_entity_name = True
    _attr_translation_key = "shopping_list"
    _attr_icon = "mdi:cart"
    _attr_supported_features = (
        TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )

    def __init__(
        self, coordinator: FwlDataUpdateCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_shopping_list"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="food with love",
            manufacturer="fwl connect GmbH",
            model="Unofficial API",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._items_by_uid: dict[str, dict] = {}
        self._update_from_coordinator()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_from_coordinator()
        self.async_write_ha_state()

    def _update_from_coordinator(self) -> None:
        items = self.coordinator.data.get("shopping_items") or []
        self._items_by_uid = {item["uid"]: item for item in items}
        self._attr_todo_items = [
            TodoItem(
                uid=item["uid"],
                summary=item["summary"],
                status=(
                    TodoItemStatus.COMPLETED
                    if item.get("done")
                    else TodoItemStatus.NEEDS_ACTION
                ),
            )
            for item in items
        ]

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Toggle done / leave summary as-is (FWL has no rename API here)."""
        if not item.uid:
            return
        stored = self._items_by_uid.get(item.uid)
        if not stored:
            raise FwlApiError(f"Unknown shopping item {item.uid}")
        done = item.status == TodoItemStatus.COMPLETED
        await self.coordinator.client.set_shopping_item_done(
            stored["recipe_id"],
            stored["ingredient_id"],
            done=done,
            raw=stored.get("raw") or {},
        )
        await self.coordinator.async_request_refresh()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Remove ingredients from Firestore shopping lists."""
        for uid in uids:
            stored = self._items_by_uid.get(uid)
            if not stored:
                continue
            await self.coordinator.client.delete_shopping_item(
                stored["recipe_id"],
                stored["ingredient_id"],
            )
        await self.coordinator.async_request_refresh()
