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

  const VIEWER_PATH_RE = /^\/api\/foodwithlove\/recipe\/[A-Za-z0-9_%-]+$/;
  const APP_HOST = "www.foodwithlove.de";
  const IMAGE_HOST_RE =
    /^(?:storage\.googleapis\.com|(?:[\w-]+\.)?googleapis\.com|www\.foodwithlove\.de|foodwithlove\.de|food-with-love-app\.web\.app|food-with-love-app\.firebaseapp\.com)$/i;

  function normalizeViewerPath(viewerUrl) {
    if (!viewerUrl) return null;
    try {
      const u = new URL(String(viewerUrl), window.location.origin);
      if (u.origin !== window.location.origin) return null;
      if (u.search || u.hash) return null;
      if (!VIEWER_PATH_RE.test(u.pathname)) return null;
      return u.pathname;
    } catch (_err) {
      return null;
    }
  }

  function safeAppUrl(url) {
    if (!url) return null;
    try {
      const u = new URL(String(url));
      if (u.protocol !== "https:") return null;
      if (u.hostname !== APP_HOST) return null;
      if (u.pathname !== "/app" && u.pathname !== "/app/") return null;
      return u.toString();
    } catch (_err) {
      return null;
    }
  }

  async function fetchRecipeHtml(hass, viewerUrl) {
    if (!hass) return null;
    const path = normalizeViewerPath(viewerUrl);
    if (!path) {
      throw new Error("Invalid recipe viewer URL");
    }
    const resp = await hass.fetchWithAuth(path);
    if (!resp.ok) {
      throw new Error(`Recipe viewer HTTP ${resp.status}`);
    }
    const ctype = (resp.headers.get("content-type") || "").toLowerCase();
    if (!ctype.includes("text/html")) {
      throw new Error("Unexpected recipe content type");
    }
    return await resp.text();
  }

  async function openRecipe(hass, { appUrl, viewerUrl }) {
    const safeApp = safeAppUrl(appUrl);
    if (preferApp() && safeApp) {
      window.location.assign(safeApp);
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
    if (safeApp) window.location.assign(safeApp);
  }

  function openViewerOverlay(html) {
    const existing = document.getElementById("fwl-recipe-overlay");
    if (existing) existing.remove();

    // Content blob is only loaded inside sandbox=allow-scripts (no same-origin).
    let contentBlobUrl = null;
    let wrapperBlobUrl = null;
    const revokeBlobs = () => {
      if (wrapperBlobUrl) URL.revokeObjectURL(wrapperBlobUrl);
      if (contentBlobUrl) URL.revokeObjectURL(contentBlobUrl);
      wrapperBlobUrl = null;
      contentBlobUrl = null;
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
      revokeBlobs();
      contentBlobUrl = URL.createObjectURL(
        new Blob([html], { type: "text/html;charset=utf-8" })
      );
      // Wrapper stays script-free; recipe runs in an opaque-origin sandbox.
      const wrapper = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>Rezept</title>
<style>html,body,iframe{margin:0;border:0;width:100%;height:100%;background:#fff}</style>
</head><body><iframe sandbox="allow-scripts" src="${contentBlobUrl}" title="Rezept"></iframe></body></html>`;
      wrapperBlobUrl = URL.createObjectURL(
        new Blob([wrapper], { type: "text/html;charset=utf-8" })
      );
      window.open(wrapperBlobUrl, "_blank", "noopener,noreferrer");
    });

    const closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.textContent = "Schließen";
    closeBtn.style.cssText = buttonStyle(true);
    const close = () => {
      revokeBlobs();
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
    // Scripts (portion scaler) allowed; opaque origin — no parent/HA access.
    iframe.setAttribute("sandbox", "allow-scripts");
    // srcdoc avoids navigating to /api/* without a bearer token.
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
    // DOMParser documents are inert — unlike assigning to a detached element's
    // innerHTML, which still runs <img onerror=…> / similar markup.
    const doc = new DOMParser().parseFromString(String(s ?? ""), "text/html");
    return doc.body.textContent || "";
  }

  /** Only allow https images from known FWL/CDN hosts. */
  function safeHttpsUrl(url) {
    try {
      const u = new URL(String(url || "").trim());
      if (u.protocol !== "https:") return "";
      if (!IMAGE_HOST_RE.test(u.hostname)) return "";
      if (u.username || u.password) return "";
      return u.toString();
    } catch (_err) {
      return "";
    }
  }

  function openHint() {
    return preferApp() ? "In App öffnen" : "Rezept öffnen";
  }

  function openDataAttrs(appUrl, viewerUrl) {
    return `data-app="${esc(appUrl || "")}" data-viewer="${esc(viewerUrl || "")}"`;
  }

  /** Compact open affordance — book icon, no wrapping text link. */
  function openIconButton(appUrl, viewerUrl) {
    if (!appUrl && !viewerUrl) return "";
    return `<button type="button" class="fwl-open fwl-icon-btn" ${openDataAttrs(appUrl, viewerUrl)} title="${esc(openHint())}" aria-label="${esc(openHint())}">
      <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
        <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
        <path d="M12 2v20"/>
      </svg>
    </button>`;
  }

  function metaLine(meal) {
    const parts = [];
    if (meal.preparation_time != null && meal.preparation_time !== "") {
      parts.push(`${meal.preparation_time} min`);
    }
    if (meal.rating != null && meal.rating !== "") {
      const votes =
        meal.rating_count != null && meal.rating_count !== ""
          ? ` (${meal.rating_count})`
          : "";
      parts.push(`★ ${meal.rating}${votes}`);
    }
    return parts.length
      ? `<div class="fwl-prep">${esc(parts.join(" · "))}</div>`
      : "";
  }

  function mealMain(meal, imgSize) {
    const title = esc(meal.title || "");
    const prep = metaLine(meal);
    const size = imgSize || 72;
    const imgUrl = safeHttpsUrl(meal.image_url);
    const img = imgUrl
      ? `<img src="${esc(imgUrl)}" alt="" width="${size}" style="width:${size}px;max-width:${size}px;height:auto;border-radius:8px;flex:0 0 auto;" />`
      : "";
    const text = `<div class="fwl-text"><strong>${title}</strong>${prep}</div>`;
    const canOpen = meal.app_url || meal.viewer_url;
    if (!canOpen) {
      return `<div class="fwl-main">${img}${text}</div>`;
    }
    return `<button type="button" class="fwl-open fwl-main" ${openDataAttrs(meal.app_url, meal.viewer_url)} title="${esc(openHint())}">
      ${img}${text}
    </button>`;
  }

  function mealRow(meal, dayDate) {
    const date = meal.date || dayDate || "";
    const custom = meal.custom ? "1" : "0";
    const key = meal.custom ? meal.title || "" : meal.recipe_id || "";
    const remove =
      date && key
        ? `<button type="button" class="fwl-remove" title="Aus Wochenplan entfernen" aria-label="Entfernen" data-date="${esc(date)}" data-key="${esc(key)}" data-custom="${custom}" data-title="${esc(meal.title || "")}">×</button>`
        : "";
    return `<div class="fwl-meal">${mealMain(meal, 72)}${openIconButton(meal.app_url, meal.viewer_url)}${remove}</div>`;
  }

  function bindOpens(root, hass) {
    root.querySelectorAll(".fwl-open").forEach((el) => {
      el.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        openRecipe(hass, {
          appUrl: el.getAttribute("data-app") || "",
          viewerUrl: el.getAttribute("data-viewer") || "",
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
          <style>${sharedRowStyles()}
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

  function sharedRowStyles() {
    return `
      .fwl-meal, .fwl-fav-recipe {
        margin: .35rem 0 .7rem; display: flex; align-items: center; gap: .4rem;
      }
      button.fwl-main {
        appearance: none; border: 0; background: transparent; color: inherit;
        font: inherit; text-align: left; cursor: pointer; flex: 1; min-width: 0;
        display: flex; align-items: center; gap: .55rem; padding: 0;
      }
      button.fwl-main:hover strong { text-decoration: underline; }
      .fwl-main { display: flex; align-items: center; gap: .55rem; flex: 1; min-width: 0; }
      .fwl-text { min-width: 0; line-height: 1.3; }
      .fwl-text strong { display: block; }
      .fwl-prep { opacity: .75; font-weight: 400; font-size: .92em; margin-top: .15rem; }
      button.fwl-icon-btn {
        appearance: none; border: 1px solid var(--divider-color, #ddd);
        background: transparent; color: var(--primary-color, #03a9f4);
        width: 1.75rem; height: 1.75rem; border-radius: 999px;
        display: inline-flex; align-items: center; justify-content: center;
        cursor: pointer; flex: 0 0 auto; padding: 0;
      }
      button.fwl-icon-btn:hover { border-color: currentColor; }
    `;
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
      const img = safeHttpsUrl(
        attrs.thumb_url || attrs.entity_picture || attrs.image_url || ""
      );
      const metaBits = [];
      if (attrs.preparation_time != null && attrs.preparation_time !== "") {
        metaBits.push(`${attrs.preparation_time} min`);
      }
      if (attrs.rating != null && attrs.rating !== "") {
        const votes =
          attrs.rating_count != null && attrs.rating_count !== ""
            ? ` (${attrs.rating_count})`
            : "";
        metaBits.push(`★ ${attrs.rating}${votes}`);
      }
      const content = stripHtml(
        String(attrs.content || "")
          .replace(/<br\s*\/?>/gi, " ")
      );
      const canOpen = attrs.app_url || attrs.viewer_url;
      const root = this.shadowRoot || this.attachShadow({ mode: "open" });
      const head = canOpen
        ? `<button type="button" class="fwl-open fwl-today" ${openDataAttrs(attrs.app_url, attrs.viewer_url)} title="${esc(openHint())}">
            ${img ? `<img src="${esc(img)}" alt="" width="120" style="width:120px;max-width:120px;height:auto;border-radius:10px;" />` : ""}
            <h3 style="margin:.5rem 0 .25rem;">${esc(title)}</h3>
          </button>`
        : `${img ? `<img src="${esc(img)}" alt="" width="120" style="width:120px;max-width:120px;height:auto;border-radius:10px;" />` : ""}
           <h3 style="margin:.5rem 0 .25rem;">${esc(title)}</h3>`;
      root.innerHTML = `
        <ha-card>
          <style>
            button.fwl-today {
              appearance: none; border: 0; background: transparent; color: inherit;
              font: inherit; text-align: left; cursor: pointer; display: block; padding: 0; width: 100%;
            }
            button.fwl-today:hover h3 { text-decoration: underline; }
          </style>
          <div style="padding:12px 16px 16px;">
            ${this._config.title ? `<h2 style="margin:0 0 .5rem;font-size:1.1rem;">${esc(this._config.title)}</h2>` : ""}
            ${head}
            ${metaBits.length ? `<div style="opacity:.8;margin-bottom:.5rem;">${esc(metaBits.join(" · "))}</div>` : ""}
            ${greeting ? `<div style="font-style:italic;margin-bottom:.75rem;">${esc(greeting)}</div>` : ""}
            ${content ? `<div style="margin-bottom:.75rem;line-height:1.45;">${esc(content)}</div>` : ""}
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
    const rid = recipe.recipe_id || "";
    const add = rid
      ? `<button type="button" class="fwl-add" title="Zum Wochenplan" aria-label="Zum Wochenplan" data-recipe-id="${esc(rid)}" data-title="${esc(recipe.title || "")}">+</button>`
      : "";
    return `<div class="fwl-fav-recipe">${mealMain(recipe, 56)}${openIconButton(recipe.app_url, recipe.viewer_url)}${add}</div>`;
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
          <style>${sharedRowStyles()}
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
