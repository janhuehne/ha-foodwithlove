# food with love for Home Assistant

Unofficial Home Assistant integration for **[food with love](https://www.foodwithlove.de/)**.

> Not affiliated with fwl connect GmbH. Uses a reverse-engineered public API. For personal use only — respect FWL ToS and recipe copyright.

## Features (v0.1)

| Entity | Description |
|---|---|
| `sensor.food_with_love_recipe_of_the_day` | Today’s recipe title (+ time, servings, image) |
| `sensor.food_with_love_morning_greeting` | Daily greeting text |

No login required. Polls about once per hour.

## Install

### HACS (custom repository)

1. HACS → ⋮ → **Custom repositories**
2. URL: this repo · Category: **Integration**
3. Download **food with love**
4. Restart Home Assistant
5. Settings → Devices & services → **Add integration** → *food with love*

### Manual

Copy `custom_components/foodwithlove` into your HA `config/custom_components/` folder, restart, then add the integration.

## Lovelace example

```yaml
type: markdown
content: |
  ## {{ states('sensor.food_with_love_recipe_of_the_day') }}
  {{ state_attr('sensor.food_with_love_recipe_of_the_day', 'preparation_time') }} min  
  {{ states('sensor.food_with_love_morning_greeting') }}
```

Entity IDs may vary slightly with language; check **Settings → Devices → food with love**.

## Standalone API smoke test

```bash
python3 -m pip install -r requirements.txt
python3 fwl_client.py
```

## Roadmap

- [ ] Week plan → `calendar` (Firebase Auth + Firestore)
- [ ] Shopping list → `todo`
- [ ] Favorites sensor
- [ ] Options flow (scan interval)

Technical notes: [docs/REVERSE_ENGINEERING.md](docs/REVERSE_ENGINEERING.md)
