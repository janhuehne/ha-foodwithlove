# food with love for Home Assistant

Unofficial Home Assistant integration for **[food with love](https://www.foodwithlove.de/)**.

> Not affiliated with fwl connect GmbH. Uses a reverse-engineered private API. For personal use only — respect FWL ToS and recipe copyright.

## Features (v0.2)

| Entity | Login | Description |
|---|---|---|
| `sensor.*_recipe_of_the_day` | no | Today’s recipe (+ time, servings, image) |
| `sensor.*_morning_greeting` | no | Daily greeting |
| `calendar.*_week_plan` | Magic Link | Your week plan from the app |

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

## Roadmap

- [x] Recipe of the day + greeting
- [x] Magic Link auth
- [x] Week plan → calendar
- [ ] Shopping list → `todo`
- [ ] Favorites sensor
- [ ] Options flow (scan interval)

Technical notes: [docs/REVERSE_ENGINEERING.md](docs/REVERSE_ENGINEERING.md)
