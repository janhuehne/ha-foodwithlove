"""HTTP views for food with love (recipe HTML viewer)."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import FwlApiError
from .const import DOMAIN
from .coordinator import FwlDataUpdateCoordinator
from .recipe_html import render_recipe_html

_LOGGER = logging.getLogger(__name__)

_VIEW_KEY = f"{DOMAIN}_recipe_view_registered"


def async_setup_views(hass: HomeAssistant) -> None:
    """Register the recipe HTML viewer once."""
    if hass.data.get(_VIEW_KEY):
        return
    hass.http.register_view(FwlRecipeView())
    hass.data[_VIEW_KEY] = True


class FwlRecipeView(HomeAssistantView):
    """Serve a large-screen HTML recipe page (HA login required)."""

    url = "/api/foodwithlove/recipe/{recipe_id}"
    name = "api:foodwithlove:recipe"
    requires_auth = True

    async def get(self, request: web.Request, recipe_id: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        entry = _primary_entry(hass)
        if entry is None:
            return web.Response(status=404, text="food with love is not configured")

        coordinator: FwlDataUpdateCoordinator | None = getattr(
            entry, "runtime_data", None
        )
        if coordinator is None:
            return web.Response(status=503, text="Integration not ready")

        try:
            recipe = await _resolve_recipe(coordinator, recipe_id)
        except FwlApiError as err:
            _LOGGER.warning("Recipe viewer failed for %s: %s", recipe_id, err)
            return web.Response(status=502, text=f"Could not load recipe: {err}")
        except KeyError:
            return web.Response(status=404, text="Recipe not found")

        html = render_recipe_html(
            recipe, language=coordinator.client.language or "de"
        )
        return web.Response(text=html, content_type="text/html")


def _primary_entry(hass: HomeAssistant) -> ConfigEntry | None:
    entries = hass.config_entries.async_entries(DOMAIN)
    return entries[0] if entries else None


async def _resolve_recipe(
    coordinator: FwlDataUpdateCoordinator, recipe_id: str
) -> dict[str, Any]:
    data = coordinator.data or {}
    cached = data.get("recipe") or {}
    if cached.get("id") == recipe_id and (
        cached.get("steps") is not None or cached.get("ingredients") is not None
    ):
        return cached

    client = coordinator.client
    index = await client.get_recipe_index_map()
    content_hash = index.get(recipe_id)
    if not content_hash:
        index = await client.get_recipe_index_map(force=True)
        content_hash = index.get(recipe_id)
    if not content_hash:
        raise KeyError(recipe_id)

    recipe = await client.get_recipe(recipe_id, content_hash)
    recipe["id"] = recipe.get("id") or recipe_id
    return recipe
