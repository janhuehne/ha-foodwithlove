"""Constants for the food with love integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "foodwithlove"

CONF_LANGUAGE: Final = "language"

DEFAULT_LANGUAGE: Final = "de"
DEFAULT_SCAN_INTERVAL: Final = timedelta(hours=1)

BASE_URL: Final = "https://food-with-love-app.web.app"
USER_AGENT: Final = "HomeAssistant-foodwithlove/0.1.0"

SUPPORTED_LANGUAGES: Final = {
    "de": "Deutsch",
    "en": "English",
    "es": "Español",
    "fr": "Français",
    "it": "Italiano",
}

ATTR_RECIPE_ID: Final = "recipe_id"
ATTR_PREPARATION_TIME: Final = "preparation_time"
ATTR_SERVINGS: Final = "servings"
ATTR_SERVING_TYPE: Final = "serving_type"
ATTR_CATEGORIES: Final = "categories"
ATTR_IMAGE_URL: Final = "image_url"
ATTR_THUMB_URL: Final = "thumb_url"
ATTR_IS_PREMIUM: Final = "is_premium"
ATTR_IS_FREE: Final = "is_free"
ATTR_CONTENT: Final = "content"
ATTR_GREETING_DATE: Final = "date"
ATTR_TRANSLATIONS: Final = "translations"
