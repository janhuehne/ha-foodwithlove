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
    SHOPPING_CUSTOM_DOC,
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

        # Identity Toolkit often omits localId on custom-token sign-in;
        # force a refresh — that response always includes user_id.
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
            detail = str(err).lower()
            if any(
                token in detail
                for token in (
                    "invalid_grant",
                    "token has been expired",
                    "invalid refresh",
                    "http 400",
                    "http 401",
                    "http 403",
                )
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
            result = await self._request("GET", url, auth=True)
            if not isinstance(result, dict):
                break
            docs.extend(result.get("documents") or [])
            page_token = result.get("nextPageToken")
            if not page_token:
                break
        return docs

    async def _firestore_get(self, *parts: str) -> dict[str, Any] | None:
        try:
            result = await self._request(
                "GET", self._user_doc_url(*parts), auth=True
            )
        except FwlApiError as err:
            if "HTTP 404" in str(err):
                return None
            raise
        return result if isinstance(result, dict) else None

    async def _firestore_patch(
        self,
        *parts: str,
        fields: dict[str, Any],
        field_paths: list[str],
    ) -> None:
        params = "&".join(
            f"updateMask.fieldPaths={quote(path, safe='')}" for path in field_paths
        )
        url = f"{self._user_doc_url(*parts)}?{params}"
        await self._request(
            "PATCH",
            url,
            json_body={"fields": {k: _firestore_encode(v) for k, v in fields.items()}},
            auth=True,
            headers={"Content-Type": "application/json"},
        )

    async def _require_auth(self) -> None:
        await self.ensure_id_token()
        if not self._uid:
            raise FwlAuthError("Missing user id")

    # --- Firestore weekplan ------------------------------------------------

    async def list_weekplan(
        self, *, days_back: int = 7, days_forward: int = 21
    ) -> list[dict[str, Any]]:
        """Return planned meals as ``{date, recipe_id, title, custom}``."""
        await self._require_auth()
        catalog = await self._list_weekplan_entries("weekplan")
        custom = await self._list_weekplan_entries("weekplanCustom")

        start = date.today() - timedelta(days=days_back)
        end = date.today() + timedelta(days=days_forward)

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

        for recipe_id, day_key in custom:
            day = _parse_fwl_day(day_key)
            if day is None or day < start or day > end:
                continue
            events.append(
                {
                    "date": day,
                    "day_key": day_key,
                    "recipe_id": recipe_id,
                    "title": recipe_id,
                    "custom": True,
                }
            )

        titles = await self.resolve_recipe_titles(list(dict.fromkeys(recipe_ids)))
        for event in events:
            if not event.get("custom"):
                event["title"] = titles.get(event["recipe_id"], event["recipe_id"])

        events.sort(key=lambda e: (e["date"], e.get("title") or ""))
        return events

    async def _list_weekplan_entries(
        self, collection: str
    ) -> list[tuple[str, str]]:
        entries: list[tuple[str, str]] = []
        for doc in await self._firestore_list(collection):
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
                if enabled:
                    entries.append((recipe_id, day_key))
        return entries

    async def set_weekplan_day(
        self,
        recipe_id: str,
        day: date,
        *,
        enabled: bool = True,
        custom: bool = False,
    ) -> None:
        """Add or remove a recipe on a calendar day."""
        await self._require_auth()
        day_key = day.strftime("%Y%m%d")
        collection = "weekplanCustom" if custom else "weekplan"
        # False → delete the day key (null) so the meal disappears cleanly.
        value: bool | None = True if enabled else None
        await self._firestore_patch(
            collection,
            recipe_id,
            fields={"dates": {day_key: value}},
            field_paths=[f"dates.`{day_key}`"],
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
                        "raw": raw,
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
        self, recipe_id: str, ingredient_id: str, *, done: bool, raw: dict[str, Any]
    ) -> None:
        """Toggle an ingredient's done flag (merge write like the app)."""
        await self._require_auth()
        payload = dict(raw)
        payload["done"] = done
        await self._firestore_patch(
            "shoppingList",
            recipe_id,
            fields={"ingredients": {ingredient_id: payload}},
            field_paths=[f"ingredients.`{ingredient_id}`"],
        )

    async def delete_shopping_item(self, recipe_id: str, ingredient_id: str) -> None:
        """Remove an ingredient from a shopping list document."""
        await self._require_auth()
        await self._firestore_patch(
            "shoppingList",
            recipe_id,
            fields={"ingredients": {ingredient_id: None}},
            field_paths=[f"ingredients.`{ingredient_id}`"],
        )

    # --- Favorites & notes -------------------------------------------------

    async def get_favorites(self) -> dict[str, Any]:
        """Return favorite recipe IDs and folders."""
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

        folders: list[dict[str, Any]] = []
        for doc in await self._firestore_list("favoriteFolder"):
            folder_id = (doc.get("name") or "").rsplit("/", 1)[-1]
            fields = {
                k: _firestore_decode(v) for k, v in (doc.get("fields") or {}).items()
            }
            recipes = fields.get("recipes") or {}
            active = [
                rid
                for rid, enabled in recipes.items()
                if enabled
            ] if isinstance(recipes, dict) else []
            folders.append(
                {
                    "id": folder_id,
                    "name": fields.get("name") or folder_id,
                    "recipe_ids": active,
                    "count": len(active),
                }
            )
        folders.sort(key=lambda f: f["name"])
        return {
            "recipe_ids": sorted(favorites_map.keys()),
            "count": len(favorites_map),
            "folders": folders,
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

    async def set_note(self, recipe_id: str, note: str) -> None:
        await self._require_auth()
        await self._firestore_patch(
            "note",
            recipe_id,
            fields={"note": note},
            field_paths=["note"],
        )

    # --- Dashboard aggregate -----------------------------------------------

    async def fetch_dashboard(
        self,
        *,
        days_back: int = 7,
        days_forward: int = 21,
    ) -> dict[str, Any]:
        """Fetch greeting, today recipe, and optional account data."""
        greeting = await self.morning_greeting()
        recipe = await self.today_recipe()
        data: dict[str, Any] = {
            "greeting": greeting,
            "recipe": recipe,
            "weekplan": [],
            "shopping_items": [],
            "favorites": {"recipe_ids": [], "count": 0, "folders": []},
            "note": None,
            "authenticated": self.authenticated,
        }
        if not self.authenticated:
            return data

        try:
            data["weekplan"] = await self.list_weekplan(
                days_back=days_back, days_forward=days_forward
            )
            data["shopping_items"] = await self.list_shopping_items()
            data["favorites"] = await self.get_favorites()
            recipe_id = recipe.get("id") or recipe.get("_today_recipe_id")
            if recipe_id:
                data["note"] = await self.get_note(recipe_id)
        except FwlAuthError:
            raise
        except FwlApiError as err:
            _LOGGER.warning("Authenticated fetch failed: %s", err)
            data["auth_error"] = str(err)
        return data


def _parse_fwl_day(day_key: str) -> date | None:
    try:
        return datetime.strptime(day_key, "%Y%m%d").date()
    except ValueError:
        return None
