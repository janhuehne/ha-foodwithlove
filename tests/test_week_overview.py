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
    days = mod.build_week_overview(
        weekplan, language="de", today=today, mode="rolling"
    )
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


def test_week_overview_calendar_mon_sun():
    mod = _load_week_overview()
    today = date(2026, 10, 24)  # Saturday
    weekplan = [
        {
            "date": date(2026, 10, 20),  # Tuesday of that calendar week
            "title": "Gnocchi alla Sorrentina",
            "recipe_id": "rTi6KZH63rUZQRInqe7T",
            "custom": False,
            "app_url": "https://www.foodwithlove.de/app/?recipe=rTi6KZH63rUZQRInqe7T",
        }
    ]
    days = mod.build_week_overview(
        weekplan, language="de", today=today, mode="calendar"
    )
    assert len(days) == 7
    assert days[0]["date"] == "2026-10-19"
    assert days[0]["weekday"] == "Montag"
    assert days[5]["is_today"] is True  # Saturday
    assert days[6]["date"] == "2026-10-25"
    assert days[1]["meals"][0]["title"] == "Gnocchi alla Sorrentina"


def test_week_overview_english_labels():
    mod = _load_week_overview()
    days = mod.build_week_overview(
        [], language="en", today=date(2026, 11, 8), mode="rolling"
    )
    assert days[0]["weekday"] == "Sunday"
    assert days[0]["is_today"] is True
    assert days[6]["weekday"] == "Saturday"


def test_patch_weekplan_list_remove_and_add():
    mod = _load_week_overview()
    rid = "rTi6KZH63rUZQRInqe7T"
    weekplan = [
        {
            "date": date(2026, 11, 13),
            "day_key": "20261113",
            "recipe_id": rid,
            "title": "Gnocchi",
            "custom": False,
            "image_url": "https://example.com/g.webp",
        },
        {
            "date": date(2026, 11, 14),
            "day_key": "20261114",
            "recipe_id": "Soup",
            "title": "Soup",
            "custom": True,
        },
    ]
    removed = mod.patch_weekplan_list(
        weekplan, key=rid, day=date(2026, 11, 13), enabled=False, custom=False
    )
    assert len(removed) == 1
    assert removed[0]["custom"] is True

    moved = mod.patch_weekplan_list(
        removed, key=rid, day=date(2026, 11, 15), enabled=True, custom=False
    )
    # No template left for catalog recipe → placeholder title until refresh.
    assert any(
        e.get("recipe_id") == rid and e.get("date") == date(2026, 11, 15)
        for e in moved
    )

    with_template = mod.patch_weekplan_list(
        weekplan, key=rid, day=date(2026, 11, 15), enabled=True, custom=False
    )
    entry = next(e for e in with_template if e.get("date") == date(2026, 11, 15))
    assert entry["title"] == "Gnocchi"
    assert entry["image_url"] == "https://example.com/g.webp"
    assert len(with_template) == 3
