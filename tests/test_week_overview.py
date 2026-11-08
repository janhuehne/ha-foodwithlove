"""Week-overview helpers."""

from __future__ import annotations

from datetime import date

from _pkgutil import load


def _load_week_overview():
    load("sanitize", "sanitize.py")
    return load("week_overview", "week_overview.py")


def test_week_overview_rolling_seven_days():
    mod = _load_week_overview()
    # Saturday 24 Oct 2026 — rolling window starts today, not Monday.
    today = date(2026, 10, 24)
    weekplan = [
        {
            "date": date(2026, 10, 25),
            "title": "Gnocchi alla Sorrentina",
            "recipe_id": "rTi6KZH63rUZQRInqe7T",
            "custom": False,
            "image_url": "https://example.com/g.webp",
            "app_url": "https://www.foodwithlove.de/app/?recipe=rTi6KZH63rUZQRInqe7T",
            "preparation_time": 30,
            "servings": 4,
            "serving_type": "Portionen",
            "rating": 4.5,
            "rating_count": 21,
        }
    ]
    days = mod.build_week_overview(weekplan, language="de", today=today)
    assert len(days) == 7
    assert days[0]["date"] == "2026-10-24"
    assert days[0]["weekday"] == "Samstag"
    assert days[0]["is_today"] is True
    assert days[0]["empty"] is True
    assert days[6]["date"] == "2026-10-30"
    assert days[6]["weekday"] == "Freitag"
    sun = days[1]
    assert sun["label"] == "Sonntag 25. Oktober"
    assert sun["meals"][0]["title"] == "Gnocchi alla Sorrentina"
    assert sun["meals"][0]["app_url"].endswith("rTi6KZH63rUZQRInqe7T")
    assert sun["meals"][0]["viewer_url"] == (
        "/api/foodwithlove/recipe/rTi6KZH63rUZQRInqe7T"
    )
    assert sun["meals"][0]["servings"] == 4
    assert sun["meals"][0]["serving_type"] == "Portionen"
    assert sun["meals"][0]["date"] == "2026-10-25"
    assert sun["meals"][0]["rating"] == 4.5
    assert sun["meals"][0]["rating_count"] == 21


def test_week_overview_english_labels():
    mod = _load_week_overview()
    days = mod.build_week_overview([], language="en", today=date(2026, 11, 8))
    assert days[0]["weekday"] == "Sunday"
    assert days[0]["is_today"] is True
    assert days[6]["weekday"] == "Saturday"
