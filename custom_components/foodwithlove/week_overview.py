"""Pure helpers for the week overview (no Home Assistant imports)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

from .sanitize import is_valid_recipe_id, recipe_viewer_path

WeekMode = Literal["rolling", "calendar"]


def _coerce_weekplan_day(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value) >= 10:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def patch_weekplan_list(
    weekplan: list[dict[str, Any]],
    *,
    key: str,
    day: date,
    enabled: bool,
    custom: bool,
) -> list[dict[str, Any]]:
    """Return a new weekplan list with ``key`` added/removed on ``day``.

    Used after a successful Firestore write so sensors can update without
    waiting for a full dashboard refetch.
    """
    day_key = day.strftime("%Y%m%d")

    def matches(item: dict[str, Any]) -> bool:
        item_day = _coerce_weekplan_day(item.get("date"))
        if item_day != day:
            return False
        if custom:
            return bool(item.get("custom")) and (
                item.get("title") == key or item.get("recipe_id") == key
            )
        return (not item.get("custom")) and item.get("recipe_id") == key

    if not enabled:
        return [item for item in weekplan if not matches(item)]

    if any(matches(item) for item in weekplan):
        return list(weekplan)

    template = next(
        (
            item
            for item in weekplan
            if bool(item.get("custom")) == custom
            and (
                (
                    custom
                    and (item.get("title") == key or item.get("recipe_id") == key)
                )
                or ((not custom) and item.get("recipe_id") == key)
            )
        ),
        None,
    )
    if template:
        entry = {**template, "date": day, "day_key": day_key}
    elif custom:
        entry = {
            "date": day,
            "day_key": day_key,
            "recipe_id": key,
            "title": key,
            "custom": True,
            "app_url": None,
            "image_url": None,
        }
    else:
        entry = {
            "date": day,
            "day_key": day_key,
            "recipe_id": key,
            "title": key,
            "custom": False,
        }

    updated = list(weekplan)
    updated.append(entry)
    updated.sort(
        key=lambda e: (
            _coerce_weekplan_day(e.get("date")) or date.min,
            str(e.get("title") or ""),
        )
    )
    return updated

_WEEKDAYS_DE = (
    "Montag",
    "Dienstag",
    "Mittwoch",
    "Donnerstag",
    "Freitag",
    "Samstag",
    "Sonntag",
)
_WEEKDAYS_EN = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


def build_week_overview(
    weekplan: list[dict[str, Any]],
    *,
    language: str,
    today: date,
    mode: WeekMode = "rolling",
) -> list[dict[str, Any]]:
    """Build a 7-day overview.

    ``rolling`` — today … today+6
    ``calendar`` — Monday … Sunday of the calendar week containing ``today``
    """
    by_day: dict[date, list[dict[str, Any]]] = {}
    for item in weekplan:
        day = item.get("date")
        if not isinstance(day, date):
            continue
        title = item.get("title") or item.get("recipe_id")
        if not title:
            continue
        recipe_id = None if item.get("custom") else item.get("recipe_id")
        meal = {
            "title": title,
            "date": day.isoformat(),
            "recipe_id": recipe_id,
            "custom": bool(item.get("custom")),
            "image_url": item.get("image_url"),
            "app_url": item.get("app_url"),
            "viewer_url": (
                recipe_viewer_path(recipe_id)
                if recipe_id and is_valid_recipe_id(recipe_id)
                else None
            ),
            "preparation_time": item.get("preparation_time"),
            "servings": item.get("servings"),
            "serving_type": item.get("serving_type"),
            "rating": item.get("rating"),
            "rating_count": item.get("rating_count"),
        }
        by_day.setdefault(day, []).append(meal)

    weekdays = _WEEKDAYS_DE if language == "de" else _WEEKDAYS_EN
    if mode == "calendar":
        start = today - timedelta(days=today.weekday())
    else:
        start = today

    days: list[dict[str, Any]] = []
    for offset in range(7):
        day = start + timedelta(days=offset)
        meals = by_day.get(day, [])
        weekday = weekdays[day.weekday()]
        days.append(
            {
                "date": day.isoformat(),
                "weekday": weekday,
                "label": _day_label(day, weekday, language),
                "meals": meals,
                "is_today": day == today,
                "empty": not meals,
            }
        )
    return days


def _day_label(day: date, weekday: str, language: str) -> str:
    if language == "de":
        months = (
            "Januar",
            "Februar",
            "März",
            "April",
            "Mai",
            "Juni",
            "Juli",
            "August",
            "September",
            "Oktober",
            "November",
            "Dezember",
        )
        return f"{weekday} {day.day}. {months[day.month - 1]}"
    return f"{weekday} {day.strftime('%d %b')}"
