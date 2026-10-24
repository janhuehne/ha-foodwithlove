"""Pure helpers for the Mon–Sun week overview (no Home Assistant imports)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

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
) -> list[dict[str, Any]]:
    """Build Mon–Sun overview matching the FWL app Wochenüberblick."""
    monday = today - timedelta(days=today.weekday())
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
                f"/api/foodwithlove/recipe/{recipe_id}" if recipe_id else None
            ),
            "preparation_time": item.get("preparation_time"),
            "servings": item.get("servings"),
            "serving_type": item.get("serving_type"),
            "rating": item.get("rating"),
            "rating_count": item.get("rating_count"),
        }
        by_day.setdefault(day, []).append(meal)

    weekdays = _WEEKDAYS_DE if language == "de" else _WEEKDAYS_EN
    days: list[dict[str, Any]] = []
    for offset in range(7):
        day = monday + timedelta(days=offset)
        meals = by_day.get(day, [])
        days.append(
            {
                "date": day.isoformat(),
                "weekday": weekdays[offset],
                "label": _day_label(day, weekdays[offset], language),
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
