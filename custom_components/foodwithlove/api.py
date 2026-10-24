"""Async client for the unofficial food with love API + Firebase Auth/Firestore."""

from __future__ import annotations

import base64
import json
import logging
import re
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
    SHOPPING_CUSTOM_DOC,
    USER_AGENT,
)
from .sanitize import (
    app_recipe_url,
    is_valid_recipe_id,
    recipe_viewer_path,
    sanitize_error_detail,
)

_LOGGER = logging.getLogger(__name__)
_TIMEOUT = ClientTimeout(total=30)

_AUTH_TOKEN_ERRORS = (
    "INVALID_REFRESH_TOKEN",
    "TOKEN_EXPIRED",
    "USER_DISABLED",
    "USER_NOT_FOUND",
    "INVALID_GRANT",
    "invalid_grant",
)


class FwlApiError(Exception):
    """Raised when the FWL API request or decrypt fails."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


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


def _firestore_encode(value: Any) -> dict[str, Any]:
    """Encode a Python value as a Firestore REST field value."""
    if value is None:
        return {"nullValue": None}
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"integerValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, dict):
        return {
            "mapValue": {
                "fields": {k: _firestore_encode(v) for k, v in value.items()}
            }
        }
    if isinstance(value, list):
        return {"arrayValue": {"values": [_firestore_encode(v) for v in value]}}
    return {"stringValue": str(value)}


def _split_field_path(path: str) -> list[str]:
    """Split ``dates.`20261203` `` / ``ingredients.`id`.done`` into segments."""
    parts: list[str] = []
    i = 0
    while i < len(path):
        if path[i] == "`":
            end = path.index("`", i + 1)
            parts.append(path[i + 1 : end])
            i = end + 1
            if i < len(path) and path[i] == ".":
                i += 1
            continue
        dot = path.find(".", i)
        if dot < 0:
            parts.append(path[i:])
            break
        parts.append(path[i:dot])
        i = dot + 1
    return parts


def _quote_field_path(segment: str) -> str:
    """Quote a Firestore field path segment when needed."""
    if re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", segment):
        return segment
    return f"`{segment}`"


def _build_fields_from_leaves(leaves: dict[str, Any]) -> dict[str, Any]:
    """Build a nested Python dict from leaf field paths, then Firestore-encode."""
    root: dict[str, Any] = {}
    for path, value in leaves.items():
        parts = _split_field_path(path)
        cursor = root
        for part in parts[:-1]:
            nxt = cursor.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                cursor[part] = nxt
            cursor = nxt
        cursor[parts[-1]] = value
    return {k: _firestore_encode(v) for k, v in root.items()}


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
        self._recipe_index_fetched_at = 0.0
        self._ratings: dict[str, dict[str, Any]] | None = None
        self._ratings_fetched_at = 0.0

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
                if len(body) > 5_000_000:
                    raise FwlApiError(
                        f"Response too large for {url}",
                        status=response.status,
                    )
                if response.status >= 400:
                    detail = sanitize_error_detail(
                        body.decode("utf-8", errors="replace")
                    )
                    raise FwlApiError(
                        f"HTTP {response.status}: {detail}",
                        status=response.status,
                    )
                if not body:
                    return None
                content_type = response.headers.get("Content-Type", "")
                try:
                    if "application/json" in content_type or body[:1] in (b"{", b"["):
                        return json.loads(body)
                except json.JSONDecodeError as err:
                    raise FwlApiError(
                        f"Invalid JSON for {url}: {err}", status=response.status
                    ) from err
                return body
        except FwlApiError:
            raise
        except TimeoutError as err:
            raise FwlApiError(f"Timeout for {url}") from err
        except ClientResponseError as err:
            raise FwlApiError(
                f"Request failed for {url}: {err}", status=err.status
            ) from err
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
            try:
                return json.loads(result)
            except json.JSONDecodeError as err:
                raise FwlApiError(f"Invalid JSON for {path}: {err}") from err
        raise FwlApiError(f"Unexpected response type for {path}")

    # --- public recipe API -------------------------------------------------

    async def today(self) -> dict[str, Any]:
        return await self._get_json("/today")

    async def morning_greeting(self) -> dict[str, Any]:
        return await self._get_json("/api/v1/morninggreeting")

    async def recipe_index(self) -> dict[str, Any]:
        return await self._get_json("/api/v1/recipes/index")

    async def get_recipe_index_map(self, *, force: bool = False) -> dict[str, str]:
        stale = (
            self._recipe_index is not None
            and time.time() - self._recipe_index_fetched_at > 86400
        )
        if self._recipe_index is None or force or stale:
            index = await self.recipe_index()
            self._recipe_index = {
                item["id"]: item["h"]
                for item in index.get("recipes") or []
                if item.get("id") and item.get("h")
            }
            self._recipe_index_fetched_at = time.time()
        return self._recipe_index

    async def get_ratings_map(self, *, force: bool = False) -> dict[str, dict[str, Any]]:
        """Public ``/ratings/`` map: ``{ recipeId: { rating, count, score } }``."""
        stale = (
            self._ratings is not None
            and time.time() - self._ratings_fetched_at > 3600
        )
        if self._ratings is None or force or stale:
            try:
                raw = await self._get_json("/ratings/")
            except FwlApiError as err:
                _LOGGER.warning("Failed to load ratings map: %s", err)
                return self._ratings or {}
            out: dict[str, dict[str, Any]] = {}
            if isinstance(raw, dict):
                for rid, info in raw.items():
                    if not isinstance(info, dict):
                        continue
                    out[str(rid)] = {
                        "rating": info.get("rating"),
                        "count": info.get("count"),
                        "score": info.get("score"),
                    }
            self._ratings = out
            self._ratings_fetched_at = time.time()
        return self._ratings

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
        missing = [rid for rid in recipe_ids if rid not in index]
        if missing:
            index = await self.get_recipe_index_map(force=True)

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
            index = await self.get_recipe_index_map(force=True)
            content_hash = index.get(recipe_id)
        if not content_hash:
            raise FwlApiError(f"Today recipe {recipe_id} not found in index")

        try:
            recipe = await self.get_recipe(recipe_id, content_hash)
        except FwlApiError:
            index = await self.get_recipe_index_map(force=True)
            content_hash = index.get(recipe_id)
            if not content_hash:
                raise
            recipe = await self.get_recipe(recipe_id, content_hash)

        recipe["id"] = recipe.get("id") or recipe_id
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
            if err.status in (401, 403):
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

        if not uid:
            await self.ensure_id_token(force_refresh=True)
            uid = self._uid or ""

        if not uid:
            raise FwlAuthError("Firebase sign-in did not return a user id")

        return {
            "refresh_token": self._refresh_token or refresh_token,
            "uid": uid,
            "email": email.strip(),
        }

    async def ensure_id_token(self, *, force_refresh: bool = False) -> str:
        """Return a valid Firebase ID token, refreshing if needed."""
        if (
            not force_refresh
            and self._id_token
            and self._uid
            and time.time() < self._id_token_expires_at
        ):
            return self._id_token
        if not self._refresh_token:
            raise FwlAuthError("Not authenticated")

        try:
            result = await self._request(
                "POST",
                f"{SECURE_TOKEN_URL}?key={FIREBASE_API_KEY}",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except FwlApiError as err:
            detail = str(err)
            # Only credential-invalid bodies force Magic Link reauth; bare HTTP 400
            # can be API-key / request-shape faults.
            if err.status in (401, 403) or any(
                code in detail for code in _AUTH_TOKEN_ERRORS
            ):
                raise FwlAuthError("Token refresh failed") from err
            raise

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

    # --- Firestore helpers -------------------------------------------------

    def _user_doc_url(self, *parts: str) -> str:
        base = f"{FIRESTORE_BASE}/users/{quote(self._uid)}"
        if not parts:
            return base
        path = "/".join(quote(p, safe="") for p in parts)
        return f"{base}/{path}"

    async def _firestore_list(self, collection: str) -> list[dict[str, Any]]:
        docs: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            url = f"{FIRESTORE_BASE}/users/{quote(self._uid)}/{collection}?pageSize=100"
            if page_token:
                url += f"&pageToken={quote(page_token)}"
            result = await self._firestore_request("GET", url)
            if not isinstance(result, dict):
                raise FwlApiError(
                    f"Unexpected Firestore list response for {collection}"
                )
            docs.extend(result.get("documents") or [])
            page_token = result.get("nextPageToken")
            if not page_token:
                break
        return docs

    async def _firestore_get(self, *parts: str) -> dict[str, Any] | None:
        try:
            result = await self._firestore_request(
                "GET", self._user_doc_url(*parts)
            )
        except FwlApiError as err:
            if err.status == 404:
                return None
            raise
        if result is None:
            return None
        if not isinstance(result, dict):
            raise FwlApiError(f"Unexpected Firestore document for {'/'.join(parts)}")
        return result

    async def _firestore_request(self, method: str, url: str, **kwargs: Any) -> Any:
        """Firestore call with one forced token refresh on 401."""
        await self.ensure_id_token()
        try:
            return await self._request(method, url, auth=True, **kwargs)
        except FwlApiError as err:
            if err.status in (401, 403):
                await self.ensure_id_token(force_refresh=True)
                try:
                    return await self._request(method, url, auth=True, **kwargs)
                except FwlApiError as retry_err:
                    if retry_err.status in (401, 403):
                        raise FwlAuthError(
                            "Firestore authentication failed",
                            status=retry_err.status,
                        ) from retry_err
                    raise
            raise

    async def _firestore_patch(
        self,
        *parts: str,
        fields: dict[str, Any] | None = None,
        field_paths: list[str],
        leaf_updates: dict[str, Any] | None = None,
    ) -> None:
        """PATCH a document.

        Paths listed in ``field_paths`` but absent from the encoded body are
        deleted (Firestore REST semantics). Prefer ``leaf_updates`` for nested
        leaf writes such as ``ingredients.`id`.done``.
        """
        params = "&".join(
            f"updateMask.fieldPaths={quote(path, safe='')}" for path in field_paths
        )
        url = f"{self._user_doc_url(*parts)}?{params}"
        if leaf_updates is not None:
            encoded = _build_fields_from_leaves(leaf_updates)
        else:
            encoded = {
                k: _firestore_encode(v) for k, v in (fields or {}).items()
            }
        await self._firestore_request(
            "PATCH",
            url,
            json_body={"fields": encoded},
            headers={"Content-Type": "application/json"},
        )

    async def _firestore_create(
        self, collection: str, fields: dict[str, Any]
    ) -> str:
        """Create a document under the user collection; return the new doc id."""
        url = f"{FIRESTORE_BASE}/users/{quote(self._uid)}/{collection}"
        encoded = {k: _firestore_encode(v) for k, v in fields.items()}
        result = await self._firestore_request(
            "POST",
            url,
            json_body={"fields": encoded},
            headers={"Content-Type": "application/json"},
        )
        if not isinstance(result, dict) or not result.get("name"):
            raise FwlApiError(f"Unexpected Firestore create response for {collection}")
        return str(result["name"]).rsplit("/", 1)[-1]

    async def _firestore_delete(self, *parts: str) -> None:
        await self._firestore_request("DELETE", self._user_doc_url(*parts))

    async def _require_auth(self) -> None:
        await self.ensure_id_token()
        if not self._uid:
            raise FwlAuthError("Missing user id")

    # --- Firestore weekplan ------------------------------------------------

    async def list_weekplan(
        self,
        *,
        days_back: int = 7,
        days_forward: int = 21,
        today: date | None = None,
    ) -> list[dict[str, Any]]:
        """Return planned meals as ``{date, recipe_id, title, custom}``."""
        await self._require_auth()
        anchor = today or date.today()
        catalog = await self._list_catalog_weekplan()
        custom = await self._list_custom_weekplan()

        start = anchor - timedelta(days=days_back)
        end = anchor + timedelta(days=days_forward)

        events: list[dict[str, Any]] = []
        recipe_ids: list[str] = []

        for recipe_id, day_key in catalog:
            day = _parse_fwl_day(day_key)
            if day is None or day < start or day > end:
                continue
            recipe_ids.append(recipe_id)
            events.append(
                {
                    "date": day,
                    "day_key": day_key,
                    "recipe_id": recipe_id,
                    "custom": False,
                }
            )

        for title, day_key in custom:
            day = _parse_fwl_day(day_key)
            if day is None or day < start or day > end:
                continue
            events.append(
                {
                    "date": day,
                    "day_key": day_key,
                    "recipe_id": title,
                    "title": title,
                    "custom": True,
                }
            )

        titles = await self.resolve_recipe_titles(list(dict.fromkeys(recipe_ids)))
        details = await self._recipe_details_map(list(dict.fromkeys(recipe_ids)))
        for event in events:
            rid = event.get("recipe_id")
            if event.get("custom"):
                event.setdefault("title", rid)
                event["app_url"] = None
                event["image_url"] = None
                continue
            event["title"] = titles.get(rid, rid)
            info = details.get(rid) or {}
            event["image_url"] = info.get("image_url")
            event["app_url"] = app_recipe_url(rid) if rid else None
            if info.get("preparation_time") is not None:
                event["preparation_time"] = info["preparation_time"]
            # Default yield from the recipe catalog — not stored on the weekplan.
            if info.get("servings") is not None:
                event["servings"] = info["servings"]
            if info.get("serving_type"):
                event["serving_type"] = info["serving_type"]
            if info.get("rating") is not None:
                event["rating"] = info["rating"]
            if info.get("rating_count") is not None:
                event["rating_count"] = info["rating_count"]

        events.sort(key=lambda e: (e["date"], e.get("title") or ""))
        return events

    async def _recipe_details_map(
        self, recipe_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Fetch thumb/prep metadata for catalog recipe IDs (best-effort)."""
        if not recipe_ids:
            return {}
        index = await self.get_recipe_index_map()
        ratings = await self.get_ratings_map()
        known = [
            rid
            for rid in recipe_ids
            if rid in index and is_valid_recipe_id(rid)
        ]
        out: dict[str, dict[str, Any]] = {}
        chunk_size = 20
        for i in range(0, len(known), chunk_size):
            chunk = known[i : i + chunk_size]
            try:
                recipes = await self.get_recipes(chunk)
            except FwlApiError as err:
                _LOGGER.warning("Failed to load recipe details %s: %s", chunk, err)
                continue
            for recipe in recipes:
                rid = recipe.get("id")
                if not rid:
                    continue
                thumb = _first_url(recipe.get("thumbUrls"))
                image = _first_url(recipe.get("fullUrls")) or thumb
                rating_info = ratings.get(rid) or {}
                out[rid] = {
                    "image_url": image,
                    "thumb_url": thumb,
                    "preparation_time": recipe.get("preparationTime"),
                    "servings": recipe.get("servingsNumber"),
                    "serving_type": recipe.get("servingType"),
                    "rating": rating_info.get("rating"),
                    "rating_count": rating_info.get("count"),
                }
        return out

    async def _list_catalog_weekplan(self) -> list[tuple[str, str]]:
        """Return ``(recipe_id, day_key)`` from ``weekplan/{recipeId}.dates``."""
        entries: list[tuple[str, str]] = []
        for doc in await self._firestore_list("weekplan"):
            name = doc.get("name") or ""
            recipe_id = name.rsplit("/", 1)[-1]
            fields = doc.get("fields") or {}
            dates_field = fields.get("dates")
            if not dates_field:
                continue
            decoded = _firestore_decode(dates_field)
            if not isinstance(decoded, dict):
                continue
            for day_key, enabled in decoded.items():
                if enabled is True:
                    entries.append((recipe_id, day_key))
        return entries

    async def _list_custom_weekplan(self) -> list[tuple[str, str]]:
        """Return ``(title, day_key)`` from ``weekplanCustom/{yyyyMMdd}.{title}``.

        Official app shape (addCustom/deleteCustom): one document per day, top-level
        meal titles mapped to boolean true/false.
        """
        entries: list[tuple[str, str]] = []
        for doc in await self._firestore_list("weekplanCustom"):
            name = doc.get("name") or ""
            day_key = name.rsplit("/", 1)[-1]
            if _parse_fwl_day(day_key) is None:
                # Skip legacy/incorrect docs (e.g. HA v0.3 wrote recipe-shaped docs).
                _LOGGER.debug("Ignoring non-day weekplanCustom doc %s", day_key)
                continue
            fields = {
                k: _firestore_decode(v) for k, v in (doc.get("fields") or {}).items()
            }
            for title, enabled in fields.items():
                if enabled is True:
                    entries.append((title, day_key))
        return entries

    async def set_weekplan_day(
        self,
        recipe_id: str,
        day: date,
        *,
        enabled: bool = True,
        custom: bool = False,
    ) -> None:
        """Add or remove a meal on a calendar day.

        Catalog: ``weekplan/{recipeId}.dates.{yyyyMMdd}`` — delete by omitting the
        masked field (null crashes the official app Boolean cast).
        Custom: ``weekplanCustom/{yyyyMMdd}.{title}`` — write true/false like the app.
        """
        await self._require_auth()
        day_key = day.strftime("%Y%m%d")
        if custom:
            title = recipe_id
            await self._firestore_patch(
                "weekplanCustom",
                day_key,
                fields={title: bool(enabled)},
                field_paths=[_quote_field_path(title)],
            )
            return

        path = f"dates.`{day_key}`"
        if enabled:
            await self._firestore_patch(
                "weekplan",
                recipe_id,
                leaf_updates={path: True},
                field_paths=[path],
            )
        else:
            # Mask-only delete: path in updateMask, absent from body.
            await self._firestore_patch(
                "weekplan",
                recipe_id,
                fields={},
                field_paths=[path],
            )

    # --- Shopping list -----------------------------------------------------

    async def list_shopping_items(self) -> list[dict[str, Any]]:
        """Flatten all shopping lists into todo-friendly items."""
        await self._require_auth()
        items: list[dict[str, Any]] = []
        for doc in await self._firestore_list("shoppingList"):
            recipe_id = (doc.get("name") or "").rsplit("/", 1)[-1]
            fields = {
                k: _firestore_decode(v) for k, v in (doc.get("fields") or {}).items()
            }
            list_name = fields.get("name") or recipe_id
            ingredients = fields.get("ingredients") or {}
            if not isinstance(ingredients, dict):
                continue
            for ingredient_id, raw in ingredients.items():
                if not isinstance(raw, dict):
                    continue
                # Official app may leave null tombstones; skip them.
                if raw.get("name") is None and raw.get("done") is None:
                    continue
                name = raw.get("name") or ingredient_id
                quantity = raw.get("quantity") or ""
                summary = f"{quantity} {name}".strip() if quantity else name
                if recipe_id != SHOPPING_CUSTOM_DOC and list_name:
                    summary = f"{summary} ({list_name})"
                items.append(
                    {
                        "uid": f"{recipe_id}:{ingredient_id}",
                        "recipe_id": recipe_id,
                        "ingredient_id": ingredient_id,
                        "list_name": list_name,
                        "name": name,
                        "quantity": quantity,
                        "section": raw.get("section", 0),
                        "index": raw.get("index", 0),
                        "summary": summary,
                        "done": bool(raw.get("done")),
                    }
                )
        items.sort(
            key=lambda i: (
                i["list_name"],
                i.get("section", 0),
                i.get("index", 0),
                i["summary"],
            )
        )
        return items

    async def set_shopping_item_done(
        self, recipe_id: str, ingredient_id: str, *, done: bool
    ) -> None:
        """Toggle only the ingredient's ``done`` leaf (avoids stale whole-map rewrite)."""
        await self._require_auth()
        path = f"ingredients.`{ingredient_id}`.done"
        await self._firestore_patch(
            "shoppingList",
            recipe_id,
            leaf_updates={path: done},
            field_paths=[path],
        )

    async def delete_shopping_item(self, recipe_id: str, ingredient_id: str) -> None:
        """Remove an ingredient — matches the official app (writes null)."""
        await self._require_auth()
        await self._firestore_patch(
            "shoppingList",
            recipe_id,
            fields={"ingredients": {ingredient_id: None}},
            field_paths=[f"ingredients.`{ingredient_id}`"],
        )

    # --- Favorites & notes -------------------------------------------------

    async def get_favorites(self) -> dict[str, Any]:
        """Return favorite recipe IDs and folders (with titles/images)."""
        await self._require_auth()
        user_doc = await self._firestore_get()
        favorites_map: dict[str, bool] = {}
        if user_doc:
            fields = user_doc.get("fields") or {}
            if "favorites" in fields:
                decoded = _firestore_decode(fields["favorites"])
                if isinstance(decoded, dict):
                    favorites_map = {
                        k: bool(v) for k, v in decoded.items() if v is True
                    }

        folders_raw: list[dict[str, Any]] = []
        folder_ids: set[str] = set()
        for doc in await self._firestore_list("favoriteFolder"):
            folder_id = (doc.get("name") or "").rsplit("/", 1)[-1]
            fields = {
                k: _firestore_decode(v) for k, v in (doc.get("fields") or {}).items()
            }
            recipes = fields.get("recipes") or {}
            active = (
                [rid for rid, enabled in recipes.items() if enabled]
                if isinstance(recipes, dict)
                else []
            )
            folder_ids.update(active)
            folders_raw.append(
                {
                    "id": folder_id,
                    "name": fields.get("name") or folder_id,
                    "recipe_ids": active,
                }
            )

        all_ids = list(dict.fromkeys([*favorites_map.keys(), *folder_ids]))
        titles = await self.resolve_recipe_titles(all_ids)
        details = await self._recipe_details_map(all_ids)

        def _recipe_card(rid: str) -> dict[str, Any]:
            info = details.get(rid) or {}
            return {
                "recipe_id": rid,
                "title": titles.get(rid) or rid,
                "image_url": info.get("thumb_url") or info.get("image_url"),
                "app_url": app_recipe_url(rid),
                "viewer_url": (
                    recipe_viewer_path(rid) if is_valid_recipe_id(rid) else None
                ),
                "preparation_time": info.get("preparation_time"),
                "rating": info.get("rating"),
                "rating_count": info.get("rating_count"),
            }

        folders: list[dict[str, Any]] = []
        for folder in folders_raw:
            recipes = [_recipe_card(rid) for rid in folder["recipe_ids"]]
            recipes.sort(key=lambda r: (r.get("title") or "").lower())
            folders.append(
                {
                    "id": folder["id"],
                    "name": folder["name"],
                    "count": len(recipes),
                    "recipes": recipes,
                }
            )
        folders.sort(key=lambda f: f["name"])

        uncategorized_ids = [
            rid for rid in favorites_map if rid not in folder_ids
        ]
        uncategorized = [_recipe_card(rid) for rid in uncategorized_ids]
        uncategorized.sort(key=lambda r: (r.get("title") or "").lower())

        return {
            "recipe_ids": sorted(favorites_map.keys()),
            "count": len(favorites_map),
            "folders": folders,
            "uncategorized": uncategorized,
        }

    async def get_note(self, recipe_id: str) -> str | None:
        await self._require_auth()
        doc = await self._firestore_get("note", recipe_id)
        if not doc:
            return None
        fields = doc.get("fields") or {}
        if "note" not in fields:
            return None
        value = _firestore_decode(fields["note"])
        return value if isinstance(value, str) else None

    async def create_favorite_folder(self, name: str) -> str:
        """Create an empty favorite folder; return its Firestore document id."""
        await self._require_auth()
        clean = name.strip()
        if not clean or len(clean) > 80:
            raise FwlApiError("Invalid folder name")
        if any(ch in clean for ch in ("\x00", "\n", "\r", "`")):
            raise FwlApiError("Invalid folder name")
        return await self._firestore_create(
            "favoriteFolder",
            {"name": clean, "recipes": {}},
        )

    async def delete_favorite_folder(self, folder_id: str) -> None:
        """Delete a favorite folder only when it contains no recipes."""
        await self._require_auth()
        if not is_valid_recipe_id(folder_id):
            raise FwlApiError("Invalid folder id")
        doc = await self._firestore_get("favoriteFolder", folder_id)
        if doc is None:
            raise FwlApiError("Folder not found", status=404)
        fields = {
            k: _firestore_decode(v) for k, v in (doc.get("fields") or {}).items()
        }
        recipes = fields.get("recipes") or {}
        active = (
            [rid for rid, enabled in recipes.items() if enabled]
            if isinstance(recipes, dict)
            else []
        )
        if active:
            raise FwlApiError("Folder is not empty")
        await self._firestore_delete("favoriteFolder", folder_id)

    async def move_favorite(
        self,
        recipe_id: str,
        *,
        to_folder_id: str | None,
    ) -> None:
        """Move a favorited recipe into a folder, or to uncategorized (``None``).

        Ensures the recipe stays in ``users/{uid}.favorites``. Removes it from
        every folder map, then adds it to the target folder when given.
        """
        await self._require_auth()
        if not is_valid_recipe_id(recipe_id):
            raise FwlApiError("Invalid recipe id")
        if to_folder_id is not None and not is_valid_recipe_id(to_folder_id):
            raise FwlApiError("Invalid folder id")

        # Keep in the global favorites map.
        fav_path = f"favorites.`{recipe_id}`"
        await self._firestore_patch(
            leaf_updates={fav_path: True},
            field_paths=[fav_path],
        )

        for doc in await self._firestore_list("favoriteFolder"):
            folder_id = (doc.get("name") or "").rsplit("/", 1)[-1]
            if not folder_id:
                continue
            fields = {
                k: _firestore_decode(v) for k, v in (doc.get("fields") or {}).items()
            }
            recipes = fields.get("recipes") or {}
            if not isinstance(recipes, dict) or recipe_id not in recipes:
                continue
            # Mask-only delete (omit from body) — safer than writing false/null.
            path = f"recipes.`{recipe_id}`"
            await self._firestore_patch(
                "favoriteFolder",
                folder_id,
                fields={},
                field_paths=[path],
            )

        if to_folder_id:
            target = await self._firestore_get("favoriteFolder", to_folder_id)
            if target is None:
                raise FwlApiError("Folder not found", status=404)
            path = f"recipes.`{recipe_id}`"
            await self._firestore_patch(
                "favoriteFolder",
                to_folder_id,
                leaf_updates={path: True},
                field_paths=[path],
            )

    # --- Dashboard aggregate -----------------------------------------------

    async def fetch_dashboard(
        self,
        *,
        days_back: int = 7,
        days_forward: int = 21,
        today: date | None = None,
    ) -> dict[str, Any]:
        """Fetch greeting, today recipe, and optional account data."""
        greeting = await self.morning_greeting()
        recipe = await self.today_recipe()
        recipe_id = recipe.get("id") if isinstance(recipe, dict) else None
        if recipe_id:
            rating_info = (await self.get_ratings_map()).get(recipe_id) or {}
            recipe["rating"] = rating_info.get("rating")
            recipe["ratingCount"] = rating_info.get("count")
        data: dict[str, Any] = {
            "greeting": greeting,
            "recipe": recipe,
            "weekplan": [],
            "shopping_items": [],
            "favorites": {"recipe_ids": [], "count": 0, "folders": []},
            "note": None,
            "authenticated": self.authenticated,
            "account_error": None,
        }
        if not self.authenticated:
            return data

        try:
            data["weekplan"] = await self.list_weekplan(
                days_back=days_back,
                days_forward=days_forward,
                today=today,
            )
            data["shopping_items"] = await self.list_shopping_items()
            data["favorites"] = await self.get_favorites()
            recipe_id = recipe.get("id")
            if recipe_id:
                data["note"] = await self.get_note(recipe_id)
        except FwlAuthError:
            raise
        except FwlApiError as err:
            _LOGGER.warning("Authenticated fetch failed: %s", err)
            data["account_error"] = _sanitize_error(str(err))
            data["account_stale"] = True
        return data


def _sanitize_error(message: str) -> str:
    """Strip UIDs/URLs from error strings before exposing to diagnostics."""
    message = re.sub(r"/users/[^/\s]+", "/users/<uid>", message)
    message = re.sub(r"Bearer\s+\S+", "Bearer <redacted>", message)
    return message[:200]


def _parse_fwl_day(day_key: str) -> date | None:
    try:
        return datetime.strptime(day_key, "%Y%m%d").date()
    except ValueError:
        return None


def _first_url(values: Any) -> str | None:
    if isinstance(values, list) and values:
        item = values[0]
        return item if isinstance(item, str) else None
    return None
