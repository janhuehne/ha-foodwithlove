"""Week-overview helpers."""

from __future__ import annotations

from datetime import date

from _pkgutil import load


def _load_week_overview():
    load("sanitize", "sanitize.py")
    return load("week_overview", "week_overview.py")


def test_week_overview_matches_app_shape():
    mod = _load_week_overview()
    weekplan = [
        {
            "date": date(2026, 10, 20),
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
        weekplan, language="de", today=date(2026, 10, 24)
    )
    assert len(days) == 7
    assert days[0]["weekday"] == "Montag"
    assert days[0]["empty"] is True
    tue = days[1]
    assert tue["label"] == "Dienstag 20. Oktober"
    assert tue["meals"][0]["title"] == "Gnocchi alla Sorrentina"
    assert tue["meals"][0]["app_url"].endswith("rTi6KZH63rUZQRInqe7T")
    assert tue["meals"][0]["viewer_url"] == (
        "/api/foodwithlove/recipe/rTi6KZH63rUZQRInqe7T"
    )
    assert tue["meals"][0]["servings"] == 4
    assert tue["meals"][0]["serving_type"] == "Portionen"
    assert tue["meals"][0]["date"] == "2026-10-20"
    assert tue["meals"][0]["rating"] == 4.5
    assert tue["meals"][0]["rating_count"] == 21
    sat = days[5]
    assert sat["is_today"] is True
    assert sat["empty"] is True
