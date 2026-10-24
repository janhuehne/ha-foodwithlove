"""Sanitizer / XSS hardening tests."""

from __future__ import annotations

from _pkgutil import load


def _load():
    return load("sanitize", "sanitize.py")


def test_rich_strips_event_handler_attributes():
    mod = _load()
    out = mod.sanitize_rich_html(
        'Hello <span onclick="alert(1)" onmouseover="x()">world</span>!'
    )
    assert "onclick" not in out
    assert "onmouseover" not in out
    assert "<span>" in out
    assert "</span>" in out
    assert "world" in out


def test_rich_escapes_script_and_keeps_strong():
    mod = _load()
    out = mod.sanitize_rich_html(
        '<script>alert(1)</script><strong>ok</strong><img src=x onerror=alert(1)>'
    )
    assert "<script>" not in out
    assert "onerror" not in out
    assert "<strong>ok</strong>" in out
    assert "<img" not in out


def test_recipe_id_and_viewer_path():
    mod = _load()
    assert mod.is_valid_recipe_id("rTi6KZH63rUZQRInqe7T")
    assert not mod.is_valid_recipe_id("../api/states")
    assert not mod.is_valid_recipe_id("a/b")
    assert not mod.is_valid_recipe_id("a\\b")
    path = mod.recipe_viewer_path("abc_12-3")
    assert path == "/api/foodwithlove/recipe/abc_12-3"


def test_image_and_app_url_allowlist():
    mod = _load()
    assert mod.safe_https_image_url(
        "https://storage.googleapis.com/food-with-love-app.appspot.com/x.webp"
    )
    assert mod.safe_https_image_url("http://evil.test/x.png") is None
    assert mod.safe_https_image_url("javascript:alert(1)") is None
    assert mod.is_allowed_app_url(
        "https://www.foodwithlove.de/app/?recipe=abc"
    )
    assert not mod.is_allowed_app_url("https://evil.test/app/?recipe=abc")
    assert not mod.is_allowed_app_url("javascript:alert(1)")
