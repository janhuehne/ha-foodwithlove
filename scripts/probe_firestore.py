#!/usr/bin/env python3
import asyncio
import json
from pathlib import Path
from urllib.parse import quote

import aiohttp

tok = json.loads(Path(".fwl_tokens.json").read_text())
API_KEY = "AIzaSyBSHLwLRuE13rn5VKbcLlhPl6Sad_OXS4Y"
UID = tok["uid"]
BASE = f"https://firestore.googleapis.com/v1/projects/food-with-love-app/databases/(default)/documents"


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"https://securetoken.googleapis.com/v1/token?key={API_KEY}",
            data={
                "grant_type": "refresh_token",
                "refresh_token": tok["refresh_token"],
            },
        ) as resp:
            tr = await resp.json()
            id_token = tr["id_token"]
        headers = {"Authorization": f"Bearer {id_token}"}

        for coll in ("shoppingList", "favoriteFolder", "note"):
            async with session.get(
                f"{BASE}/users/{quote(UID)}/{coll}?pageSize=3", headers=headers
            ) as resp:
                body = await resp.json()
                docs = body.get("documents") or []
                print(f"\n=== {coll} n={len(docs)} ===")
                for doc in docs[:2]:
                    name = doc.get("name", "").rsplit("/", 1)[-1]
                    print("DOC", name)
                    print(
                        json.dumps(doc.get("fields") or {}, indent=2, ensure_ascii=False)[
                            :2500
                        ]
                    )


asyncio.run(main())
