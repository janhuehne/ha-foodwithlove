"""Diagnostics support for food with love."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_EMAIL, CONF_REFRESH_TOKEN, CONF_UID

TO_REDACT = {CONF_REFRESH_TOKEN, CONF_EMAIL, CONF_UID, "note"}


def _sanitize_title(title: str) -> str:
    return re.sub(r"\([^)]*@[^)]*\)", "(<email>)", title)


def _sanitize_error(message: str | None) -> str | None:
    if not message:
        return message
    message = re.sub(r"/users/[^/\s]+", "/users/<uid>", message)
    message = re.sub(r"Bearer\s+\S+", "Bearer <redacted>", message)
    return message[:200]


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data or {}
    recipe = data.get("recipe") or {}
    favorites = data.get("favorites") or {}
    shopping = data.get("shopping_items") or []
    weekplan = data.get("weekplan") or []

    return {
        "entry": async_redact_data(
            {
                "title": _sanitize_title(entry.title),
                "data": dict(entry.data),
                "options": dict(entry.options),
            },
            TO_REDACT,
        ),
        "authenticated": bool(data.get("authenticated")),
        "recipe": {
            "id": recipe.get("id"),
            "title": recipe.get("title"),
            "preparation_time": recipe.get("preparationTime"),
            "has_note": bool(data.get("note")),
        },
        "weekplan_count": len(weekplan),
        "shopping_item_count": len(shopping),
        "shopping_done_count": sum(1 for i in shopping if i.get("done")),
        "favorites_count": favorites.get("count", 0),
        "favorite_folders": [
            {"name": f.get("name"), "count": f.get("count")}
            for f in favorites.get("folders") or []
        ],
        "account_error": _sanitize_error(data.get("account_error")),
        "account_stale": bool(data.get("account_stale")),
    }
