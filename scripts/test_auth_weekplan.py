#!/usr/bin/env python3
"""Interactive smoke test: Magic Link → Firebase → weekplan.

Usage:
  python3 scripts/test_auth_weekplan.py
  python3 scripts/test_auth_weekplan.py you@example.com
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Import client without Home Assistant package init
import importlib.util


def _load_api():
    const_spec = importlib.util.spec_from_file_location(
        "fwl_const", ROOT / "custom_components/foodwithlove/const.py"
    )
    const_mod = importlib.util.module_from_spec(const_spec)
    sys.modules["fwl_const"] = const_mod
    const_spec.loader.exec_module(const_mod)

    # Fake package for relative imports in api.py
    import types

    pkg = types.ModuleType("custom_components")
    fwl = types.ModuleType("custom_components.foodwithlove")
    fwl.const = const_mod
    sys.modules["custom_components"] = pkg
    sys.modules["custom_components.foodwithlove"] = fwl
    sys.modules["custom_components.foodwithlove.const"] = const_mod

    api_spec = importlib.util.spec_from_file_location(
        "custom_components.foodwithlove.api",
        ROOT / "custom_components/foodwithlove/api.py",
    )
    api_mod = importlib.util.module_from_spec(api_spec)
    api_mod.__package__ = "custom_components.foodwithlove"
    sys.modules[api_spec.name] = api_mod
    api_spec.loader.exec_module(api_mod)
    return api_mod


async def main() -> None:
    api = _load_api()
    email = (sys.argv[1] if len(sys.argv) > 1 else input("FWL email: ")).strip()
    if not email or "@" not in email:
        raise SystemExit("Need a valid email")

    async with aiohttp.ClientSession() as session:
        client = api.FwlApiClient(session, language="de")

        print("1) Public today…")
        recipe = await client.today_recipe()
        print(f"   → {recipe.get('title')}")

        print(f"2) Request Magic Link for {email}…")
        reference = await client.request_magic_link(email)
        print(f"   → reference={reference}")
        print("   Check your inbox for a 6-digit code.")

        code = input("3) Enter code: ").strip()
        print("4) Verify + Firebase sign-in…")
        tokens = await client.verify_magic_link(
            email=email, reference=reference, code=code
        )
        print(f"   → uid={tokens['uid']}")

        out = ROOT / ".fwl_tokens.json"
        out.write_text(
            json.dumps(
                {
                    "email": tokens["email"],
                    "uid": tokens["uid"],
                    "refresh_token": tokens["refresh_token"],
                },
                indent=2,
            )
            + "\n"
        )
        print(f"   → saved {out} (gitignored)")

        print("5) Fetch weekplan…")
        events = await client.list_weekplan()
        if not events:
            print("   → (empty — no planned meals in range)")
        for event in events:
            kind = "custom" if event.get("custom") else "recipe"
            print(
                f"   → {event['date']} | {event.get('title')} [{kind}]"
            )

        print("OK — auth + weekplan work.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None
