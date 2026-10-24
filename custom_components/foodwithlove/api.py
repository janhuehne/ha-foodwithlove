"""Async client for the unofficial food with love API + Firebase Auth/Firestore."""

from __future__ import annotations

import base64
import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlencode

from aiohttp import ClientError, ClientResponseError, ClientSession, ClientTimeout
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from .const import (
    BASE_URL,
    FIREBASE_API_KEY,
    FIRESTORE_BASE,
    FUNCTIONS_URL,
    IDENTITY_URL,
    SECURE_TOKEN_URL,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)
_TIMEOUT = ClientTimeout(total=30)


class FwlApiError(Exception):
    """Raised when the FWL API request or decrypt fails."""


class FwlAuthError(FwlApiError):
    """Raised for authentication failures."""


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


def _firestore_decode(value: dict[str, Any]) -> Any:
    """Decode a Firestore REST field value."""
    if "stringValue" in value:
        return value["stringValue"]
    if "booleanValue" in value:
        return value["booleanValue"]
    if "integerValue" in value:
        return int(value["integerValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "nullValue" in value:
        return None
    if "mapValue" in value:
        fields = value["mapValue"].get("fields") or {}
        return {k: _firestore_decode(v) for k, v in fields.items()}
    if "arrayValue" in value:
        values = value["arrayValue"].get("values") or []
        return [_firestore_decode(v) for v in values]
    return value


class FwlApiClient:
    """Async wrapper around public FWL endpoints, Magic Link auth, and Firestore."""

    def __init__(
        self,
        session: ClientSession,
        *,
        language: str = "de",
        base_url: str = BASE_URL,
        refresh_token: str | None = None,
        uid: str | None = None,
    ) -> None:
        self._session = session
        self._language = language
        self._base_url = base_url.rstrip("/")
        self._refresh_token = refresh_token
        self._uid = uid
        self._id_token: str | None = None
        self._id_token_expires_at = 0.0
        self._recipe_index: dict[str, str] | None = None

    @property
    def language(self) -> str:
        return self._language

    @property
    def authenticated(self) -> bool:
        return bool(self._refresh_token)

    @property
    def uid(self) -> str | None:
        return self._uid

    @property
    def refresh_token(self) -> str | None:
        return self._refresh_token

    def set_tokens(self, *, refresh_token: str, uid: str) -> None:
        """Store tokens from a successful login."""
        self._refresh_token = refresh_token
        self._uid = uid
        self._id_token = None
        self._id_token_expires_at = 0.0

    def clear_auth(self) -> None:
        """Drop stored credentials."""
        self._refresh_token = None
        self._uid = None
        self._id_token = None
        self._id_token_expires_at = 0.0

    def _headers(self, *, auth: bool = False) -> dict[str, str]:
        headers = {
            "Accept": "*/*",
            "User-Agent": USER_AGENT,
            "x-platform": "Android",
            "accept-language": self._language,
            "x-fwl-lang": "true",
        }
        if auth and self._id_token:
            headers["Authorization"] = f"Bearer {self._id_token}"
        return headers

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        auth: bool = False,
        headers: dict[str, str] | None = None,
    ) -> Any:
        req_headers = self._headers(auth=auth)
        if headers:
            req_headers.update(headers)
        try:
            async with self._session.request(
                method,
                url,
                json=json_body,
                data=data,
                headers=req_headers,
                timeout=_TIMEOUT,
            ) as response:
                body = await response.read()
                if response.status >= 400:
                    detail = body.decode("utf-8", errors="replace")[:300]
                    raise FwlApiError(f"HTTP {response.status} for {url}: {detail}")
                if not body:
                    return None
                content_type = response.headers.get("Content-Type", "")
                if "application/json" in content_type or body[:1] in (b"{", b"["):
                    return json.loads(body)
                return body
        except ClientResponseError as err:
            raise FwlApiError(f"Request failed for {url}: {err}") from err
        except ClientError as err:
            raise FwlApiError(f"Request failed for {url}: {err}") from err

    async def _get_bytes(self, path: str) -> bytes:
        url = path if path.startswith("http") else f"{self._base_url}{path}"
        result = await self._request("GET", url)
        if isinstance(result, bytes):
            return result
        if isinstance(result, (dict, list)):
            return json.dumps(result).encode()
        raise FwlApiError(f"Unexpected response type for {path}")

    async def _get_json(self, path: str) -> Any:
        url = path if path.startswith("http") else f"{self._base_url}{path}"
        result = await self._request("GET", url)
        if isinstance(result, (dict, list)):
            return result
        if isinstance(result, bytes):
            return json.loads(result)
        raise FwlApiError(f"Unexpected response type for {path}")

    # --- public recipe API -------------------------------------------------

    async def today(self) -> dict[str, Any]:
        return await self._get_json("/today")

    async def morning_greeting(self) -> dict[str, Any]:
        return await self._get_json("/api/v1/morninggreeting")

    async def recipe_index(self) -> dict[str, Any]:
        return await self._get_json("/api/v1/recipes/index")

    async def get_recipe_index_map(self, *, force: bool = False) -> dict[str, str]:
        if self._recipe_index is None or force:
            index = await self.recipe_index()
            self._recipe_index = {
                item["id"]: item["h"]
                for item in index.get("recipes") or []
                if item.get("id") and item.get("h")
            }
        return self._recipe_index

    async def get_recipe(self, recipe_id: str, content_hash: str) -> dict[str, Any]:
        path = f"/api/v1/recipe/{quote(recipe_id)}/{quote(content_hash)}"
        text = decrypt_payload(await self._get_bytes(path))
        return json.loads(text)

    async def get_recipes(self, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        path = f"/api/v1/recipes?{urlencode({'ids': ','.join(ids)})}"
        text = decrypt_payload(await self._get_bytes(path))
        data = json.loads(text)
        return data if isinstance(data, list) else [data]

    async def resolve_recipe_titles(self, recipe_ids: list[str]) -> dict[str, str]:
        """Resolve recipe IDs to titles (best-effort)."""
        index = await self.get_recipe_index_map()
        titles: dict[str, str] = {}
        to_fetch: list[str] = []
        for rid in recipe_ids:
            if rid in index:
                to_fetch.append(rid)
            else:
                titles[rid] = rid
        chunk_size = 20
        for i in range(0, len(to_fetch), chunk_size):
            chunk = to_fetch[i : i + chunk_size]
            try:
                recipes = await self.get_recipes(chunk)
            except FwlApiError as err:
                _LOGGER.warning("Failed to resolve recipes %s: %s", chunk, err)
                for rid in chunk:
                    titles.setdefault(rid, rid)
                continue
            for recipe in recipes:
                rid = recipe.get("id")
                if rid:
                    titles[rid] = recipe.get("title") or rid
            for rid in chunk:
                titles.setdefault(rid, rid)
        return titles

    async def today_recipe(self) -> dict[str, Any]:
        today = await self.today()
        recipe_id = today.get("recipeId")
        if not recipe_id:
            raise FwlApiError("Missing recipeId in /today response")

        index = await self.get_recipe_index_map()
        content_hash = index.get(recipe_id)
        if not content_hash:
            raise FwlApiError(f"Today recipe {recipe_id} not found in index")

        recipe = await self.get_recipe(recipe_id, content_hash)
        recipe["_today_recipe_id"] = recipe_id
        return recipe

    # --- Magic Link auth ---------------------------------------------------

    async def request_magic_link(self, email: str) -> str:
        """Request a Magic Link code; returns the login reference."""
        url = f"{FUNCTIONS_URL}/v1RequestLogin"
        result = await self._request(
            "POST",
            url,
            json_body={"email": email.strip()},
            headers={"Content-Type": "application/json"},
        )
        if not isinstance(result, dict) or not result.get("reference"):
            raise FwlAuthError("Magic Link request rejected")
        return result["reference"]

    async def verify_magic_link(
        self, *, email: str, reference: str, code: str
    ) -> dict[str, str]:
        """Verify code → Firebase custom token → ID/refresh tokens."""
        url = f"{FUNCTIONS_URL}/v1VerifyLogin"
        try:
            result = await self._request(
                "POST",
                url,
                json_body={
                    "email": email.strip(),
                    "reference": reference,
                    "code": code.strip(),
                },
                headers={"Content-Type": "application/json"},
            )
        except FwlApiError as err:
            if "HTTP 403" in str(err) or "HTTP 401" in str(err):
                raise FwlAuthError("Invalid Magic Link code") from err
            raise
        if not isinstance(result, dict) or not result.get("token"):
            raise FwlAuthError("Invalid Magic Link code")

        custom_token = result["token"]
        sign_in = await self._request(
            "POST",
            f"{IDENTITY_URL}/accounts:signInWithCustomToken?key={FIREBASE_API_KEY}",
            json_body={"token": custom_token, "returnSecureToken": True},
            headers={"Content-Type": "application/json"},
        )
        if not isinstance(sign_in, dict) or not sign_in.get("refreshToken"):
            raise FwlAuthError("Firebase sign-in failed")

        refresh_token = sign_in["refreshToken"]
        uid = sign_in.get("localId") or sign_in.get("userId") or ""
        id_token = sign_in.get("idToken")
        expires_in = int(sign_in.get("expiresIn") or 3600)

        self.set_tokens(refresh_token=refresh_token, uid=uid)
        if id_token:
            self._id_token = id_token
            self._id_token_expires_at = time.time() + expires_in - 60

        # Some Identity Toolkit responses omit localId; refresh always returns user_id.
        if not uid:
            await self.ensure_id_token()
            uid = self._uid or ""

        if not uid:
            raise FwlAuthError("Firebase sign-in did not return a user id")

        return {
            "refresh_token": self._refresh_token or refresh_token,
            "uid": uid,
            "email": email.strip(),
        }

    async def ensure_id_token(self) -> str:
        """Return a valid Firebase ID token, refreshing if needed."""
        if self._id_token and time.time() < self._id_token_expires_at:
            return self._id_token
        if not self._refresh_token:
            raise FwlAuthError("Not authenticated")

        result = await self._request(
            "POST",
            f"{SECURE_TOKEN_URL}?key={FIREBASE_API_KEY}",
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if not isinstance(result, dict) or not result.get("id_token"):
            raise FwlAuthError("Token refresh failed")

        self._id_token = result["id_token"]
        if result.get("refresh_token"):
            self._refresh_token = result["refresh_token"]
        if result.get("user_id"):
            self._uid = result["user_id"]
        expires_in = int(result.get("expires_in") or 3600)
        self._id_token_expires_at = time.time() + expires_in - 60
        return self._id_token

    # --- Firestore weekplan ------------------------------------------------

    async def list_weekplan(
        self, *, days_back: int = 7, days_forward: int = 21
    ) -> list[dict[str, Any]]:
        """Return planned meals as ``{date, recipe_id, title, custom}``."""
        await self.ensure_id_token()
        if not self._uid:
            raise FwlAuthError("Missing user id")

        catalog = await self._list_weekplan_collection("weekplan")
        custom = await self._list_weekplan_collection("weekplanCustom")

        start = date.today() - timedelta(days=days_back)
        end = date.today() + timedelta(days=days_forward)

        events: list[dict[str, Any]] = []
        recipe_ids: list[str] = []

        for day_key, ids in catalog.items():
            day = _parse_fwl_day(day_key)
            if day is None or day < start or day > end:
                continue
            for rid in ids:
                recipe_ids.append(rid)
                events.append(
                    {
                        "date": day,
                        "day_key": day_key,
                        "recipe_id": rid,
                        "custom": False,
                    }
                )

        for day_key, ids in custom.items():
            day = _parse_fwl_day(day_key)
            if day is None or day < start or day > end:
                continue
            for name in ids:
                events.append(
                    {
                        "date": day,
                        "day_key": day_key,
                        "recipe_id": name,
                        "title": name,
                        "custom": True,
                    }
                )

        titles = await self.resolve_recipe_titles(list(dict.fromkeys(recipe_ids)))
        for event in events:
            if not event.get("custom"):
                event["title"] = titles.get(event["recipe_id"], event["recipe_id"])

        events.sort(key=lambda e: (e["date"], e.get("title") or ""))
        return events

    async def _list_weekplan_collection(self, collection: str) -> dict[str, list[str]]:
        url = f"{FIRESTORE_BASE}/users/{quote(self._uid)}/{collection}"
        result = await self._request("GET", url, auth=True)
        out: dict[str, list[str]] = {}
        if not isinstance(result, dict):
            return out
        for doc in result.get("documents") or []:
            name = doc.get("name") or ""
            day_key = name.rsplit("/", 1)[-1]
            fields = doc.get("fields") or {}
            dates_field = fields.get("dates")
            if dates_field:
                decoded = _firestore_decode(dates_field)
                if isinstance(decoded, dict):
                    out[day_key] = [
                        key for key, enabled in decoded.items() if enabled
                    ]
                    continue
            # weekplanCustom docs are often a flat map of name→bool
            flat = {
                key: _firestore_decode(value)
                for key, value in fields.items()
                if key != "dates"
            }
            enabled = [key for key, value in flat.items() if value is True]
            if enabled:
                out[day_key] = enabled
        return out

    async def fetch_dashboard(self) -> dict[str, Any]:
        """Fetch greeting, today's recipe, and optional weekplan."""
        greeting = await self.morning_greeting()
        recipe = await self.today_recipe()
        data: dict[str, Any] = {
            "greeting": greeting,
            "recipe": recipe,
            "weekplan": [],
            "authenticated": self.authenticated,
        }
        if self.authenticated:
            try:
                data["weekplan"] = await self.list_weekplan()
            except FwlApiError as err:
                _LOGGER.warning("Weekplan fetch failed: %s", err)
                data["weekplan_error"] = str(err)
        return data


def _parse_fwl_day(day_key: str) -> date | None:
    try:
        return datetime.strptime(day_key, "%Y%m%d").date()
    except ValueError:
        return None
