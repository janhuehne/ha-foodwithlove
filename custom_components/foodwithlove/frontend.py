"""Serve and register the Lovelace cards for food with love."""

from __future__ import annotations

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
_DATA_SETUP = f"{DOMAIN}_frontend_setup"
_CARD_FILENAME = "fwl-food-card.js"


async def async_setup_frontend(hass: HomeAssistant) -> None:
    """Register static card JS once per HA run."""
    if hass.data.get(_DATA_SETUP):
        return
    hass.data[_DATA_SETUP] = True

    comp_path = os.path.dirname(__file__)
    card_path = os.path.join(comp_path, _CARD_FILENAME)
    try:
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    CARD_URL,
                    card_path,
                    cache_headers=True,
                )
            ]
        )
    except RuntimeError as err:
        _LOGGER.warning("Could not register foodwithlove card static path: %s", err)
        return

    card_url = CARD_URL
    try:
        mtime = await hass.async_add_executor_job(os.path.getmtime, card_path)
        card_url = f"{CARD_URL}?v={int(mtime)}"
    except OSError:
        card_url = f"{CARD_URL}?v={int(datetime.now(timezone.utc).timestamp())}"

    add_extra_js_url(hass, card_url)
    _LOGGER.info("food with love Lovelace card at %s", card_url)

    # Also ensure a Lovelace resource exists (helps companion apps after restart).
    @callback
    def _schedule(_now=None) -> None:
        hass.async_create_task(_async_ensure_lovelace_resource(hass, card_url))

    if hass.is_running:
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
        for item in resources.async_items():
            url = item.get("url") or ""
            if url.split("?")[0] == CARD_URL:
                if url != card_url and "?v=" in card_url:
                    await resources.async_update_item(item["id"], {"url": card_url})
                return
        await resources.async_create_item({"res_type": "module", "url": card_url})
    except Exception as err:  # noqa: BLE001 — never break integration setup
        _LOGGER.debug("Lovelace resource registration skipped: %s", err)
