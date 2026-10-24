# food with love for Home Assistant

Unofficial Home Assistant integration for **[food with love](https://www.foodwithlove.de/)**.

> Not affiliated with fwl connect GmbH. Uses a reverse-engineered private API. For personal use only — respect FWL ToS and recipe copyright.

## Features (v0.3)

| Entity / feature | Login | Description |
|---|---|---|
| `sensor.*` recipe of the day | no | Today’s recipe (+ time, servings, image, personal note when logged in) |
| `sensor.*` morning greeting | no | Daily greeting |
| `sensor.*` favorites | Magic Link | Favorite count + folders |
| `calendar.*` week plan | Magic Link | Week plan (create/delete events supported) |
| `todo.*` shopping list | Magic Link | Shopping ingredients; check off / delete writes back to FWL |
| Options | — | Scan interval, calendar days back/forward |
| Diagnostics / reauth | — | Redacted diagnostics; Magic Link reauth when token expires |

## Install

### HACS (custom repository)

1. HACS → ⋮ → **Custom repositories**
2. URL: `https://github.com/janhuehne/ha-foodwithlove` · Category: **Integration**
3. Download **food with love** (branch `dev` if offered)
4. Restart Home Assistant
5. Settings → Devices & services → **Add integration** → *food with love*

### Manual

Copy `custom_components/foodwithlove` into your HA `config/custom_components/` folder, restart, then add the integration.

## Setup

1. Choose language  
2. Either **Public only** or **Sign in with Magic Link**  
3. For Magic Link: enter the email of your FWL account → enter the 6-digit code from the mail  

Already installed without login? Open the integration → **Reconfigure** to link your account.

### Calendar create tip

To add a catalog recipe, create a calendar event with `recipe_id=<id>` in the description. Without that, the event summary is stored as a custom weekplan entry.

## Lovelace example

```yaml
type: markdown
content: |
  ### {{ states('sensor.food_with_love_rezept_des_tages') }}
  {{ state_attr('sensor.food_with_love_rezept_des_tages', 'preparation_time') }} min  
  _{{ states('sensor.food_with_love_morgengruss') }}_
```

Entity IDs vary with language — check **Settings → Devices → food with love**.

## Standalone API smoke test

```bash
python3 -m pip install -r requirements.txt
python3 fwl_client.py
```

Technical notes: [docs/REVERSE_ENGINEERING.md](docs/REVERSE_ENGINEERING.md)
