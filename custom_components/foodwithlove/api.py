"""Async client for the unofficial food with love public API."""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from aiohttp import ClientError, ClientSession, ClientTimeout
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from .const import BASE_URL, USER_AGENT

_LOGGER = logging.getLogger(__name__)


class FwlApiError(Exception):
    """Raised when the FWL API request or decrypt fails."""


def utc_aes_key(when: datetime | None = None) -> bytes:
    """Daily AES key used by the official app: ``{MM}dontFWst{YYYY}{DD}`` (UTC)."""
    when = when or datetime.now(timezone.utc)
    return f"{when.month:02d}dontFWst{when.year}{when.day:02d}".encode("utf-8")


def decrypt_payload(blob: bytes, key: bytes | None = None) -> str:
    """Decrypt a Base64(IV||ciphertext) recipe payload."""
    key = key or utc_aes_key()
    raw = blob
    stripped = blob.strip()
    try:
        if all(
            c in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\n\r"
            for c in stripped[:64]
        ):
            raw = base64.b64decode(stripped)
    except Exception:  # noqa: BLE001
        raw = blob

    if len(raw) < 17:
        raise FwlApiError("Ciphertext too short")

    iv, ciphertext = raw[:16], raw[16:]
    try:
        cipher = AES.new(key, AES.MODE_CBC, iv)
        return unpad(cipher.decrypt(ciphertext), 16).decode("utf-8")
    except ValueError as err:
        raise FwlApiError(f"Decrypt failed (check UTC date / key): {err}") from err


class FwlApiClient:
    """Thin async wrapper around the public FWL endpoints."""

    def __init__(
        self,
        session: ClientSession,
        *,
        language: str = "de",
        base_url: str = BASE_URL,
    ) -> None:
        self._session = session
        self._language = language
        self._base_url = base_url.rstrip("/")

    @property
    def language(self) -> str:
        return self._language

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "*/*",
            "User-Agent": USER_AGENT,
            "x-platform": "Android",
            "accept-language": self._language,
            "x-fwl-lang": "true",
        }

    async def _request(self, path: str) -> bytes:
        url = path if path.startswith("http") else f"{self._base_url}{path}"
        try:
            async with self._session.get(
                url,
                headers=self._headers(),
                timeout=ClientTimeout(total=30),
            ) as response:
                body = await response.read()
                if response.status >= 400:
                    raise FwlApiError(f"HTTP {response.status} for {path}")
                return body
        except ClientError as err:
            raise FwlApiError(f"Request failed for {path}: {err}") from err

    async def _json(self, path: str) -> Any:
        return json.loads(await self._request(path))

    async def today(self) -> dict[str, Any]:
        return await self._json("/today")

    async def morning_greeting(self) -> dict[str, Any]:
        return await self._json("/api/v1/morninggreeting")

    async def recipe_index(self) -> dict[str, Any]:
        return await self._json("/api/v1/recipes/index")

    async def get_recipe(self, recipe_id: str, content_hash: str) -> dict[str, Any]:
        path = f"/api/v1/recipe/{quote(recipe_id)}/{quote(content_hash)}"
        text = decrypt_payload(await self._request(path))
        return json.loads(text)

    async def today_recipe(self) -> dict[str, Any]:
        today = await self.today()
        recipe_id = today.get("recipeId")
        if not recipe_id:
            raise FwlApiError("Missing recipeId in /today response")

        index = await self.recipe_index()
        recipes = index.get("recipes") or []
        content_hash = next(
            (item.get("h") for item in recipes if item.get("id") == recipe_id),
            None,
        )
        if not content_hash:
            raise FwlApiError(f"Today recipe {recipe_id} not found in index")

        recipe = await self.get_recipe(recipe_id, content_hash)
        recipe["_today_recipe_id"] = recipe_id
        return recipe

    async def fetch_dashboard(self) -> dict[str, Any]:
        """Fetch greeting + today's recipe for the coordinator."""
        greeting = await self.morning_greeting()
        recipe = await self.today_recipe()
        _LOGGER.debug(
            "Fetched FWL today=%s greeting_date=%s",
            recipe.get("title"),
            greeting.get("date"),
        )
        return {"greeting": greeting, "recipe": recipe}
