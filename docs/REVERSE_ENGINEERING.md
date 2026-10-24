# food with love (FWL) — reverse engineering notes

Unofficial notes from APK `com.fwl_frontend` **4.0.5**. Not affiliated with fwl connect GmbH.
Private API may change; ToS apply. Intended for a personal Home Assistant integration.

## Stack

| Layer | Detail |
|---|---|
| Backend host | `https://food-with-love-app.web.app` |
| Cloud Functions | `https://europe-west3-food-with-love-app.cloudfunctions.net` |
| Auth | Firebase Auth (Google / Apple / Magic Link) |
| User data | Cloud Firestore collection `users/{uid}/…` |
| Recipe CDN | AES-encrypted blobs over HTTPS |
| Firebase project | `food-with-love-app` |
| Android app id | `1:655843402758:android:ba71ad211a53ee84bf0f87` |

## HTTP headers (app)

```
x-platform: Android
accept-language: <locale>
x-fwl-lang: true
Authorization: Bearer <firebase_id_token>   # authenticated routes only
```

## Public API (no login)

| Method | Path | Notes |
|---|---|---|
| GET | `/today` | `{ "recipeId": "…" }` — recipe of the day |
| GET | `/api/v1/morninggreeting` | Localized greeting text |
| GET | `/api/v1/recipes/index` | `{ recipes: [{ id, h }, …] }` hash index |
| GET | `/api/v1/recipe/{id}/{h}` | **Base64(AES ciphertext)** of one recipe |
| GET | `/api/v1/recipes?ids=id1,id2` | Batch encrypted recipes |
| GET | `/api/v1/books` | Digital cookbooks (JSON) |
| GET | `/api/v1/terms` | Terms notification |
| GET | `/ratings/` | Public rating map |

Verified 2026-10-24: today → **Rotes Thai Curry**.

## Recipe encryption

```
AES/CBC/PKCS7Padding
key  = f"{MM}dontFWst{YYYY}{DD}"   # UTC calendar date, 16 ASCII bytes
     e.g. 2026-10-24 UTC → "10dontFWst202624"
IV   = first 16 bytes of ciphertext
body = remaining bytes
wire = Base64( IV || ciphertext )
plaintext = JSON Recipe or Recipe[]
```

Key rotates **daily (UTC)**. Device clock skew breaks decrypt (app logs `error_decrypt_failed`).

## Auth API

### Magic Link

Verified: `somethingbad` may be omitted (`null` in the app).

1. `POST …/v1RequestLogin` body `{ "email": "…" }`  
   → `{ "reference": "…" }` and sends a 6-digit code by email
2. `POST …/v1VerifyLogin` body `{ "reference", "code", "email" }`  
   → `{ "token": "<firebase_custom_token>" }`
3. Firebase Identity Toolkit  
   `POST …/accounts:signInWithCustomToken?key=<web_api_key>`  
   → `idToken`, `refreshToken`, `localId` (uid)
4. Refresh  
   `POST https://securetoken.googleapis.com/v1/token?key=…`  
   `grant_type=refresh_token&refresh_token=…`

Weekplan documents are keyed by **recipe ID**.  
Field `dates` is a map of `yyyyMMdd → true` (which days that recipe is planned).

### Google / Apple

Native Firebase Auth in the app; same ID token for API + Firestore.

## Authenticated REST

Requires `Authorization: Bearer <idToken>`:

- `/api/v1/entitlements`
- `/api/v1/user` (DELETE)
- `/api/v1/user/language`, `/api/v1/user/deletion-preview`
- `/api/v1/community/*`, `/api/v1/comment*`, `/api/v1/photos*`
- `/api/v1/terms/accept`, `/api/v1/report`
- subscription helpers

## Firestore (`users/{uid}`)

| Path | Purpose |
|---|---|
| `shoppingList/{listId}` | Shopping lists (`name`, `ingredients`, `portion`, `imageURL`); ingredient maps include `done`. App delete writes `null` for an ingredient key. |
| `weekplan/{recipeId}` | Field `dates: { "yyyyMMdd": true, … }` (recipe → days). **Delete a day by omitting the masked field** — do not write `null` (app casts values to Boolean and crashes). |
| `weekplanCustom/{yyyyMMdd}` | **Different shape:** one document per day; top-level keys are free-text meal titles mapped to `true`/`false` (`addCustom`/`deleteCustom`). |
| `users/{uid}` | Top-level `favorites: { recipeId: true }` map |
| `favoriteFolder/{folderId}` | Favorite folders (`name`, `recipes: { recipeId: true }`). Create via POST; delete only when `recipes` is empty. Move: strip recipe from all folder maps, then set on target (or leave uncategorized). |
| user doc field `favorites` | Map of favorited recipe ids (kept when moving between folders) |
| `note/{recipeId}` | Personal recipe notes |

Joelle’s shared weekplan UID (hardcoded in app): `kc1je2gWhhgB4b71axEVWhHZ1YF2`.

## Home Assistant mapping

| FWL feature | HA entity | Auth needed |
|---|---|---|
| Recipe of the day | `sensor` (+ attributes title, image, time) | No |
| Morning greeting | `sensor` | No |
| Week plan | `calendar` | Yes (Firestore) |
| Shopping list | `todo` | Yes (Firestore) |
| Favorites count / next cook | `sensor` | Yes |
| Notify before dinner | automation on calendar | Yes |

## Limits / risks

- Unofficial; endpoints and AES key format can change without notice.
- Recipe payloads are copyrighted; keep integrations personal / account-bound.
- Firestore security rules will reject requests without a valid Firebase Auth UID.
- Magic-link field `somethingbad` may be a bot-check token — confirm before automating login.
