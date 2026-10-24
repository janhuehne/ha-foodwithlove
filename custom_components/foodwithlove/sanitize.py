"""Shared sanitizers for untrusted FWL recipe / URL data."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, urlparse

# Observed FWL catalog ids are alphanumeric (+ _ -); reject path tricks.
_RECIPE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

_ALLOWED_IMAGE_HOSTS = frozenset(
    {
        "storage.googleapis.com",
        "www.foodwithlove.de",
        "foodwithlove.de",
        "food-with-love-app.web.app",
        "food-with-love-app.firebaseapp.com",
    }
)

_APP_ORIGIN = "https://www.foodwithlove.de"
_APP_PATH_PREFIX = "/app/"

# Tags FWL recipe text may keep — emitted with zero attributes.
_ALLOWED_NAMES = frozenset(
    {"br", "strong", "b", "em", "i", "u", "p", "ul", "ol", "li", "span", "div"}
)
_TAG_RE = re.compile(r"</?([a-zA-Z0-9]+)(\s[^>]*)?\s*/?>", re.IGNORECASE)


def is_valid_recipe_id(recipe_id: str | None) -> bool:
    return bool(recipe_id and _RECIPE_ID_RE.fullmatch(recipe_id))


def recipe_viewer_path(recipe_id: str) -> str:
    """Relative HA path for the recipe HTML viewer (path-encoded id)."""
    if not is_valid_recipe_id(recipe_id):
        raise ValueError("invalid recipe id")
    return f"/api/foodwithlove/recipe/{quote(recipe_id, safe='')}"


def app_recipe_url(recipe_id: str) -> str | None:
    if not is_valid_recipe_id(recipe_id):
        return None
    return f"{_APP_ORIGIN}{_APP_PATH_PREFIX}?recipe={quote(recipe_id, safe='')}"


def safe_https_image_url(url: Any) -> str | None:
    """Allow https images from known FWL/CDN hosts only."""
    if not isinstance(url, str):
        return None
    raw = url.strip()
    if not raw.startswith("https://"):
        return None
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    host = parsed.hostname.lower()
    if host not in _ALLOWED_IMAGE_HOSTS and not host.endswith(
        ".googleapis.com"
    ):
        return None
    if parsed.username or parsed.password:
        return None
    return raw


def is_allowed_app_url(url: Any) -> bool:
    if not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.hostname != "www.foodwithlove.de":
        return False
    path = parsed.path or "/"
    return path == "/app" or path.startswith("/app/")


def sanitize_rich_html(value: Any) -> str:
    """Escape untrusted text; re-emit a tiny tag allowlist with no attributes."""
    import html as html_mod

    if value is None:
        return ""
    raw = str(value)
    if not raw.strip():
        return ""

    placeholders: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1).lower()
        if name not in _ALLOWED_NAMES:
            return ""
        token = match.group(0)
        closing = token.lstrip().startswith("</")
        if name == "br":
            cleaned = "<br>"
        elif closing:
            cleaned = f"</{name}>"
        else:
            cleaned = f"<{name}>"
        placeholders.append(cleaned)
        return f"\x00{len(placeholders) - 1}\x00"

    kept = _TAG_RE.sub(_replace, raw)
    # Drop any remaining angle-bracket junk, then escape.
    kept = re.sub(r"<[^>]*>", "", kept)
    escaped = html_mod.escape(kept)
    for idx, tag in enumerate(placeholders):
        escaped = escaped.replace(f"\x00{idx}\x00", tag)
    return escaped


def sanitize_error_detail(detail: str, *, limit: int = 120) -> str:
    detail = re.sub(r"Bearer\s+\S+", "Bearer <redacted>", detail)
    detail = re.sub(r"/users/[^/\s\"']+", "/users/<uid>", detail)
    detail = re.sub(r"[\x00-\x1f]+", " ", detail)
    return detail[:limit]
