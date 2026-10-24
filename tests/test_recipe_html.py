"""Recipe HTML viewer helpers."""

from __future__ import annotations

from _pkgutil import load

# Minimal FWL-shaped recipe (do not depend on gitignored sample_*.json).
_SAMPLE_RECIPE = {
    "title": "Pflaumen-Haselnuss-Kuchen mit Baiser",
    "preparationTime": 75,
    "servingsNumber": 12,
    "servingType": "Stücke",
    "rating": 4.5,
    "ratingCount": 46,
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
    load("sanitize", "sanitize.py")
    return load("recipe_html", "recipe_html.py")


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
    assert "★ 4.5 (46)" in html
    assert "onclick" not in html


def test_render_strips_handler_attributes_from_rich_text():
    mod = _load_recipe_html()
    recipe = {
        **_SAMPLE_RECIPE,
        "content": '<span onclick="alert(1)">hi</span>',
        "tip": '<div onmouseover="x()">tip</div>',
    }
    html = mod.render_recipe_html(recipe, language="de")
    assert "onclick" not in html
    assert "onmouseover" not in html
    assert "<span>hi</span>" in html
