"""Minimal unofficial food with love (FWL) API client.

Decrypts public recipe payloads the same way the Android app does.
User-specific data (weekplan, shopping list) needs Firebase Auth + Firestore.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

BASE = "https://food-with-love-app.web.app"
UA = "FWL-HA/0.1 (unofficial; +https://github.com/local/ha-foodwithlove)"


def utc_aes_key(when: datetime | None = None) -> bytes:
    """Daily AES key: ``{MM}dontFWst{YYYY}{DD}`` in UTC (16 bytes)."""
    when = when or datetime.now(timezone.utc)
    return f"{when.month:02d}dontFWst{when.year}{when.day:02d}".encode("utf-8")


def decrypt_payload(blob: bytes, key: bytes | None = None) -> str:
    """Decrypt Base64(IV||ciphertext) or raw IV||ciphertext from the CDN."""
    key = key or utc_aes_key()
    raw = blob
    # Responses are Base64 text (Content-Type often text/html).
    try:
        stripped = blob.strip()
        if all(c in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\n\r" for c in stripped[:64]):
            raw = base64.b64decode(stripped)
    except Exception:
        raw = blob
    if len(raw) < 17:
        raise ValueError("ciphertext too short")
    iv, ct = raw[:16], raw[16:]
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return unpad(cipher.decrypt(ct), 16).decode("utf-8")


@dataclass
class FwlClient:
    base: str = BASE
    language: str = "de"

    def _request(self, path: str, *, token: str | None = None) -> bytes:
        url = path if path.startswith("http") else f"{self.base}{path}"
        headers = {
            "Accept": "*/*",
            "User-Agent": UA,
            "x-platform": "Android",
            "accept-language": self.language,
            "x-fwl-lang": "true",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()

    def _json(self, path: str, *, token: str | None = None) -> Any:
        return json.loads(self._request(path, token=token))

    def today(self) -> dict[str, Any]:
        return self._json("/today")

    def morning_greeting(self) -> dict[str, Any]:
        return self._json("/api/v1/morninggreeting")

    def recipe_index(self) -> dict[str, Any]:
        return self._json("/api/v1/recipes/index")

    def books(self) -> list[dict[str, Any]]:
        return self._json("/api/v1/books")

    def get_recipe(self, recipe_id: str, content_hash: str) -> dict[str, Any]:
        path = f"/api/v1/recipe/{urllib.parse.quote(recipe_id)}/{urllib.parse.quote(content_hash)}"
        text = decrypt_payload(self._request(path))
        return json.loads(text)

    def get_recipes(self, ids: list[str]) -> list[dict[str, Any]]:
        q = urllib.parse.urlencode({"ids": ",".join(ids)})
        text = decrypt_payload(self._request(f"/api/v1/recipes?{q}"))
        data = json.loads(text)
        return data if isinstance(data, list) else [data]

    def today_recipe(self) -> dict[str, Any]:
        rid = self.today()["recipeId"]
        index = {r["id"]: r["h"] for r in self.recipe_index()["recipes"]}
        h = index.get(rid)
        if not h:
            raise KeyError(f"today recipe {rid} missing from index")
        return self.get_recipe(rid, h)


def main() -> None:
    client = FwlClient()
    greeting = client.morning_greeting()
    recipe = client.today_recipe()
    print("Greeting:", greeting.get("body"))
    print("Today:", recipe.get("title"))
    print("Time:", recipe.get("preparationTime"), "min")
    print("Servings:", recipe.get("servingsNumber"), recipe.get("servingType"))
    thumbs = recipe.get("thumbUrls") or []
    if thumbs:
        print("Thumb:", thumbs[0])


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code}: {e.reason}") from e
