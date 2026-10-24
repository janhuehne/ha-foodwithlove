"""Week-overview helpers."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_week_overview():
    path = ROOT / "custom_components/foodwithlove/week_overview.py"
    spec = importlib.util.spec_from_file_location("fwl_week_overview", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fwl_week_overview"] = mod
    spec.loader.exec_module(mod)
    return mod


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
    sat = days[5]
    assert sat["is_today"] is True
    assert sat["empty"] is True
