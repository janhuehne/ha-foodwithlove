"""Render a full FWL recipe as a large-screen HTML page."""

from __future__ import annotations

import html
import json
from typing import Any

from .sanitize import (
    recipe_viewer_path as _safe_viewer_path,
    safe_https_image_url,
    sanitize_rich_html,
)


def recipe_viewer_path(recipe_id: str) -> str:
    """Relative HA path for the recipe HTML viewer."""
    return _safe_viewer_path(recipe_id)


def render_recipe_html(recipe: dict[str, Any], *, language: str = "de") -> str:
    """Build a self-contained HTML document for kitchen / wall displays.

    Portion scaling is client-side (same idea as the FWL app): scale each
    ingredient quantity by desiredServings / baseServings. Nothing is stored.
    """
    title = _text(recipe.get("title") or "Rezept")
    de = language == "de"
    prep = recipe.get("preparationTime")
    raw_servings = recipe.get("servingsNumber")
    try:
        base_servings = float(raw_servings) if raw_servings is not None else 0.0
    except (TypeError, ValueError):
        base_servings = 0.0
    if base_servings <= 0:
        base_servings = 1.0
    serving_type = _text(
        recipe.get("servingType") or ("Portionen" if de else "servings")
    )
    meta_bits: list[str] = []
    if prep:
        meta_bits.append(f"{prep} min")
    rating = recipe.get("rating")
    rating_count = recipe.get("ratingCount")
    if rating is not None:
        votes = f" ({rating_count})" if rating_count is not None else ""
        meta_bits.append(f"★ {rating}{votes}")
    meta = " · ".join(meta_bits)

    image = safe_https_image_url(
        _first_url(recipe.get("fullUrls")) or _first_url(recipe.get("thumbUrls"))
    )
    image_html = (
        f'<img class="hero" src="{html.escape(image, quote=True)}" alt="" '
        f'referrerpolicy="no-referrer">'
        if image
        else ""
    )

    intro = sanitize_rich_html(recipe.get("content"))
    tip = sanitize_rich_html(recipe.get("tip") or recipe.get("potTip"))
    ingredients_html = _ingredients_block(recipe.get("ingredients") or [], de=de)
    steps = recipe.get("steps") or []
    pot_steps = recipe.get("potSteps") or []
    steps_html = _steps_block(steps, heading=("Zubereitung" if de else "Steps"))
    pot_html = _steps_block(
        pot_steps,
        heading=("Ohne Thermomix" if de else "Without Thermomix"),
    )

    show_toggle = bool(steps and pot_steps)
    tabs = ""
    if show_toggle:
        tabs = f"""
        <div class="tabs" role="tablist">
          <button type="button" class="tab active" data-panel="thermo">
            {"Thermomix" if de else "Thermomix"}
          </button>
          <button type="button" class="tab" data-panel="pot">
            {"Topf / Ofen" if de else "Pot / oven"}
          </button>
        </div>
        """
        steps_section = f"""
        <section id="panel-thermo" class="panel active">{steps_html}</section>
        <section id="panel-pot" class="panel">{pot_html}</section>
        """
    elif pot_steps and not steps:
        steps_section = f"<section class=\"panel active\">{pot_html}</section>"
    else:
        steps_section = f"<section class=\"panel active\">{steps_html}</section>"

    tip_html = (
        f'<aside class="tip"><strong>{"Tipp" if de else "Tip"}:</strong> {tip}</aside>'
        if tip
        else ""
    )
    footer = (
        "Inoffizielle food-with-love-Ansicht · nur für persönlichen Gebrauch"
        if de
        else "Unofficial food with love view · personal use only"
    )
    persons_label = "Personen" if de else "people"
    # Prefer "Portionen"/recipe servingType in the control when it's not empty.
    scale_label = serving_type or persons_label
    base_json = json.dumps(base_servings)

    servings_ctrl = f"""
    <div class="servings" id="servings-ctrl" data-base="{html.escape(str(base_servings))}">
      <button type="button" class="servings-btn" data-delta="-1" aria-label="-">−</button>
      <div class="servings-readout">
        <span id="servings-value">{html.escape(_format_serving_count(base_servings))}</span>
        <span class="servings-unit">{scale_label}</span>
      </div>
      <button type="button" class="servings-btn" data-delta="1" aria-label="+">+</button>
    </div>
    """

    return f"""<!DOCTYPE html>
<html lang="{html.escape(language)}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src https:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none';">
  <title>{title}</title>
  <style>
    :root {{
      --bg: #f7f3ee;
      --ink: #1c1917;
      --muted: #57534e;
      --accent: #b45309;
      --card: #fffdf9;
      --line: #e7e5e4;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", system-ui, sans-serif;
      background: var(--bg);
      color: var(--ink);
      line-height: 1.45;
    }}
    main {{
      max-width: 52rem; margin: 0 auto;
      padding: 1rem 1.5rem 3rem;
    }}
    .hero {{
      width: 100%; max-height: 42vh; object-fit: cover;
      border-radius: 1rem; display: block; margin-bottom: 1.25rem;
    }}
    h1 {{
      font-size: clamp(1.8rem, 4vw, 2.6rem);
      line-height: 1.15; margin: 0 0 0.35rem;
    }}
    .meta {{ color: var(--muted); font-size: 1.1rem; margin-bottom: 0.75rem; }}
    .servings {{
      display: inline-flex; align-items: center; gap: 0.65rem;
      margin: 0 0 1.25rem; padding: 0.35rem;
      background: var(--card); border: 1px solid var(--line);
      border-radius: 999px;
    }}
    .servings-btn {{
      appearance: none; width: 2.4rem; height: 2.4rem;
      border-radius: 999px; border: 1px solid var(--line);
      background: #fff; color: var(--ink); font-size: 1.35rem;
      line-height: 1; cursor: pointer;
    }}
    .servings-btn:active {{ background: #f5f5f4; }}
    .servings-readout {{
      min-width: 6.5rem; text-align: center; font-size: 1.15rem;
      font-weight: 650;
    }}
    .servings-unit {{
      display: block; font-size: 0.8rem; font-weight: 500;
      color: var(--muted);
    }}
    .intro {{ font-size: 1.15rem; margin-bottom: 1.5rem; }}
    h2 {{
      font-size: 1.35rem; margin: 1.75rem 0 0.75rem;
      color: var(--accent);
    }}
    .group {{ margin-bottom: 1rem; }}
    .group-title {{
      font-weight: 650; font-size: 1.05rem; margin-bottom: 0.35rem;
    }}
    ul.ingredients {{
      list-style: none; padding: 0; margin: 0;
      display: grid; gap: 0.35rem;
    }}
    ul.ingredients li {{
      background: var(--card); border: 1px solid var(--line);
      border-radius: 0.65rem; padding: 0.55rem 0.8rem;
      font-size: 1.12rem;
    }}
    ol.steps {{
      padding-left: 1.4rem; margin: 0;
      display: grid; gap: 0.9rem;
    }}
    ol.steps li {{ font-size: 1.15rem; padding-left: 0.35rem; }}
    .tip {{
      margin-top: 1.5rem; padding: 1rem 1.1rem;
      background: #fff7ed; border-left: 4px solid var(--accent);
      border-radius: 0.5rem;
    }}
    .tabs {{
      display: flex; gap: 0.5rem; margin: 1.25rem 0 0.5rem;
    }}
    .tab {{
      appearance: none; border: 1px solid var(--line);
      background: var(--card); border-radius: 999px;
      padding: 0.5rem 1rem; cursor: pointer; font-size: 1rem;
    }}
    .tab.active {{
      background: var(--ink); color: #fff; border-color: var(--ink);
    }}
    .panel {{ display: none; }}
    .panel.active {{ display: block; }}
    footer {{
      margin-top: 2.5rem; color: var(--muted); font-size: 0.85rem;
    }}
  </style>
</head>
<body>
  <main>
    {image_html}
    <h1>{title}</h1>
    <div class="meta">{html.escape(meta)}</div>
    {servings_ctrl}
    {f'<div class="intro">{intro}</div>' if intro else ""}
    {ingredients_html}
    {tabs}
    {steps_section}
    {tip_html}
    <footer>{html.escape(footer)}</footer>
  </main>
  <script>
    const BASE = {base_json};
    let current = BASE;

    function parseQty(raw) {{
      if (raw == null) return null;
      const s = String(raw).trim().replace(",", ".");
      if (!s) return null;
      if (s.includes("/")) {{
        const [a, b] = s.split("/", 2);
        const n = Number(a), d = Number(b);
        if (d) return n / d;
      }}
      const n = Number(s);
      return Number.isFinite(n) ? n : null;
    }}

    function formatQty(n) {{
      if (!Number.isFinite(n)) return "";
      const abs = Math.abs(n);
      if (abs === 0) return "0";
      // Prefer tidy kitchen fractions for common values.
      const frac = nearestFraction(n);
      if (frac) return frac;
      if (Math.abs(n - Math.round(n)) < 1e-6) return String(Math.round(n));
      if (abs >= 100) return String(Math.round(n));
      if (abs >= 10) return (Math.round(n * 10) / 10).toString();
      return (Math.round(n * 100) / 100).toString().replace(/\\.?0+$/, "");
    }}

    function nearestFraction(n) {{
      const sign = n < 0 ? "-" : "";
      const abs = Math.abs(n);
      const whole = Math.floor(abs + 1e-9);
      const rem = abs - whole;
      if (rem < 0.02) return sign + String(whole || (n === 0 ? "0" : whole));
      const table = [
        [0.125, "1/8"], [0.25, "1/4"], [0.333, "1/3"], [0.375, "3/8"],
        [0.5, "1/2"], [0.625, "5/8"], [0.666, "2/3"], [0.75, "3/4"],
        [0.875, "7/8"],
      ];
      for (const [v, label] of table) {{
        if (Math.abs(rem - v) < 0.04) {{
          return whole ? `${{sign}}${{whole}} ${{label}}` : sign + label;
        }}
      }}
      return null;
    }}

    function applyScale() {{
      const factor = current / BASE;
      document.getElementById("servings-value").textContent = formatQty(current);
      document.querySelectorAll("li[data-qty]").forEach((li) => {{
        const base = parseQty(li.dataset.qty);
        const unit = li.dataset.unit || "";
        const name = li.dataset.name || "";
        const qtyEl = li.querySelector(".qty");
        if (base == null || !qtyEl) return;
        const scaled = base * factor;
        const left = [formatQty(scaled), unit].filter(Boolean).join(" ");
        qtyEl.textContent = left ? left + (name ? " " : "") : "";
      }});
    }}

    document.querySelectorAll(".servings-btn").forEach((btn) => {{
      btn.addEventListener("click", () => {{
        const delta = Number(btn.dataset.delta) || 0;
        const next = Math.round((current + delta) * 100) / 100;
        if (next < 1) return;
        current = next;
        applyScale();
      }});
    }});

    document.querySelectorAll(".tab").forEach((btn) => {{
      btn.addEventListener("click", () => {{
        document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
        document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
        btn.classList.add("active");
        const panel = document.getElementById("panel-" + btn.dataset.panel);
        if (panel) panel.classList.add("active");
      }});
    }});
  </script>
</body>
</html>
"""


def _format_serving_count(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return str(value)


def _ingredients_block(groups: list[Any], *, de: bool) -> str:
    if not groups:
        return ""
    parts = [f"<h2>{'Zutaten' if de else 'Ingredients'}</h2>"]
    for group in groups:
        if not isinstance(group, dict):
            continue
        items = group.get("ingredients") or []
        group_type = group.get("type")
        body = ['<ul class="ingredients">']
        for item in items:
            if not isinstance(item, dict):
                continue
            line = _ingredient_li(item)
            if line:
                body.append(line)
        body.append("</ul>")
        block = "".join(body)
        if group_type and str(group_type).strip() and str(group_type) not in (
            "Basis",
            "Base",
            "",
        ):
            parts.append(
                f'<div class="group"><div class="group-title">'
                f"{html.escape(str(group_type))}</div>{block}</div>"
            )
        else:
            parts.append(f'<div class="group">{block}</div>')
    return "".join(parts)


def _ingredient_li(item: dict[str, Any]) -> str:
    qty = str(item.get("quantity") or "").strip()
    unit = str(item.get("unit") or "").strip()
    name = str(item.get("name") or "").strip()
    if not qty and not unit and not name:
        return ""
    left = " ".join(p for p in (qty, unit) if p).strip()
    # Scalable when quantity parses as a number / fraction.
    attrs = (
        f' data-qty="{html.escape(qty, quote=True)}"'
        f' data-unit="{html.escape(unit, quote=True)}"'
        f' data-name="{html.escape(name, quote=True)}"'
        if qty
        else ""
    )
    if left and name:
        return (
            f"<li{attrs}><span class=\"qty\">{html.escape(left)} </span>"
            f"{html.escape(name)}</li>"
        )
    if name:
        return f"<li{attrs}>{html.escape(name)}</li>"
    return f"<li{attrs}><span class=\"qty\">{html.escape(left)}</span></li>"


def _steps_block(steps: list[Any], *, heading: str) -> str:
    if not steps:
        return ""
    parts = [f"<h2>{html.escape(heading)}</h2>", '<ol class="steps">']
    for step in steps:
        if not isinstance(step, dict):
            continue
        instruction = sanitize_rich_html(step.get("instruction"))
        if not instruction:
            continue
        parts.append(f"<li>{instruction}</li>")
    parts.append("</ol>")
    return "".join(parts)


def _first_url(urls: Any) -> str | None:
    if isinstance(urls, list) and urls:
        first = urls[0]
        return first if isinstance(first, str) and first else None
    return None


def _text(value: Any) -> str:
    return html.escape(str(value or ""))
