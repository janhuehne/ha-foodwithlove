"""Recipe HTML viewer helpers."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_recipe_html():
    path = ROOT / "custom_components/foodwithlove/recipe_html.py"
    spec = importlib.util.spec_from_file_location("fwl_recipe_html", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fwl_recipe_html"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_recipe_viewer_path():
    mod = _load_recipe_html()
    assert mod.recipe_viewer_path("abc") == "/api/foodwithlove/recipe/abc"


def test_render_recipe_html_includes_ingredients_and_steps():
    mod = _load_recipe_html()
    sample = json.loads((ROOT / "sample_recipe.json").read_text(encoding="utf-8"))
    html = mod.render_recipe_html(sample, language="de")
    assert "Pflaumen-Haselnuss-Kuchen" in html
    assert "Zutaten" in html
    assert "große Pflaumen" in html
    assert "Zubereitung" in html
    assert "175°C" in html
    assert 'data-panel="pot"' in html
