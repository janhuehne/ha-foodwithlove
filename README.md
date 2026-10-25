# food with love for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/release/janhuehne/ha-foodwithlove.svg)](https://github.com/janhuehne/ha-foodwithlove/releases)
[![Validate](https://github.com/janhuehne/ha-foodwithlove/actions/workflows/validate.yml/badge.svg)](https://github.com/janhuehne/ha-foodwithlove/actions/workflows/validate.yml)

Unofficial Home Assistant integration for **[food with love](https://www.foodwithlove.de/)**.

> Not affiliated with fwl connect GmbH. Uses a reverse-engineered private API.
> For personal use only — respect FWL ToS and recipe copyright.

## Features

| Entity / feature | Login | Description |
|---|---|---|
| Recipe of the day | no | Title, image, prep time, servings, app + large-screen viewer link |
| Morning greeting | no | Daily greeting text |
| Week overview | Magic Link | Mon–Sun meal plan with images and smart open links |
| Week plan calendar | Magic Link | Create / delete planned meals |
| Remove from week plan | Magic Link | Service `foodwithlove.remove_weekplan_meal` + × on week card |
| Add to week plan | Magic Link | Service `foodwithlove.add_weekplan_meal` + + on favorites |
| Favorites | Magic Link | Collapsible folders (`custom:fwl-favorites-card`); move / create / delete empty |
| Favorite folders | Magic Link | Services `create_favorite_folder`, `delete_favorite_folder`, `move_favorite` |
| Shopping list todo | Magic Link | Check off / delete syncs back to FWL |
| Options | — | Poll interval, calendar window |
| Diagnostics / reauth | — | Redacted diagnostics; Magic Link when the token expires |

## Requirements

- Home Assistant **2024.12+**
- Optional: food with love account (Magic Link) for week plan, shopping list, favorites

## Install (HACS)

1. HACS → **Integrations** → search for **food with love** → Download  
2. Restart Home Assistant  
3. Settings → Devices & services → **Add integration** → **food with love**

### Custom repository (if not yet in the default store)

1. HACS → **Integrations** → ⋮ → **Custom repositories**
2. URL: `https://github.com/janhuehne/ha-foodwithlove` — category **Integration**
3. Download **food with love**, then restart and add the integration as above.

### Manual

Copy `custom_components/foodwithlove` into your HA `config/custom_components/` folder, restart, then add the integration.

## Setup

1. Choose language  
2. **Public only** or **Sign in with Magic Link**  
3. For Magic Link: enter your FWL account email → enter the 6-digit code from the mail  

Already installed without login? Open the integration → **Reconfigure** to link your account.

App deep links use `https://www.foodwithlove.de/app/?recipe=<id>` (opens in the FWL app when installed).

Full recipe on a large screen (no FWL app): `viewer_url` on the recipe-of-the-day sensor / week-overview meals points to an HA login–protected page at `/api/foodwithlove/recipe/<id>` (ingredients + steps).

The Lovelace cards open **App on mobile**, **HA viewer overlay on desktop** (with a “Neuer Tab” option).

### Calendar create tip

To add a catalog recipe, create a calendar event with `recipe_id=<id>` in the description. Without that, the summary is stored as a custom weekplan entry.

## Lovelace

Built-in cards (auto-loaded with the integration):

```yaml
type: custom:fwl-week-card
entity: sensor.food_with_love_wochenuberblick

type: custom:fwl-recipe-card
entity: sensor.food_with_love_rezept_des_tages
greeting_entity: sensor.food_with_love_morgengruss

type: custom:fwl-favorites-card
entity: sensor.food_with_love_favoriten
```

### Optional: join Cookidoo / Chefkoch favorites / week plan

Install companion integrations as needed:

- [ha-cookidoo-collections](https://github.com/janhuehne/ha-cookidoo-collections) (plus the official HA **Cookidoo** integration for shopping list / calendar)
- [ha-chefkoch-collections](https://github.com/janhuehne/ha-chefkoch-collections) (≥ 0.1.2; weekplan add is Plus-gated via `has_meal_planner`)

Then point the FWL cards at the collections sensors (`cookidoo_entity` / `chefkoch_entity` are independent):

```yaml
type: custom:fwl-week-card
entity: sensor.food_with_love_wochenuberblick
cookidoo_entity: sensor.cookidoo_collections_favoriten
chefkoch_entity: sensor.chefkoch_collections_favoriten

type: custom:fwl-favorites-card
entity: sensor.food_with_love_favoriten
cookidoo_entity: sensor.cookidoo_collections_favoriten
chefkoch_entity: sensor.chefkoch_collections_favoriten
```

Folders are merged by name; add / move / remove / create-folder actions route by recipe source.

Also useful:

- `todo.food_with_love_einkaufsliste`

Entity IDs vary with language — check **Settings → Devices → food with love**.
## Development

```bash
python3 -m pip install -r requirements.txt pytest
python3 -m pytest tests/ -q
```

Technical notes: [docs/REVERSE_ENGINEERING.md](docs/REVERSE_ENGINEERING.md)

## License

MIT — see [LICENSE](LICENSE).

Not affiliated with fwl connect GmbH / food with love.
