#!/usr/bin/env python3
"""Live smoke test for 0.3.0 dashboard APIs (uses .fwl_tokens.json)."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import ssl
import sys
from datetime import date, timedelta
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pkg = "custom_components.foodwithlove"
_load(f"{pkg}.const", ROOT / "custom_components/foodwithlove/const.py")
api = _load(f"{pkg}.api", ROOT / "custom_components/foodwithlove/api.py")


async def main() -> None:
    tok = json.loads((ROOT / ".fwl_tokens.json").read_text())
    ctx = ssl.create_default_context()
    # Some local networks MITM TLS; HA itself uses the system trust store.
    if "--insecure" in sys.argv:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    connector = aiohttp.TCPConnector(ssl=ctx)
    async with aiohttp.ClientSession(connector=connector) as session:
        client = api.FwlApiClient(
            session,
            language="de",
            refresh_token=tok["refresh_token"],
            uid=tok["uid"],
        )
        data = await client.fetch_dashboard(days_back=3, days_forward=14)
        recipe = data.get("recipe") or {}
        favorites = data.get("favorites") or {}
        print("authenticated:", data.get("authenticated"))
        print(
            "today:",
            recipe.get("title"),
            recipe.get("id") or recipe.get("_today_recipe_id"),
        )
        print("note:", repr(data.get("note")))
        print("weekplan:", len(data.get("weekplan") or []))
        for e in (data.get("weekplan") or [])[:5]:
            print(" ", e["date"], e.get("title"), e.get("recipe_id"))
        print("shopping:", len(data.get("shopping_items") or []))
        print(
            "favorites:",
            favorites.get("count"),
            "folders:",
            len(favorites.get("folders") or []),
        )

        recipe_id = recipe.get("id") or recipe.get("_today_recipe_id")
        if recipe_id:
            test_day = date.today() + timedelta(days=40)
            print("weekplan write test:", recipe_id, test_day)
            await client.set_weekplan_day(recipe_id, test_day, enabled=True)
            events = await client.list_weekplan(days_back=0, days_forward=45)
            found = [
                e
                for e in events
                if e["recipe_id"] == recipe_id and e["date"] == test_day
            ]
            print("  after add:", bool(found))
            await client.set_weekplan_day(recipe_id, test_day, enabled=False)
            events = await client.list_weekplan(days_back=0, days_forward=45)
            found = [
                e
                for e in events
                if e["recipe_id"] == recipe_id and e["date"] == test_day
            ]
            print("  after remove:", bool(found))

        if client.refresh_token != tok["refresh_token"]:
            tok["refresh_token"] = client.refresh_token
            (ROOT / ".fwl_tokens.json").write_text(json.dumps(tok, indent=2) + "\n")
            print("tokens updated")


if __name__ == "__main__":
    asyncio.run(main())
