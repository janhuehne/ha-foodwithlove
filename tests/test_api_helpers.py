"""Unit tests for foodwithlove API helpers (no Home Assistant import)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from _pkgutil import load


@pytest.fixture(scope="module")
def api():
    load("const", "const.py")
    load("sanitize", "sanitize.py")
    return load("api", "api.py")


def test_split_field_path(api):
    assert api._split_field_path("dates.`20261203`") == ["dates", "20261203"]
    assert api._split_field_path("ingredients.`abc`.done") == [
        "ingredients",
        "abc",
        "done",
    ]


def test_build_fields_from_leaves_done(api):
    fields = api._build_fields_from_leaves({"ingredients.`abc`.done": True})
    done = fields["ingredients"]["mapValue"]["fields"]["abc"]["mapValue"]["fields"][
        "done"
    ]
    assert done == {"booleanValue": True}


def test_quote_field_path(api):
    assert api._quote_field_path("dates") == "dates"
    assert api._quote_field_path("HA Test") == "`HA Test`"


def test_parse_fwl_day(api):
    assert api._parse_fwl_day("20261020") == date(2026, 10, 20)
    assert api._parse_fwl_day("nope") is None


def test_utc_aes_key_shape(api):
    key = api.utc_aes_key(datetime(2026, 10, 24, tzinfo=timezone.utc))
    assert key == b"10dontFWst202624"


def test_app_recipe_url_const():
    const = load("const", "const.py")
    assert (
        const.APP_RECIPE_URL.format(recipe_id="abc")
        == "https://www.foodwithlove.de/app/?recipe=abc"
    )
