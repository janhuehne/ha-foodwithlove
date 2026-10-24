"""Constants for the food with love integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "foodwithlove"

CONF_LANGUAGE: Final = "language"
CONF_EMAIL: Final = "email"
CONF_REFRESH_TOKEN: Final = "refresh_token"
CONF_UID: Final = "uid"
CONF_LOGIN: Final = "login"

# Options
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_DAYS_BACK: Final = "days_back"
CONF_DAYS_FORWARD: Final = "days_forward"

DEFAULT_LANGUAGE: Final = "de"
DEFAULT_SCAN_INTERVAL_MINUTES: Final = 60
DEFAULT_SCAN_INTERVAL_AUTH_MINUTES: Final = 30
DEFAULT_DAYS_BACK: Final = 7
DEFAULT_DAYS_FORWARD: Final = 21

DEFAULT_SCAN_INTERVAL: Final = timedelta(hours=1)
DEFAULT_SCAN_INTERVAL_AUTH: Final = timedelta(minutes=30)

BASE_URL: Final = "https://food-with-love-app.web.app"
APP_RECIPE_URL: Final = "https://www.foodwithlove.de/app/?recipe={recipe_id}"
FUNCTIONS_URL: Final = (
    "https://europe-west3-food-with-love-app.cloudfunctions.net"
)
FIREBASE_API_KEY: Final = "AIzaSyBSHLwLRuE13rn5VKbcLlhPl6Sad_OXS4Y"
FIREBASE_PROJECT_ID: Final = "food-with-love-app"
FIRESTORE_BASE: Final = (
    f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}"
    "/databases/(default)/documents"
)
IDENTITY_URL: Final = "https://identitytoolkit.googleapis.com/v1"
SECURE_TOKEN_URL: Final = "https://securetoken.googleapis.com/v1/token"

USER_AGENT: Final = "HomeAssistant-foodwithlove/0.5.3"

SUPPORTED_LANGUAGES: Final = {
    "de": "Deutsch",
    "en": "English",
    "es": "Español",
    "fr": "Français",
    "it": "Italiano",
}

LOGIN_SKIP: Final = "skip"
LOGIN_MAGIC_LINK: Final = "magic_link"

SHOPPING_CUSTOM_DOC: Final = "custom"

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
ATTR_AUTHENTICATED: Final = "authenticated"
ATTR_NOTE: Final = "note"
ATTR_APP_URL: Final = "app_url"
ATTR_VIEWER_URL: Final = "viewer_url"
ATTR_FAVORITE_COUNT: Final = "favorite_count"
ATTR_FAVORITE_FOLDERS: Final = "favorite_folders"
