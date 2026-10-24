/**
 * food with love — Lovelace cards with device-aware recipe opening.
 * Mobile / touch-narrow: open FWL app deep link.
 * Desktop: open HA recipe viewer in an overlay (fallback: new tab).
 */
(() => {
  const CARD_TAG = "fwl-food-card";
  const WEEK_TAG = "fwl-week-card";
  const RECIPE_TAG = "fwl-recipe-card";
  const FAV_TAG = "fwl-favorites-card";

  function preferApp() {
    const ua = navigator.userAgent || "";
    if (/Android|iPhone|iPad|iPod|Mobile/i.test(ua)) return true;
    // Large tablets in landscape still prefer the in-HA viewer.
    if (navigator.maxTouchPoints > 1 && window.innerWidth < 768) return true;
    return false;
  }

  async function fetchRecipeHtml(hass, viewerUrl) {
    if (!hass || !viewerUrl) return null;
    const resp = await hass.fetchWithAuth(viewerUrl);
    if (!resp.ok) {
      throw new Error(`Recipe viewer HTTP ${resp.status}`);
    }
    return await resp.text();
  }

  async function openRecipe(hass, { appUrl, viewerUrl }) {
    if (preferApp() && appUrl) {
      window.location.href = appUrl;
      return;
    }
    if (viewerUrl) {
      try {
        const html = await fetchRecipeHtml(hass, viewerUrl);
        if (html) {
          openViewerOverlay(html);
          return;
        }
      } catch (err) {
        console.error("fwl recipe viewer failed", err);
        window.alert("Rezept konnte nicht geladen werden.");
        return;
      }
    }
    if (appUrl) window.location.href = appUrl;
  }

  function openViewerOverlay(html) {
    const existing = document.getElementById("fwl-recipe-overlay");
    if (existing) existing.remove();

    // Blob tab: authenticated HTML without needing a cookie on /api/*
    let blobUrl = null;
    const revokeBlob = () => {
      if (blobUrl) {
        URL.revokeObjectURL(blobUrl);
        blobUrl = null;
      }
    };

    const backdrop = document.createElement("div");
    backdrop.id = "fwl-recipe-overlay";
    backdrop.setAttribute("role", "dialog");
    backdrop.setAttribute("aria-modal", "true");
    backdrop.style.cssText =
      "position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.55);" +
      "display:flex;align-items:center;justify-content:center;padding:1rem;" +
      "box-sizing:border-box;";

    const panel = document.createElement("div");
    panel.style.cssText =
      "background:var(--card-background-color,#fff);width:min(960px,100%);" +
      "height:min(90vh,100%);border-radius:12px;overflow:hidden;display:flex;" +
      "flex-direction:column;box-shadow:0 12px 40px rgba(0,0,0,.35);";

    const bar = document.createElement("div");
    bar.style.cssText =
      "display:flex;align-items:center;justify-content:flex-end;gap:.5rem;" +
      "padding:.5rem .75rem;border-bottom:1px solid var(--divider-color,#ddd);";

    const tabBtn = document.createElement("button");
    tabBtn.type = "button";
    tabBtn.textContent = "Neuer Tab";
    tabBtn.style.cssText = buttonStyle();
    tabBtn.addEventListener("click", () => {
      revokeBlob();
      blobUrl = URL.createObjectURL(
        new Blob([html], { type: "text/html;charset=utf-8" })
      );
      window.open(blobUrl, "_blank", "noopener");
    });

    const closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.textContent = "Schließen";
    closeBtn.style.cssText = buttonStyle(true);
    const close = () => {
      revokeBlob();
      backdrop.remove();
    };
    closeBtn.addEventListener("click", close);
    backdrop.addEventListener("click", (ev) => {
      if (ev.target === backdrop) close();
    });

    bar.append(tabBtn, closeBtn);

    const iframe = document.createElement("iframe");
    iframe.title = "Rezept";
    iframe.style.cssText = "border:0;flex:1;width:100%;background:#fff;";
    // srcdoc keeps HA auth out of the picture (no bare /api navigation).
    iframe.srcdoc = html;

    panel.append(bar, iframe);
    backdrop.append(panel);
    document.body.append(backdrop);
  }

  function buttonStyle(primary) {
    return (
      "appearance:none;border:1px solid var(--divider-color,#ccc);" +
      `background:${primary ? "var(--primary-color,#03a9f4)" : "transparent"};` +
      `color:${primary ? "var(--text-primary-color,#fff)" : "var(--primary-text-color)"};` +
      "border-radius:8px;padding:.35rem .75rem;font:inherit;cursor:pointer;"
    );
  }

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function stripHtml(s) {
    const d = document.createElement("div");
    d.innerHTML = String(s ?? "");
    return d.textContent || d.innerText || "";
  }

  function linkLabel() {
    return preferApp() ? "In App öffnen" : "Rezept öffnen";
  }

  function mealRow(meal, dayDate) {
    const title = esc(meal.title || "");
    const prep = meal.preparation_time
      ? ` · ${esc(meal.preparation_time)} min`
      : "";
    const img = meal.image_url
      ? `<img src="${esc(meal.image_url)}" alt="" width="72" style="width:72px;max-width:72px;height:auto;border-radius:8px;vertical-align:middle;margin-right:8px;" />`
      : "";
    const canOpen = meal.app_url || meal.viewer_url;
    const open = canOpen
      ? ` · <a href="#" class="fwl-open" data-app="${esc(meal.app_url || "")}" data-viewer="${esc(meal.viewer_url || "")}">${esc(linkLabel())}</a>`
      : "";
    const date = meal.date || dayDate || "";
    const custom = meal.custom ? "1" : "0";
    const key = meal.custom ? meal.title || "" : meal.recipe_id || "";
    const remove =
      date && key
        ? ` <button type="button" class="fwl-remove" title="Aus Wochenplan entfernen" aria-label="Entfernen" data-date="${esc(date)}" data-key="${esc(key)}" data-custom="${custom}" data-title="${esc(meal.title || "")}">×</button>`
        : "";
    return `<div class="fwl-meal" style="margin:.35rem 0 .7rem;display:flex;align-items:center;gap:.35rem;"><div style="flex:1;min-width:0;">${img}<strong>${title}</strong>${prep}${open}</div>${remove}</div>`;
  }

  function bindOpens(root, hass) {
    root.querySelectorAll("a.fwl-open").forEach((a) => {
      a.addEventListener("click", (ev) => {
        ev.preventDefault();
        openRecipe(hass, {
          appUrl: a.getAttribute("data-app") || "",
          viewerUrl: a.getAttribute("data-viewer") || "",
        });
      });
    });
  }

  function bindRemoves(root, hass) {
    root.querySelectorAll("button.fwl-remove").forEach((btn) => {
      btn.addEventListener("click", async (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        const title = btn.getAttribute("data-title") || "Rezept";
        if (!window.confirm(`„${title}“ aus dem Wochenplan entfernen?`)) {
          return;
        }
        const custom = btn.getAttribute("data-custom") === "1";
        const key = btn.getAttribute("data-key") || "";
        const date = btn.getAttribute("data-date") || "";
        const data = { date, custom };
        if (custom) data.title = key;
        else data.recipe_id = key;
        btn.disabled = true;
        try {
          await hass.callService("foodwithlove", "remove_weekplan_meal", data);
        } catch (err) {
          console.error("fwl remove weekplan meal failed", err);
          window.alert("Konnte nicht entfernt werden.");
          btn.disabled = false;
        }
      });
    });
  }

  class FwlWeekCard extends HTMLElement {
    setConfig(config) {
      this._config = config || {};
      if (!this._config.entity) {
        throw new Error("entity is required");
      }
    }

    set hass(hass) {
      this._hass = hass;
      this._render();
    }

    getCardSize() {
      return 6;
    }

    _render() {
      if (!this._hass || !this._config) return;
      const st = this._hass.states[this._config.entity];
      const days = (st && st.attributes && st.attributes.days) || [];
      const root = this.shadowRoot || this.attachShadow({ mode: "open" });
      let body;
      if (!days.length) {
        body = "<em>Wochenplan wird geladen…</em>";
      } else {
        body = days
          .map((d) => {
            const label = esc(d.label || "");
            const head = d.is_today
              ? `<h3 style="margin:1rem 0 .35rem;">${label}</h3>`
              : `<div style="margin:1rem 0 .35rem;font-weight:600;">${label}</div>`;
            if (d.empty) {
              return `${head}<div style="opacity:.7;">Keine Rezepte</div>`;
            }
            const meals = (d.meals || [])
              .map((m) => mealRow(m, d.date))
              .join("");
            return `${head}${meals}`;
          })
          .join("");
      }
      root.innerHTML = `
        <ha-card>
          <style>
            button.fwl-remove {
              appearance: none; border: 1px solid var(--divider-color, #ddd);
              background: transparent; color: var(--secondary-text-color);
              width: 1.75rem; height: 1.75rem; border-radius: 999px;
              font-size: 1.1rem; line-height: 1; cursor: pointer; flex: 0 0 auto;
            }
            button.fwl-remove:hover { color: var(--error-color, #c62828); border-color: currentColor; }
            button.fwl-remove:disabled { opacity: .4; cursor: wait; }
          </style>
          <div style="padding:12px 16px 16px;">
            ${this._config.title ? `<h2 style="margin:0 0 .5rem;font-size:1.1rem;">${esc(this._config.title)}</h2>` : ""}
            ${body}
          </div>
        </ha-card>`;
      bindOpens(root, this._hass);
      bindRemoves(root, this._hass);
    }
  }

  class FwlRecipeCard extends HTMLElement {
    setConfig(config) {
      this._config = config || {};
      if (!this._config.entity) {
        throw new Error("entity is required");
      }
    }

    set hass(hass) {
      this._hass = hass;
      this._render();
    }

    getCardSize() {
      return 4;
    }

    _render() {
      if (!this._hass || !this._config) return;
      const st = this._hass.states[this._config.entity];
      const gEnt = this._config.greeting_entity;
      const greeting = gEnt && this._hass.states[gEnt] ? this._hass.states[gEnt].state : "";
      const attrs = (st && st.attributes) || {};
      const title = st ? st.state : "";
      const img =
        attrs.thumb_url || attrs.entity_picture || attrs.image_url || "";
      const prep = attrs.preparation_time;
      const metaBits = [];
      if (prep) metaBits.push(`${prep} min`);
      const content = stripHtml(
        String(attrs.content || "")
          .replace(/<br\s*\/?>/gi, " ")
      );
      const canOpen = attrs.app_url || attrs.viewer_url;
      const root = this.shadowRoot || this.attachShadow({ mode: "open" });
      root.innerHTML = `
        <ha-card>
          <div style="padding:12px 16px 16px;">
            ${this._config.title ? `<h2 style="margin:0 0 .5rem;font-size:1.1rem;">${esc(this._config.title)}</h2>` : ""}
            ${img ? `<img src="${esc(img)}" alt="" width="120" style="width:120px;max-width:120px;height:auto;border-radius:10px;" />` : ""}
            <h3 style="margin:.5rem 0 .25rem;">${esc(title)}</h3>
            ${metaBits.length ? `<div style="opacity:.8;margin-bottom:.5rem;">${esc(metaBits.join(" · "))}</div>` : ""}
            ${greeting ? `<div style="font-style:italic;margin-bottom:.75rem;">${esc(greeting)}</div>` : ""}
            ${content ? `<div style="margin-bottom:.75rem;line-height:1.45;">${esc(content)}</div>` : ""}
            ${
              canOpen
                ? `<a href="#" class="fwl-open" data-app="${esc(attrs.app_url || "")}" data-viewer="${esc(attrs.viewer_url || "")}" style="font-weight:600;">${esc(linkLabel())}</a>`
                : ""
            }
          </div>
        </ha-card>`;
      bindOpens(root, this._hass);
    }
  }

  function todayISO() {
    const d = new Date();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${d.getFullYear()}-${m}-${day}`;
  }

  function pickDate(title) {
    return new Promise((resolve) => {
      const existing = document.getElementById("fwl-date-picker");
      if (existing) existing.remove();

      const backdrop = document.createElement("div");
      backdrop.id = "fwl-date-picker";
      backdrop.style.cssText =
        "position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,.45);" +
        "display:flex;align-items:center;justify-content:center;padding:1rem;";

      const panel = document.createElement("div");
      panel.style.cssText =
        "background:var(--card-background-color,#fff);color:var(--primary-text-color);" +
        "border-radius:12px;padding:1rem 1.1rem;min-width:min(320px,100%);" +
        "box-shadow:0 12px 40px rgba(0,0,0,.35);";

      const heading = document.createElement("div");
      heading.style.cssText = "font-weight:650;margin-bottom:.75rem;";
      heading.textContent = title || "Zum Wochenplan hinzufügen";

      const input = document.createElement("input");
      input.type = "date";
      input.value = todayISO();
      input.style.cssText =
        "width:100%;font:inherit;padding:.5rem;border-radius:8px;" +
        "border:1px solid var(--divider-color,#ccc);margin-bottom:.85rem;" +
        "background:transparent;color:inherit;box-sizing:border-box;";

      const row = document.createElement("div");
      row.style.cssText = "display:flex;justify-content:flex-end;gap:.5rem;";

      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.textContent = "Abbrechen";
      cancel.style.cssText = buttonStyle();
      const ok = document.createElement("button");
      ok.type = "button";
      ok.textContent = "Hinzufügen";
      ok.style.cssText = buttonStyle(true);

      const close = (value) => {
        backdrop.remove();
        resolve(value);
      };
      cancel.addEventListener("click", () => close(null));
      backdrop.addEventListener("click", (ev) => {
        if (ev.target === backdrop) close(null);
      });
      ok.addEventListener("click", () => close(input.value || null));

      row.append(cancel, ok);
      panel.append(heading, input, row);
      backdrop.append(panel);
      document.body.append(backdrop);
      input.focus();
    });
  }

  function favoriteRecipeRow(recipe) {
    const title = esc(recipe.title || recipe.recipe_id || "");
    const prep = recipe.preparation_time
      ? ` · ${esc(recipe.preparation_time)} min`
      : "";
    const img = recipe.image_url
      ? `<img src="${esc(recipe.image_url)}" alt="" width="56" style="width:56px;max-width:56px;height:auto;border-radius:8px;vertical-align:middle;margin-right:8px;" />`
      : "";
    const canOpen = recipe.app_url || recipe.viewer_url;
    const open = canOpen
      ? `<a href="#" class="fwl-open" data-app="${esc(recipe.app_url || "")}" data-viewer="${esc(recipe.viewer_url || "")}">${esc(linkLabel())}</a>`
      : "";
    const rid = recipe.recipe_id || "";
    const add = rid
      ? `<button type="button" class="fwl-add" title="Zum Wochenplan" aria-label="Zum Wochenplan" data-recipe-id="${esc(rid)}" data-title="${title}">+</button>`
      : "";
    return `<div class="fwl-fav-recipe" style="display:flex;align-items:center;gap:.4rem;margin:.3rem 0 .55rem;">
      <div style="flex:1;min-width:0;">${img}<strong>${title}</strong>${prep}${open ? ` · ${open}` : ""}</div>
      ${add}
    </div>`;
  }

  class FwlFavoritesCard extends HTMLElement {
    setConfig(config) {
      this._config = config || {};
      if (!this._config.entity) {
        throw new Error("entity is required");
      }
      this._open = this._open || new Set();
    }

    set hass(hass) {
      this._hass = hass;
      this._render();
    }

    getCardSize() {
      return 6;
    }

    _toggle(id) {
      if (this._open.has(id)) this._open.delete(id);
      else this._open.add(id);
      this._render();
    }

    _render() {
      if (!this._hass || !this._config) return;
      const st = this._hass.states[this._config.entity];
      const attrs = (st && st.attributes) || {};
      const folders = attrs.favorite_folders || [];
      const uncategorized = attrs.uncategorized || [];
      const total = attrs.favorite_count || (st && st.state) || 0;
      const sections = [];
      if (uncategorized.length) {
        sections.push({
          id: "__uncategorized__",
          name: "Ohne Ordner",
          count: uncategorized.length,
          recipes: uncategorized,
        });
      }
      for (const f of folders) {
        sections.push({
          id: f.id || f.name,
          name: f.name || "Ordner",
          count: f.count || (f.recipes || []).length,
          recipes: f.recipes || [],
        });
      }

      const root = this.shadowRoot || this.attachShadow({ mode: "open" });
      let body;
      if (!sections.length) {
        body = "<em>Keine Favoriten</em>";
      } else {
        body = sections
          .map((sec) => {
            const open = this._open.has(sec.id);
            const chev = open ? "▾" : "▸";
            const recipes = open
              ? (sec.recipes || []).map(favoriteRecipeRow).join("")
              : "";
            return `<div class="fwl-folder">
              <button type="button" class="fwl-folder-head" data-id="${esc(sec.id)}">
                <span class="chev">${chev}</span>
                <span class="name">${esc(sec.name)}</span>
                <span class="count">${esc(sec.count)}</span>
              </button>
              ${open ? `<div class="fwl-folder-body">${recipes || "<em>Leer</em>"}</div>` : ""}
            </div>`;
          })
          .join("");
      }

      root.innerHTML = `
        <ha-card>
          <style>
            .pad { padding: 12px 16px 16px; }
            .summary { opacity: .75; margin-bottom: .65rem; font-size: .95rem; }
            .fwl-folder { border-top: 1px solid var(--divider-color, #3333); }
            .fwl-folder:first-of-type { border-top: 0; }
            button.fwl-folder-head {
              appearance: none; width: 100%; display: flex; align-items: center;
              gap: .55rem; padding: .65rem 0; border: 0; background: transparent;
              color: inherit; font: inherit; cursor: pointer; text-align: left;
            }
            button.fwl-folder-head .chev { width: 1rem; opacity: .7; }
            button.fwl-folder-head .name { flex: 1; font-weight: 650; }
            button.fwl-folder-head .count {
              opacity: .65; font-variant-numeric: tabular-nums;
            }
            .fwl-folder-body { padding: 0 0 .55rem .2rem; }
            button.fwl-add {
              appearance: none; border: 1px solid var(--divider-color, #ddd);
              background: transparent; color: var(--primary-color, #03a9f4);
              width: 1.75rem; height: 1.75rem; border-radius: 999px;
              font-size: 1.2rem; line-height: 1; cursor: pointer; flex: 0 0 auto;
            }
            button.fwl-add:hover { border-color: currentColor; }
            button.fwl-add:disabled { opacity: .4; cursor: wait; }
          </style>
          <div class="pad">
            ${this._config.title ? `<h2 style="margin:0 0 .35rem;font-size:1.1rem;">${esc(this._config.title)}</h2>` : ""}
            <div class="summary">${esc(total)} Favoriten</div>
            ${body}
          </div>
        </ha-card>`;

      root.querySelectorAll("button.fwl-folder-head").forEach((btn) => {
        btn.addEventListener("click", () => this._toggle(btn.getAttribute("data-id")));
      });
      bindOpens(root, this._hass);
      root.querySelectorAll("button.fwl-add").forEach((btn) => {
        btn.addEventListener("click", async (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          const recipeId = btn.getAttribute("data-recipe-id") || "";
          const recipeTitle = btn.getAttribute("data-title") || "Rezept";
          const day = await pickDate(`„${recipeTitle}“ planen`);
          if (!day || !recipeId) return;
          btn.disabled = true;
          try {
            await this._hass.callService("foodwithlove", "add_weekplan_meal", {
              date: day,
              recipe_id: recipeId,
            });
          } catch (err) {
            console.error("fwl add weekplan meal failed", err);
            window.alert("Konnte nicht zum Wochenplan hinzufügen.");
            btn.disabled = false;
            return;
          }
          btn.disabled = false;
        });
      });
    }
  }

  /** Combined card used by the Food dashboard (week + recipe of the day). */
  class FwlFoodCard extends HTMLElement {
    setConfig(config) {
      this._config = config || {};
    }

    set hass(hass) {
      this._hass = hass;
      if (!this._built) {
        this._built = true;
        this.attachShadow({ mode: "open" });
        this.shadowRoot.innerHTML = `
          <style>
            .stack { display: grid; gap: 12px; }
          </style>
          <div class="stack">
            <fwl-week-card></fwl-week-card>
            <fwl-recipe-card></fwl-recipe-card>
          </div>`;
        this._week = this.shadowRoot.querySelector(WEEK_TAG);
        this._recipe = this.shadowRoot.querySelector(RECIPE_TAG);
        this._week.setConfig({
          entity:
            this._config.week_entity ||
            "sensor.food_with_love_wochenuberblick",
          title: this._config.week_title || "",
        });
        this._recipe.setConfig({
          entity:
            this._config.recipe_entity ||
            "sensor.food_with_love_rezept_des_tages",
          greeting_entity:
            this._config.greeting_entity ||
            "sensor.food_with_love_morgengruss",
          title: this._config.recipe_title || "",
        });
      }
      this._week.hass = hass;
      this._recipe.hass = hass;
    }

    getCardSize() {
      return 10;
    }
  }

  if (!customElements.get(WEEK_TAG)) {
    customElements.define(WEEK_TAG, FwlWeekCard);
  }
  if (!customElements.get(RECIPE_TAG)) {
    customElements.define(RECIPE_TAG, FwlRecipeCard);
  }
  if (!customElements.get(FAV_TAG)) {
    customElements.define(FAV_TAG, FwlFavoritesCard);
  }
  if (!customElements.get(CARD_TAG)) {
    customElements.define(CARD_TAG, FwlFoodCard);
  }

  window.customCards = window.customCards || [];
  for (const c of [
    {
      type: "fwl-week-card",
      name: "food with love week",
      description: "Week overview with device-aware recipe links",
    },
    {
      type: "fwl-recipe-card",
      name: "food with love recipe",
      description: "Recipe of the day with device-aware open action",
    },
    {
      type: "fwl-favorites-card",
      name: "food with love favorites",
      description: "Collapsible favorite folders with add-to-weekplan",
    },
    {
      type: "fwl-food-card",
      name: "food with love",
      description: "Week + recipe of the day",
    },
  ]) {
    if (!window.customCards.some((x) => x.type === c.type)) {
      window.customCards.push(c);
    }
  }
})();
