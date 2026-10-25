"""Serve and register the Lovelace cards for food with love."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CARD_URL = "/foodwithlove/fwl-food-card.js"
_DATA_PATH = f"{DOMAIN}_frontend_path_registered"
_CARD_FILENAME = "fwl-food-card.js"


def _card_version(comp_path: str) -> str:
    """Prefer package version so Lovelace cache-busts on releases."""
    manifest_path = os.path.join(comp_path, "manifest.json")
    try:
        with open(manifest_path, encoding="utf-8") as handle:
            data = json.load(handle)
        version = str(data.get("version") or "").strip()
        if version:
            return version
    except OSError:
        pass
    try:
        return str(int(os.path.getmtime(os.path.join(comp_path, _CARD_FILENAME))))
    except OSError:
        return str(int(datetime.now(timezone.utc).timestamp()))


async def async_setup_frontend(hass: HomeAssistant) -> None:
    """Register static card JS and keep the Lovelace resource URL fresh."""
    comp_path = os.path.dirname(__file__)
    card_path = os.path.join(comp_path, _CARD_FILENAME)
    version = _card_version(comp_path)
    card_url = f"{CARD_URL}?v={version}"

    if not hass.data.get(_DATA_PATH):
        try:
            # cache_headers=False: otherwise browsers keep stale card JS across
            # releases even when the query string changes on another loader.
            await hass.http.async_register_static_paths(
                [
                    StaticPathConfig(
                        CARD_URL,
                        card_path,
                        cache_headers=False,
                    )
                ]
            )
        except RuntimeError as err:
            _LOGGER.warning("Could not register foodwithlove card static path: %s", err)
            return
        hass.data[_DATA_PATH] = True

    # Track last injected URL so we do not stack duplicate extra_js entries.
    last_url = hass.data.get(f"{DOMAIN}_frontend_card_url")
    if last_url != card_url:
        add_extra_js_url(hass, card_url)
        hass.data[f"{DOMAIN}_frontend_card_url"] = card_url
        _LOGGER.info("food with love Lovelace card at %s", card_url)

    @callback
    def _schedule(_now=None) -> None:
        hass.async_create_task(_async_ensure_lovelace_resource(hass, card_url))

    if hass.is_running:
        # Prefer call_soon_threadsafe path via event loop — setup runs on loop.
        _schedule()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, lambda _e: _schedule())
        async_call_later(hass, 15, _schedule)


async def _async_ensure_lovelace_resource(hass: HomeAssistant, card_url: str) -> None:
    """Best-effort: create/update Lovelace module resource for the card."""
    try:
        lovelace = hass.data.get("lovelace")
        resources = getattr(lovelace, "resources", None)
        if resources is None and isinstance(lovelace, dict):
            resources = lovelace.get("resources")
        if resources is None or not hasattr(resources, "async_create_item"):
            return
        if not resources.loaded:
            await resources.async_load()
            resources.loaded = True
        existing = None
        for item in resources.async_items():
            url = item.get("url") or ""
            if "fwl-food-card" in url:
                if existing is None:
                    existing = item
                else:
                    # Drop duplicate card resources (extra_js + old /local copies).
                    try:
                        await resources.async_delete_item(item["id"])
                    except Exception:  # noqa: BLE001
                        _LOGGER.debug("Could not delete duplicate card resource %s", url)
        if existing is not None:
            if existing.get("url") != card_url:
                await resources.async_update_item(existing["id"], {"url": card_url})
            return
        await resources.async_create_item({"res_type": "module", "url": card_url})
    except Exception as err:  # noqa: BLE001 — never break integration setup
        _LOGGER.debug("Lovelace resource registration skipped: %s", err)
