"""Recipe HTML viewer helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Minimal FWL-shaped recipe (do not depend on gitignored sample_*.json).
_SAMPLE_RECIPE = {
    "title": "Pflaumen-Haselnuss-Kuchen mit Baiser",
    "preparationTime": 75,
    "servingsNumber": 12,
    "servingType": "Stücke",
    "ingredients": [
        {
            "type": "Basis",
            "ingredients": [
                {"unit": "", "quantity": "5", "name": "große Pflaumen"},
            ],
        }
    ],
    "steps": [
        {
            "instruction": (
                "Den Backofen auf <strong>175°C Ober-Unterhitze</strong> vorheizen."
            ),
            "stepIngredients": [],
        }
    ],
    "potSteps": [
        {
            "instruction": "Teig im Topf verrühren.",
            "stepIngredients": [],
        }
    ],
}


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
    html = mod.render_recipe_html(_SAMPLE_RECIPE, language="de")
    assert "Pflaumen-Haselnuss-Kuchen" in html
    assert "Zutaten" in html
    assert "große Pflaumen" in html
    assert "Zubereitung" in html
    assert "175°C" in html
    assert 'data-panel="pot"' in html
    assert 'id="servings-ctrl"' in html
    assert 'data-qty="5"' in html
    assert "const BASE = 12.0" in html or "const BASE = 12" in html
