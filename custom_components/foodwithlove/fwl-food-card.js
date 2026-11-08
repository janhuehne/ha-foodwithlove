/**
 * food with love — Lovelace cards with device-aware recipe opening.
 * Mobile / touch-narrow: open FWL app deep link.
 * Desktop: open HA recipe viewer in an overlay (fallback: new tab).
 */
(() => {
  const CARD_VERSION = "0.5.33";
  const WEEK_MODE_STORAGE_KEY = "fwl-week-mode";

  function readStoredWeekMode() {
    try {
      const v = window.localStorage.getItem(WEEK_MODE_STORAGE_KEY);
      if (v === "calendar" || v === "rolling") return v;
    } catch (_err) {
      /* private mode / denied */
    }
    return null;
  }

  function storeWeekMode(mode) {
    try {
      window.localStorage.setItem(WEEK_MODE_STORAGE_KEY, mode);
    } catch (_err) {
      /* ignore */
    }
  }
  const CARD_TAG = "fwl-food-card";
  const WEEK_TAG = "fwl-week-card";
  const RECIPE_TAG = "fwl-recipe-card";
  const FAV_TAG = "fwl-favorites-card";
  // Helps confirm the browser actually loaded this build (not a stale module).
  try {
    window.__fwlFoodCardVersion = CARD_VERSION;
    console.info(`[foodwithlove] fwl-food-card ${CARD_VERSION}`);
  } catch (_err) {
    /* ignore */
  }

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
    /^(?:storage\.googleapis\.com|(?:[\w-]+\.)?googleapis\.com|www\.foodwithlove\.de|foodwithlove\.de|food-with-love-app\.web\.app|food-with-love-app\.firebaseapp\.com|assets\.tmecosys\.com|(?:[\w-]+\.)?tmecosys\.com|(?:[\w-]+\.)?chefkoch-cdn\.de)$/i;

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

  const COOKIDOO_HOST_RE =
    /^cookidoo\.(?:de|at|ch|com|co\.uk|international|fr|it|es|nl|pl|pt|be)$/i;
  const CHEFKOCH_HOST_RE = /^(?:www\.)?chefkoch\.de$/i;

  /** Allowlisted Cookidoo recipe deep links (joined favorites). */
  function safeCookidooUrl(url) {
    if (!url) return null;
    try {
      const u = new URL(String(url));
      if (u.protocol !== "https:") return null;
      if (!COOKIDOO_HOST_RE.test(u.hostname)) return null;
      if (!u.pathname.includes("/recipes/recipe/")) return null;
      return u.toString();
    } catch (_err) {
      return null;
    }
  }

  /** Allowlisted Chefkoch recipe deep links (public + private cookbook). */
  function safeChefkochUrl(url) {
    if (!url) return null;
    try {
      const u = new URL(String(url));
      if (u.protocol !== "https:") return null;
      if (!CHEFKOCH_HOST_RE.test(u.hostname)) return null;
      // Public: /rezepte/<id>/… — private: /mein-kochbuch/privatrezepte/<user-uuid>
      if (
        !/^\/rezepte\//i.test(u.pathname) &&
        !/^\/mein-kochbuch\/privatrezepte\/user-[a-f0-9-]+\/?$/i.test(u.pathname)
      ) {
        return null;
      }
      return u.toString();
    } catch (_err) {
      return null;
    }
  }

  function collectionsDomain(source) {
    if (source === "cookidoo") return "cookidoo_collections";
    if (source === "chefkoch") return "chefkoch_collections";
    return "foodwithlove";
  }

  /** Build add/remove_weekplan_meal service data for a meal identity. */
  function weekplanServiceData({ source, date, key, custom }) {
    const data = { date };
    if (source === "cookidoo" || source === "chefkoch") {
      data.recipe_id = key;
    } else {
      data.custom = !!custom;
      if (custom) data.title = key;
      else data.recipe_id = key;
    }
    return data;
  }

  /**
   * Move a planned meal: add on toDate first, then remove on fromDate.
   * Add-first avoids losing the meal if the second call fails (same recipe may
   * briefly exist on both days).
   */
  async function moveWeekplanMeal(
    hass,
    { source, fromDate, toDate, key, custom }
  ) {
    if (!hass || !fromDate || !toDate || !key || fromDate === toDate) {
      return false;
    }
    const domain = collectionsDomain(source || "fwl");
    const removeData = weekplanServiceData({
      source,
      date: fromDate,
      key,
      custom,
    });
    const addData = weekplanServiceData({
      source,
      date: toDate,
      key,
      custom,
    });
    console.info("[foodwithlove] move weekplan", {
      domain,
      fromDate,
      toDate,
      key,
      custom: !!custom,
    });
    await hass.callService(domain, "add_weekplan_meal", addData);
    try {
      await hass.callService(domain, "remove_weekplan_meal", removeData);
    } catch (err) {
      // Target day already has the meal; leave it there and surface the error.
      console.error("weekplan move remove-from-source failed", err);
      throw err;
    }
    return true;
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
    const safeCookidoo = safeCookidooUrl(appUrl);
    if (safeCookidoo) {
      window.open(safeCookidoo, "_blank", "noopener,noreferrer");
      return;
    }
    const safeChefkoch = safeChefkochUrl(appUrl);
    if (safeChefkoch) {
      window.open(safeChefkoch, "_blank", "noopener,noreferrer");
      return;
    }
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

  function sourceBadge(source, count) {
    let label = "";
    let cls = "";
    if (source === "cookidoo") {
      label = "Cookidoo";
      cls = "cookidoo";
    } else if (source === "chefkoch") {
      label = "Chefkoch";
      cls = "chefkoch";
    } else if (source === "fwl") {
      label = "FWL";
      cls = "fwl";
    } else {
      return "";
    }
    const suffix =
      count != null && count !== "" ? ` ${esc(String(count))}` : "";
    return `<span class="fwl-src ${cls}" title="${esc(label)}">${esc(label)}${suffix}</span>`;
  }

  function sectionSourceChips(sec) {
    const bits = [];
    if (sec.fwlCount) bits.push(sourceBadge("fwl", sec.fwlCount));
    if (sec.cookCount) bits.push(sourceBadge("cookidoo", sec.cookCount));
    if (sec.chefCount) bits.push(sourceBadge("chefkoch", sec.chefCount));
    return bits.length
      ? `<span class="fwl-src-row">${bits.join("")}</span>`
      : "";
  }

  function metaLine(meal) {
    const bits = [];
    const badge = sourceBadge(meal.source);
    if (badge) bits.push(badge);
    if (meal.preparation_time != null && meal.preparation_time !== "") {
      bits.push(`<span>${esc(`${meal.preparation_time} min`)}</span>`);
    }
    if (meal.rating != null && meal.rating !== "") {
      const votes =
        meal.rating_count != null && meal.rating_count !== ""
          ? ` (${meal.rating_count})`
          : "";
      bits.push(`<span>${esc(`★ ${meal.rating}${votes}`)}</span>`);
    }
    return bits.length
      ? `<div class="fwl-prep">${bits.join('<span class="fwl-prep-sep"> · </span>')}</div>`
      : "";
  }

  function mealThumb(meal, imgSize) {
    const size = imgSize || 72;
    const imgUrl = safeHttpsUrl(meal && meal.image_url);
    if (imgUrl) {
      return `<img src="${esc(imgUrl)}" alt="" width="${size}" height="${size}" style="width:${size}px;max-width:${size}px;height:${size}px;object-fit:cover;border-radius:8px;flex:0 0 auto;" />`;
    }
    // Keep the same footprint as Cookidoo/FWL thumbs when a partner recipe
    // has no real photo (e.g. Chefkoch private recipes without images).
    return `<span class="fwl-thumb-empty" style="width:${size}px;height:${size}px;flex:0 0 auto;border-radius:8px;" aria-hidden="true"></span>`;
  }

  function mealMain(meal, imgSize) {
    const title = esc(meal.title || "");
    const prep = metaLine(meal);
    const img = mealThumb(meal, imgSize);
    const text = `<div class="fwl-text"><strong>${title}</strong>${prep}</div>`;
    const canOpen = meal.app_url || meal.viewer_url;
    if (!canOpen) {
      return `<div class="fwl-main">${img}${text}</div>`;
    }
    return `<button type="button" class="fwl-open fwl-main" ${openDataAttrs(meal.app_url, meal.viewer_url)} title="${esc(openHint())}">
      ${img}${text}
    </button>`;
  }

  function moveIconButton(attrs) {
    return `<button type="button" class="fwl-move fwl-icon-btn" title="Auf anderen Tag verschieben" aria-label="Verschieben" ${attrs}>
      <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="4" width="18" height="18" rx="2"/>
        <path d="M16 2v4M8 2v4M3 10h18"/>
        <path d="M8 14h8M14 14l-2-2 2-2"/>
      </svg>
    </button>`;
  }

  function mealActionAttrs(date, key, custom, source, title) {
    return (
      `data-date="${esc(date)}" data-key="${esc(key)}" data-custom="${custom}" ` +
      `data-source="${esc(source)}" data-title="${esc(title || "")}"`
    );
  }

  function mealRow(meal, dayDate) {
    const date = meal.date || dayDate || "";
    const source = meal.source || "fwl";
    const custom = meal.custom ? "1" : "0";
    const key = meal.custom ? meal.title || "" : meal.recipe_id || "";
    const title = meal.title || "";
    const attrs = mealActionAttrs(date, key, custom, source, title);
    const canAct = Boolean(date && key);
    const remove = canAct
      ? `<button type="button" class="fwl-remove" title="Aus Wochenplan entfernen" aria-label="Entfernen" ${attrs}>×</button>`
      : "";
    const move = canAct ? moveIconButton(attrs) : "";
    const openBtn =
      meal.app_url || meal.viewer_url
        ? openIconButton(meal.app_url, meal.viewer_url)
        : "";
    // Grip starts HTML5 drag (open/move/remove are buttons and block parent drag).
    const grip = canAct
      ? `<span class="fwl-drag-handle" title="Auf anderen Tag ziehen" aria-label="Ziehen" ${attrs}>⠿</span>`
      : "";
    const dragAttrs = canAct
      ? `draggable="true" ${attrs}`
      : "";
    return `<div class="fwl-meal"${dragAttrs ? ` ${dragAttrs}` : ""}>${grip}${mealMain(meal, 72)}${openBtn}${move}${remove}</div>`;
  }

  function mealIdentityFromEl(el) {
    return {
      fromDate: el.getAttribute("data-date") || "",
      key: el.getAttribute("data-key") || "",
      custom: el.getAttribute("data-custom") === "1",
      source: el.getAttribute("data-source") || "fwl",
      title: el.getAttribute("data-title") || "Rezept",
    };
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
        const { title, key, fromDate: date, source, custom } =
          mealIdentityFromEl(btn);
        if (!window.confirm(`„${title}“ aus dem Wochenplan entfernen?`)) {
          return;
        }
        btn.disabled = true;
        try {
          const domain = collectionsDomain(source);
          await hass.callService(
            domain,
            "remove_weekplan_meal",
            weekplanServiceData({ source, date, key, custom })
          );
        } catch (err) {
          console.error("remove weekplan meal failed", err);
          window.alert("Konnte nicht entfernt werden.");
          btn.disabled = false;
        }
      });
    });
  }

  function setMealBusy(mealEl, busy) {
    if (!mealEl) return;
    mealEl.classList.toggle("is-busy", !!busy);
    mealEl.querySelectorAll("button").forEach((b) => {
      b.disabled = !!busy;
    });
  }

  function bindMoves(root, hass, card, { chefCanPlan } = {}) {
    root.querySelectorAll("button.fwl-move").forEach((btn) => {
      btn.addEventListener("click", async (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        const ident = mealIdentityFromEl(btn);
        if (!ident.key || !ident.fromDate) return;
        if (ident.source === "chefkoch" && chefCanPlan === false) {
          window.alert(
            "Chefkoch-Wochenplaner benötigt Chefkoch Plus (meal planner)."
          );
          return;
        }
        const day = await pickDate(`„${ident.title}“ verschieben`);
        if (!day || day === ident.fromDate) return;
        const mealEl = btn.closest(".fwl-meal");
        setMealBusy(mealEl, true);
        if (card) card._moving = true;
        try {
          await moveWeekplanMeal(hass, {
            source: ident.source,
            fromDate: ident.fromDate,
            toDate: day,
            key: ident.key,
            custom: ident.custom,
          });
          if (card) {
            card._moving = false;
            card._partnerKey = "";
            card._loadPartnerMeals().finally(() => card._render());
          }
        } catch (err) {
          console.error("move weekplan meal failed", err);
          const detail = err && (err.message || String(err));
          window.alert(
            ident.source === "chefkoch"
              ? "Konnte nicht verschieben (Plus erforderlich?)."
              : `Konnte nicht verschieben.${detail ? `\n${detail}` : ""}`
          );
          setMealBusy(mealEl, false);
          if (card) card._moving = false;
        }
      });
    });
  }

  function bindDayDnD(root, hass, card, { chefCanPlan } = {}) {
    // Prefer in-memory drag state: HA Lovelace / shadow DOM often drops
    // dataTransfer payloads for custom MIME types.
    root.querySelectorAll(".fwl-meal[draggable='true']").forEach((mealEl) => {
      mealEl.addEventListener("dragstart", (ev) => {
        const fromBtn =
          ev.target && ev.target.closest && ev.target.closest("button");
        const fromHandle =
          ev.target &&
          ev.target.closest &&
          ev.target.closest(".fwl-drag-handle");
        // Allow drag from the grip (or non-button chrome); block from action buttons.
        if (fromBtn && !fromHandle) {
          ev.preventDefault();
          return;
        }
        const ident = mealIdentityFromEl(mealEl);
        if (!ident.key || !ident.fromDate) {
          ev.preventDefault();
          return;
        }
        if (card) card._draggingMeal = { ...ident };
        try {
          ev.dataTransfer.setData("text/plain", JSON.stringify(ident));
          ev.dataTransfer.effectAllowed = "move";
        } catch (_err) {
          /* ignore */
        }
        mealEl.classList.add("is-dragging");
      });
      mealEl.addEventListener("dragend", () => {
        mealEl.classList.remove("is-dragging");
        root.querySelectorAll(".fwl-day.is-drop-target").forEach((d) => {
          d.classList.remove("is-drop-target");
        });
        if (card) card._draggingMeal = null;
      });
    });

    root.querySelectorAll(".fwl-day[data-date]").forEach((dayEl) => {
      dayEl.addEventListener("dragover", (ev) => {
        ev.preventDefault();
        if (ev.dataTransfer) ev.dataTransfer.dropEffect = "move";
        dayEl.classList.add("is-drop-target");
      });
      dayEl.addEventListener("dragleave", (ev) => {
        if (!dayEl.contains(ev.relatedTarget)) {
          dayEl.classList.remove("is-drop-target");
        }
      });
      dayEl.addEventListener("drop", async (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        dayEl.classList.remove("is-drop-target");
        const toDate = dayEl.getAttribute("data-date") || "";
        let ident = card && card._draggingMeal ? { ...card._draggingMeal } : null;
        if (!ident) {
          const raw =
            (ev.dataTransfer && ev.dataTransfer.getData("text/plain")) || "";
          try {
            ident = JSON.parse(raw);
          } catch (_err) {
            ident = null;
          }
        }
        if (card) card._draggingMeal = null;
        if (!ident || !ident.key || !ident.fromDate || !toDate) {
          console.warn("[foodwithlove] drop ignored; missing meal/date", {
            ident,
            toDate,
          });
          return;
        }
        if (ident.fromDate === toDate) return;
        if (ident.source === "chefkoch" && chefCanPlan === false) {
          window.alert(
            "Chefkoch-Wochenplaner benötigt Chefkoch Plus (meal planner)."
          );
          return;
        }
        const mealEl =
          root.querySelector(
            `.fwl-meal[data-date="${CSS.escape(ident.fromDate)}"][data-key="${CSS.escape(ident.key)}"][data-source="${CSS.escape(ident.source || "fwl")}"]`
          ) || null;
        setMealBusy(mealEl, true);
        if (card) card._moving = true;
        try {
          await moveWeekplanMeal(hass, {
            source: ident.source || "fwl",
            fromDate: ident.fromDate,
            toDate,
            key: ident.key,
            custom: !!ident.custom,
          });
          if (card) {
            card._moving = false;
            card._partnerKey = "";
            card._loadPartnerMeals().finally(() => card._render());
          }
        } catch (err) {
          console.error("move weekplan meal (dnd) failed", err);
          const detail = err && (err.message || String(err));
          window.alert(
            ident.source === "chefkoch"
              ? "Konnte nicht verschieben (Plus erforderlich?)."
              : `Konnte nicht verschieben.${detail ? `\n${detail}` : ""}`
          );
          setMealBusy(mealEl, false);
          if (card) card._moving = false;
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
      this._partnerByDay = this._partnerByDay || {};
      this._partnerKey = this._partnerKey || "";
      this._cookLoading = false;
      const configured =
        this._config.week_mode === "calendar" ||
        this._config.week_mode === "rolling"
          ? this._config.week_mode
          : null;
      this._weekMode =
        this._weekMode || readStoredWeekMode() || configured || "rolling";
    }

    set hass(hass) {
      this._hass = hass;
      // Avoid wiping in-flight drag/move UI on every state push.
      if (this._moving || this._draggingMeal) return;
      this._loadPartnerMeals().finally(() => {
        if (this._moving || this._draggingMeal) return;
        this._render();
      });
    }

    getCardSize() {
      return 6;
    }

    _weekModeActive() {
      return this._weekMode === "calendar" ? "calendar" : "rolling";
    }

    _fwlDays() {
      const st = this._hass && this._hass.states[this._config.entity];
      const attrs = (st && st.attributes) || {};
      const mode = this._weekModeActive();
      if (mode === "calendar" && Array.isArray(attrs.days_calendar)) {
        return attrs.days_calendar;
      }
      if (mode === "rolling" && Array.isArray(attrs.days_rolling)) {
        return attrs.days_rolling;
      }
      return attrs.days || [];
    }

    _setWeekMode(mode) {
      const next = mode === "calendar" ? "calendar" : "rolling";
      if (this._weekModeActive() === next) return;
      this._weekMode = next;
      storeWeekMode(next);
      this._partnerKey = "";
      this._loadPartnerMeals().finally(() => this._render());
    }

    _weekMealsFromEntity(entityId) {
      if (!entityId || !this._hass) return null;
      const st = this._hass.states[entityId];
      if (!st) return null;
      const meals = (st.attributes && st.attributes.week_meals) || null;
      return Array.isArray(meals) ? meals : null;
    }

    _mealsFingerprint(meals) {
      if (!Array.isArray(meals)) return "none";
      return `${meals.length}:${meals
        .map(
          (m) =>
            `${m.date || ""}|${m.recipe_id || ""}|${m.title || ""}|${m.image_url || ""}`
        )
        .join(";")}`;
    }

    _pushPartnerMeals(byDay, meals, source, start, last) {
      for (const meal of meals || []) {
        const day = meal.date || "";
        if (!day || day < start || day > last) continue;
        if (!byDay[day]) byDay[day] = [];
        byDay[day].push({ ...meal, source: meal.source || source });
      }
    }

    async _loadCalendarInto(byDay, cal, start, last) {
      const endDate = new Date(`${last}T12:00:00`);
      endDate.setDate(endDate.getDate() + 1);
      const end = endDate.toISOString().slice(0, 10);
      const events = await this._hass.callApi(
        "GET",
        `calendars/${encodeURIComponent(cal)}?start=${encodeURIComponent(start + "T00:00:00")}&end=${encodeURIComponent(end + "T00:00:00")}`
      );
      for (const ev of events || []) {
        const day =
          (ev.start && (ev.start.date || String(ev.start.dateTime || "").slice(0, 10))) ||
          "";
        if (!day) continue;
        const title = ev.summary || "Cookidoo";
        let prep = null;
        const m = String(ev.description || "").match(
          /Total Time:\s*([0-9]+(?:\.[0-9]+)?)/i
        );
        if (m) prep = Math.round(Number(m[1]) / 60);
        if (!byDay[day]) byDay[day] = [];
        byDay[day].push({
          title,
          date: day,
          source: "cookidoo",
          recipe_id: null,
          custom: false,
          app_url: null,
          viewer_url: null,
          preparation_time: prep,
          image_url: null,
        });
      }
      return end;
    }

    async _loadPartnerMeals() {
      if (!this._hass) {
        this._partnerByDay = {};
        this._partnerKey = "";
        return;
      }
      const days = this._fwlDays();
      if (!days.length) return;
      const start = days[0].date;
      const last = days[days.length - 1].date;
      if (!start || !last) return;

      const primaryEntity = this._config.entity || "";
      const cookEnt = findCollectionsEntity(
        this._hass,
        "cookidoo",
        this._config.cookidoo_entity || "",
        primaryEntity
      );
      const chefEnt = findCollectionsEntity(
        this._hass,
        "chefkoch",
        this._config.chefkoch_entity || "",
        primaryEntity
      );
      const cookSt = cookEnt ? this._hass.states[cookEnt] : null;
      const chefSt = chefEnt ? this._hass.states[chefEnt] : null;
      const cookSensor = this._weekMealsFromEntity(cookEnt);
      const chefSensor = this._weekMealsFromEntity(chefEnt);
      const cal = this._config.cookidoo_calendar || "";
      // Prefer cookidoo collections sensor when present; otherwise calendar can fill Cookidoo.
      const needCal = Boolean(cal) && cookSensor === null;

      const key = [
        "mixed",
        cookEnt,
        chefEnt,
        needCal ? cal : "",
        start,
        last,
        cookSt ? cookSt.last_updated : "",
        chefSt ? chefSt.last_updated : "",
        this._mealsFingerprint(cookSensor),
        this._mealsFingerprint(chefSensor),
      ].join("|");
      if (key === this._partnerKey || this._cookLoading) return;

      const byDay = {};
      if (cookSensor) {
        this._pushPartnerMeals(byDay, cookSensor, "cookidoo", start, last);
      }
      if (chefSensor) {
        this._pushPartnerMeals(byDay, chefSensor, "chefkoch", start, last);
      }

      if (!needCal) {
        this._partnerByDay = byDay;
        this._partnerKey = key;
        return;
      }

      this._cookLoading = true;
      try {
        await this._loadCalendarInto(byDay, cal, start, last);
        this._partnerByDay = byDay;
        this._partnerKey = key;
      } catch (err) {
        console.error("fwl cookidoo calendar fetch failed", err);
        // Keep any sensor meals already pushed.
        this._partnerByDay = byDay;
        this._partnerKey = "";
      } finally {
        this._cookLoading = false;
      }
    }

    _mergedDays() {
      const days = this._fwlDays();
      const partners = this._partnerByDay || {};
      return days.map((d) => {
        const fwlMeals = (d.meals || []).map((m) => ({
          ...m,
          source: m.source || "fwl",
          date: m.date || d.date,
        }));
        const partnerMeals = partners[d.date] || [];
        const meals = [...fwlMeals, ...partnerMeals];
        meals.sort((a, b) =>
          String(a.title || "").localeCompare(String(b.title || ""), "de", {
            sensitivity: "base",
          })
        );
        return {
          ...d,
          meals,
          empty: meals.length === 0,
        };
      });
    }

    _chefCanPlan() {
      if (!this._hass) return true;
      const chefEnt = findCollectionsEntity(
        this._hass,
        "chefkoch",
        this._config.chefkoch_entity || "",
        this._config.entity || ""
      );
      if (!chefEnt) return true;
      const st = this._hass.states[chefEnt];
      if (!st || !st.attributes) return true;
      return !!st.attributes.has_meal_planner;
    }

    _render() {
      if (!this._hass || !this._config) return;
      const days = this._mergedDays();
      const root = this.shadowRoot || this.attachShadow({ mode: "open" });
      const mode = this._weekModeActive();
      const title = this._config.title || "Wochenplan";
      let body;
      if (!days.length) {
        body = "<em>Wochenplan wird geladen…</em>";
      } else {
        body = days
          .map((d) => {
            const label = esc(d.label || "");
            const date = esc(d.date || "");
            const head = d.is_today
              ? `<h3 class="fwl-day-label">${label}</h3>`
              : `<div class="fwl-day-label">${label}</div>`;
            const meals = d.empty
              ? `<div class="fwl-day-empty">Keine Rezepte</div>`
              : (d.meals || []).map((m) => mealRow(m, d.date)).join("");
            return `<div class="fwl-day" data-date="${date}">${head}<div class="fwl-day-body">${meals}</div></div>`;
          })
          .join("");
      }
      root.innerHTML = `
        <ha-card>
          <style>${sharedRowStyles()}
            .fwl-week-head {
              display: flex; align-items: center; justify-content: space-between;
              gap: .75rem; margin: 0 0 .65rem; flex-wrap: wrap;
            }
            .fwl-week-head h2 {
              margin: 0; font-size: 1.1rem; flex: 1 1 auto; min-width: 0;
            }
            .fwl-week-mode {
              display: inline-flex; border: 1px solid var(--divider-color, #ddd);
              border-radius: 999px; overflow: hidden; flex: 0 0 auto;
            }
            .fwl-week-mode button {
              appearance: none; border: 0; background: transparent;
              color: var(--secondary-text-color); font: inherit; font-size: .82rem;
              font-weight: 600; padding: .3rem .65rem; cursor: pointer; line-height: 1.2;
            }
            .fwl-week-mode button.is-active {
              background: var(--primary-color, #03a9f4);
              color: var(--text-primary-color, #fff);
            }
            .fwl-day {
              margin: .35rem 0 .85rem;
              padding: .35rem .55rem .55rem;
              border-radius: 10px;
              border: 1px dashed transparent;
              transition: background .12s ease, border-color .12s ease;
            }
            .fwl-day-label {
              margin: .35rem 0 .35rem;
              font-weight: 600;
            }
            h3.fwl-day-label { font-size: 1.05rem; }
            .fwl-day-empty { opacity: .7; min-height: 2.25rem; display: flex; align-items: center; }
            .fwl-day.is-drop-target {
              background: color-mix(in srgb, var(--primary-color, #03a9f4) 12%, transparent);
              border-color: var(--primary-color, #03a9f4);
            }
            .fwl-meal[draggable="true"] { cursor: grab; }
            .fwl-drag-handle {
              flex: 0 0 auto; width: 1.1rem; text-align: center;
              color: var(--secondary-text-color); opacity: .55;
              cursor: grab; user-select: none; font-size: .95rem; line-height: 1;
              padding: .2rem 0;
            }
            .fwl-drag-handle:hover { opacity: .95; }
            .fwl-meal.is-dragging { opacity: .45; }
            .fwl-meal.is-busy { opacity: .55; pointer-events: none; }
            button.fwl-remove {
              appearance: none; border: 1px solid var(--divider-color, #ddd);
              background: transparent; color: var(--secondary-text-color);
              width: 1.75rem; height: 1.75rem; border-radius: 999px;
              font-size: 1.1rem; line-height: 1; cursor: pointer; flex: 0 0 auto;
            }
            button.fwl-remove:hover { color: var(--error-color, #c62828); border-color: currentColor; }
            button.fwl-remove:disabled, button.fwl-move:disabled { opacity: .4; cursor: wait; }
          </style>
          <div style="padding:12px 16px 16px;">
            <div class="fwl-week-head">
              <h2>${esc(title)}</h2>
              <div class="fwl-week-mode" role="group" aria-label="Wochenansicht">
                <button type="button" data-mode="rolling" class="${mode === "rolling" ? "is-active" : ""}" title="Ab heute (7 Tage)">Ab heute</button>
                <button type="button" data-mode="calendar" class="${mode === "calendar" ? "is-active" : ""}" title="Kalenderwoche Mo–So">Mo–So</button>
              </div>
            </div>
            ${body}
          </div>
        </ha-card>`;
      root.querySelectorAll(".fwl-week-mode button").forEach((btn) => {
        btn.addEventListener("click", (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          this._setWeekMode(btn.getAttribute("data-mode") || "rolling");
        });
      });
      const moveOpts = { chefCanPlan: this._chefCanPlan() };
      bindOpens(root, this._hass);
      bindRemoves(root, this._hass);
      bindMoves(root, this._hass, this, moveOpts);
      bindDayDnD(root, this._hass, this, moveOpts);
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
      .fwl-thumb-empty {
        display: inline-block; box-sizing: border-box;
        background: color-mix(in srgb, var(--secondary-text-color, #888) 18%, transparent);
        border: 1px solid var(--divider-color, #3333);
      }
      .fwl-text { min-width: 0; line-height: 1.3; }
      .fwl-text strong { display: block; }
      .fwl-prep {
        opacity: .75; font-weight: 400; font-size: .92em; margin-top: .15rem;
        display: flex; flex-wrap: wrap; align-items: center; gap: .25rem;
      }
      .fwl-prep-sep { opacity: .7; }
      .fwl-src {
        flex: 0 0 auto; border-radius: 4px; padding: .05rem .3rem;
        font-size: .65rem; font-weight: 700; line-height: 1.2;
        display: inline-flex; align-items: center; justify-content: center;
        white-space: nowrap; opacity: 1;
      }
      .fwl-src.fwl { background: #e8f5e9; color: #2e7d32; }
      .fwl-src.cookidoo { background: #e3f2fd; color: #1565c0; }
      .fwl-src.chefkoch { background: #fff3e0; color: #ef6c00; }
      .fwl-src-row {
        display: inline-flex; flex-wrap: wrap; gap: .25rem; align-items: center;
        margin-left: .35rem;
      }
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

  function todayRecipeFromEntity(hass, entityId, sourceLabel) {
    if (!hass || !entityId) return null;
    const st = hass.states[entityId];
    if (!st || st.state == null || st.state === "" || st.state === "unknown" || st.state === "unavailable") {
      return null;
    }
    const attrs = st.attributes || {};
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
    return {
      source: sourceLabel,
      title: String(st.state),
      img,
      meta: metaBits.join(" · "),
      app_url: attrs.app_url || null,
      viewer_url: attrs.viewer_url || null,
      content: stripHtml(String(attrs.content || "").replace(/<br\s*\/?>/gi, " ")),
    };
  }

  function compactTodayTile(item) {
    if (!item) return "";
    const canOpen = item.app_url || item.viewer_url;
    const body = `
      ${
        item.img
          ? `<img class="thumb" src="${esc(item.img)}" alt="" loading="eager" decoding="async" />`
          : `<span class="thumb empty"></span>`
      }
      <span class="text">
        <span class="src">${esc(item.source)}</span>
        <span class="name">${esc(item.title)}</span>
        ${item.meta ? `<span class="meta">${esc(item.meta)}</span>` : ""}
      </span>`;
    if (canOpen) {
      return `<button type="button" class="fwl-open fwl-today-tile" ${openDataAttrs(
        item.app_url,
        item.viewer_url
      )} title="${esc(openHint())}">${body}</button>`;
    }
    return `<div class="fwl-today-tile">${body}</div>`;
  }

  class FwlRecipeCard extends HTMLElement {
    setConfig(config) {
      this._config = config || {};
      if (!this._config.entity) {
        throw new Error("entity is required");
      }
      this._todaySig = this._todaySig || "";
    }

    set hass(hass) {
      this._hass = hass;
      this._render();
    }

    getCardSize() {
      return 5;
    }

    _collectTodayItems() {
      const items = [];
      const fwl = todayRecipeFromEntity(
        this._hass,
        this._config.entity,
        "FWL"
      );
      if (fwl) items.push(fwl);
      const cookEnt =
        this._config.cookidoo_entity ||
        "sensor.cookidoo_collections_rezept_des_tages";
      const chefEnt =
        this._config.chefkoch_entity ||
        "sensor.chefkoch_collections_rezept_des_tages";
      // Only auto-include partners when the entity exists (or was configured).
      if (this._config.cookidoo_entity || this._hass.states[cookEnt]) {
        const cook = todayRecipeFromEntity(this._hass, cookEnt, "Cookidoo");
        if (cook) items.push(cook);
      }
      if (this._config.chefkoch_entity || this._hass.states[chefEnt]) {
        const chef = todayRecipeFromEntity(this._hass, chefEnt, "Chefkoch");
        if (chef) items.push(chef);
      }
      return items;
    }

    _render() {
      if (!this._hass || !this._config) return;
      const items = this._collectTodayItems();
      const gEnt = this._config.greeting_entity;
      const greeting =
        gEnt && this._hass.states[gEnt] ? this._hass.states[gEnt].state : "";
      // Long FWL blurb only when showing a single FWL tile (legacy layout).
      const content =
        items.length === 1 && items[0].source === "FWL" ? items[0].content : "";
      const title = this._config.title || "Rezept des Tages";
      // Skip DOM rebuild when nothing visible changed — full innerHTML
      // replaces <img> nodes and causes constant photo flicker on hass ticks.
      const sig = JSON.stringify({
        title,
        greeting,
        content,
        items: items.map((it) => [
          it.source,
          it.title,
          it.img,
          it.meta,
          it.app_url,
          it.viewer_url,
        ]),
      });
      if (sig === this._todaySig && this.shadowRoot && this.shadowRoot.firstChild) {
        return;
      }
      this._todaySig = sig;

      const root = this.shadowRoot || this.attachShadow({ mode: "open" });
      const grid = items.map(compactTodayTile).join("");
      root.innerHTML = `
        <ha-card>
          <style>
            .pad { padding: 10px 12px 12px; }
            .head {
              display: flex; align-items: baseline; justify-content: space-between;
              gap: .5rem; margin-bottom: .55rem;
            }
            .head h2 { margin: 0; font-size: 1.05rem; }
            .grid {
              display: flex; flex-direction: column; gap: .45rem;
            }
            button.fwl-today-tile, .fwl-today-tile {
              appearance: none; border: 1px solid var(--divider-color, #3333);
              background: transparent; color: inherit; font: inherit;
              text-align: left; cursor: pointer; display: flex; flex-direction: row;
              align-items: center; gap: .7rem; padding: .45rem .55rem;
              border-radius: 10px; width: 100%; box-sizing: border-box; min-width: 0;
            }
            button.fwl-today-tile:hover { border-color: var(--primary-color, #03a9f4); }
            .fwl-today-tile .thumb {
              width: 72px; height: 72px; flex: 0 0 72px; object-fit: cover;
              border-radius: 8px; background: var(--divider-color, #eee);
              display: block;
            }
            .fwl-today-tile .thumb.empty { width: 72px; height: 72px; }
            .fwl-today-tile .text {
              display: flex; flex-direction: column; gap: .15rem; min-width: 0; flex: 1;
            }
            .fwl-today-tile .src {
              font-size: .7rem; font-weight: 700; letter-spacing: .02em;
              text-transform: uppercase; opacity: .7;
            }
            .fwl-today-tile .name {
              font-weight: 650; font-size: .95rem; line-height: 1.3;
              display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;
              overflow: hidden;
            }
            .fwl-today-tile .meta { opacity: .75; font-size: .8rem; }
            .greeting { font-style: italic; margin-top: .65rem; opacity: .85; font-size: .9rem; }
            .blurb { margin-top: .55rem; line-height: 1.4; font-size: .9rem; opacity: .9;
              display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
          </style>
          <div class="pad">
            <div class="head">
              <h2>${esc(title)}</h2>
            </div>
            ${items.length ? `<div class="grid">${grid}</div>` : "<em>Kein Rezept des Tages</em>"}
            ${greeting ? `<div class="greeting">${esc(greeting)}</div>` : ""}
            ${content ? `<div class="blurb">${esc(content)}</div>` : ""}
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

  function promptText(title, placeholder) {
    return new Promise((resolve) => {
      const existing = document.getElementById("fwl-text-prompt");
      if (existing) existing.remove();

      const backdrop = document.createElement("div");
      backdrop.id = "fwl-text-prompt";
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
      heading.textContent = title || "";

      const input = document.createElement("input");
      input.type = "text";
      input.placeholder = placeholder || "";
      input.maxLength = 80;
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
      ok.textContent = "Anlegen";
      ok.style.cssText = buttonStyle(true);

      const close = (value) => {
        backdrop.remove();
        resolve(value);
      };
      cancel.addEventListener("click", () => close(null));
      backdrop.addEventListener("click", (ev) => {
        if (ev.target === backdrop) close(null);
      });
      ok.addEventListener("click", () => close((input.value || "").trim() || null));
      input.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") close((input.value || "").trim() || null);
      });

      row.append(cancel, ok);
      panel.append(heading, input, row);
      backdrop.append(panel);
      document.body.append(backdrop);
      input.focus();
    });
  }

  /** Chefkoch private recipe: name + description + collection. */
  function promptPrivateRecipe(title, folders) {
    return new Promise((resolve) => {
      const existing = document.getElementById("fwl-private-recipe-prompt");
      if (existing) existing.remove();

      const fieldStyle =
        "width:100%;font:inherit;padding:.5rem;border-radius:8px;" +
        "border:1px solid var(--divider-color,#ccc);margin-bottom:.75rem;" +
        "background:transparent;color:inherit;box-sizing:border-box;";

      const backdrop = document.createElement("div");
      backdrop.id = "fwl-private-recipe-prompt";
      backdrop.style.cssText =
        "position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,.45);" +
        "display:flex;align-items:center;justify-content:center;padding:1rem;";

      const panel = document.createElement("div");
      panel.style.cssText =
        "background:var(--card-background-color,#fff);color:var(--primary-text-color);" +
        "border-radius:12px;padding:1rem 1.1rem;min-width:min(340px,100%);" +
        "box-shadow:0 12px 40px rgba(0,0,0,.35);";

      const heading = document.createElement("div");
      heading.style.cssText = "font-weight:650;margin-bottom:.75rem;";
      heading.textContent = title || "Privates Rezept anlegen";

      const nameInput = document.createElement("input");
      nameInput.type = "text";
      nameInput.placeholder = "Name";
      nameInput.maxLength = 120;
      nameInput.style.cssText = fieldStyle;

      const descInput = document.createElement("textarea");
      descInput.placeholder = "Beschreibung (optional)";
      descInput.rows = 4;
      descInput.style.cssText = fieldStyle + "resize:vertical;min-height:5rem;";

      const select = document.createElement("select");
      select.style.cssText = fieldStyle;
      const folderOptions = [
        { id: "", name: "Hauptsammlung" },
        ...(folders || []).map((f) => ({
          id: f.id,
          name: f.name || "Ordner",
        })),
      ];
      for (const opt of folderOptions) {
        const el = document.createElement("option");
        el.value = opt.id;
        el.textContent = opt.name;
        select.append(el);
      }

      const row = document.createElement("div");
      row.style.cssText = "display:flex;justify-content:flex-end;gap:.5rem;";

      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.textContent = "Abbrechen";
      cancel.style.cssText = buttonStyle();
      const ok = document.createElement("button");
      ok.type = "button";
      ok.textContent = "Anlegen";
      ok.style.cssText = buttonStyle(true);

      const close = (value) => {
        backdrop.remove();
        resolve(value);
      };
      cancel.addEventListener("click", () => close(null));
      backdrop.addEventListener("click", (ev) => {
        if (ev.target === backdrop) close(null);
      });
      ok.addEventListener("click", () => {
        const name = (nameInput.value || "").trim();
        if (!name) {
          nameInput.focus();
          return;
        }
        close({
          name,
          description: (descInput.value || "").trim(),
          folderId: select.value || "",
        });
      });
      nameInput.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          ok.click();
        }
      });

      row.append(cancel, ok);
      panel.append(heading, nameInput, descInput, select, row);
      backdrop.append(panel);
      document.body.append(backdrop);
      nameInput.focus();
    });
  }

  function pickFolder(title, folders, currentId, optionsCfg) {
    return new Promise((resolve) => {
      const existing = document.getElementById("fwl-folder-picker");
      if (existing) existing.remove();

      const backdrop = document.createElement("div");
      backdrop.id = "fwl-folder-picker";
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
      heading.textContent = title || "Ordner wählen";

      const select = document.createElement("select");
      select.style.cssText =
        "width:100%;font:inherit;padding:.5rem;border-radius:8px;" +
        "border:1px solid var(--divider-color,#ccc);margin-bottom:.85rem;" +
        "background:transparent;color:inherit;box-sizing:border-box;";

      const emptyLabel =
        (optionsCfg && optionsCfg.emptyLabel) || "Ohne Ordner";
      const options = [
        { id: "", name: emptyLabel },
        ...folders.map((f) => ({ id: f.id, name: f.name || "Ordner" })),
      ];
      for (const opt of options) {
        const el = document.createElement("option");
        el.value = opt.id;
        el.textContent = opt.name;
        if (
          (currentId || "") === (opt.id || "") ||
          (currentId === "__uncategorized__" && !opt.id)
        ) {
          el.selected = true;
        }
        select.append(el);
      }

      const row = document.createElement("div");
      row.style.cssText = "display:flex;justify-content:flex-end;gap:.5rem;";

      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.textContent = "Abbrechen";
      cancel.style.cssText = buttonStyle();
      const ok = document.createElement("button");
      ok.type = "button";
      ok.textContent = "Verschieben";
      ok.style.cssText = buttonStyle(true);

      const close = (value) => {
        backdrop.remove();
        resolve(value);
      };
      cancel.addEventListener("click", () => close(undefined));
      backdrop.addEventListener("click", (ev) => {
        if (ev.target === backdrop) close(undefined);
      });
      ok.addEventListener("click", () => close(select.value));

      row.append(cancel, ok);
      panel.append(heading, select, row);
      backdrop.append(panel);
      document.body.append(backdrop);
      select.focus();
    });
  }

  /** Normalize folder titles so FWL + Cookidoo categories can merge. */
  function folderMergeKey(name) {
    const raw = String(name || "")
      .trim()
      .toLowerCase()
      .replace(/\s+/g, " ");
    const aliases = {
      salat: "salat",
      "kuchen & gebäck": "kuchen",
      kuchen: "kuchen",
      "snack & fingerfood": "snack",
      fingerfood: "snack",
      snack: "snack",
      "beilagen & saucen": "beilagen",
      saucen: "beilagen",
      dip: "beilagen",
      getränke: "getränke",
      getranke: "getränke",
      nachtisch: "nachtisch",
      muffins: "muffins",
      suppe: "suppe",
      hauptgericht: "hauptgericht",
    };
    return aliases[raw] || raw;
  }

  function normalizeSearch(text) {
    return String(text || "")
      .toLocaleLowerCase("de")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .trim();
  }

  function recipeMatchesQuery(recipe, queryNorm) {
    if (!queryNorm) return true;
    return normalizeSearch(recipe && recipe.title).includes(queryNorm);
  }

  function filterFavoriteSections(sections, query) {
    const q = normalizeSearch(query);
    if (!q) {
      return { sections, matchCount: null, active: false };
    }
    let matchCount = 0;
    const filtered = [];
    for (const sec of sections || []) {
      const folderHit = normalizeSearch(sec.name).includes(q);
      const recipeHits = (sec.recipes || []).filter((r) =>
        recipeMatchesQuery(r, q)
      );
      if (!folderHit && !recipeHits.length) continue;
      // Folder name match → keep all recipes; otherwise only title hits.
      const shown = folderHit ? sec.recipes || [] : recipeHits;
      matchCount += shown.length;
      filtered.push({
        ...sec,
        recipes: shown,
        count: shown.length,
        _searchHit: true,
      });
    }
    return { sections: filtered, matchCount, active: true };
  }

  function folderDisplayName(key, preferred) {
    const titles = {
      salat: "Salat",
      kuchen: "Kuchen",
      snack: "Snack",
      beilagen: "Beilagen & Saucen",
      getränke: "Getränke",
      nachtisch: "Nachtisch",
      muffins: "Muffins",
      suppe: "Suppe",
      hauptgericht: "Hauptgericht",
    };
    if (titles[key]) return titles[key];
    const name = String(preferred || key || "Ordner").trim();
    return name ? name.charAt(0).toUpperCase() + name.slice(1) : "Ordner";
  }

  function favoriteRecipeRow(recipe, folderIdForSource, options) {
    const rid = recipe.recipe_id || "";
    const source = recipe.source || "fwl";
    const canPlan = !options || options.canPlan !== false;
    const openBtn = openIconButton(recipe.app_url, recipe.viewer_url);
    const folderId = folderIdForSource || recipe.folder_id || "";
    if (!rid) {
      return `<div class="fwl-fav-recipe">${mealMain(recipe, 72)}${openBtn}</div>`;
    }
    const planBtn = canPlan
      ? `<button type="button" class="fwl-add" title="Zum Wochenplan" aria-label="Zum Wochenplan"
        data-recipe-id="${esc(rid)}" data-title="${esc(recipe.title || "")}" data-source="${esc(source)}">+</button>`
      : `<button type="button" class="fwl-add" disabled title="Chefkoch Plus Wochenplaner erforderlich" aria-label="Wochenplaner nicht verfügbar">+</button>`;
    return `<div class="fwl-fav-recipe">${mealMain(recipe, 72)}${openBtn}
      <button type="button" class="fwl-move" title="In Ordner verschieben" aria-label="In Ordner verschieben"
        data-recipe-id="${esc(rid)}" data-title="${esc(recipe.title || "")}" data-folder-id="${esc(folderId)}" data-source="${esc(source)}">↦</button>
      ${planBtn}
    </div>`;
  }

  function partnerEntityAvailable(hass, entityId) {
    if (!hass || !entityId) return false;
    const st = hass.states[entityId];
    if (!st) return false;
    return st.state !== "unavailable" && st.state !== "unknown";
  }

  /**
   * Resolve cookidoo/chefkoch collections sensors.
   * Prefer explicit config, otherwise auto-discover by attributes.source
   * (or entity_id pattern) so join works without YAML edits.
   */
  function findCollectionsEntity(hass, source, configuredId, excludeId) {
    if (configuredId && partnerEntityAvailable(hass, configuredId)) {
      return configuredId;
    }
    if (!hass || !hass.states) return "";
    const needle =
      source === "chefkoch"
        ? "chefkoch_collections"
        : source === "cookidoo"
          ? "cookidoo_collections"
          : "";
    let byPattern = "";
    for (const entityId of Object.keys(hass.states)) {
      if (entityId === excludeId || entityId === configuredId) continue;
      if (!entityId.startsWith("sensor.")) continue;
      const st = hass.states[entityId];
      if (!st || st.state === "unavailable" || st.state === "unknown") continue;
      const attrs = st.attributes || {};
      const hasFolders = Array.isArray(attrs.favorite_folders);
      if (!hasFolders) continue;
      if (attrs.source === source) return entityId;
      if (
        !byPattern &&
        needle &&
        entityId.includes(needle)
      ) {
        byPattern = entityId;
      }
    }
    return byPattern;
  }

  function partnerFolderStats(folders, uncategorized) {
    const folderCount = (folders || []).length;
    const recipeCount =
      (uncategorized || []).length +
      (folders || []).reduce(
        (sum, f) => sum + ((f.recipes && f.recipes.length) || Number(f.count) || 0),
        0
      );
    return { folderCount, recipeCount };
  }

  class FwlFavoritesCard extends HTMLElement {
    setConfig(config) {
      this._config = config || {};
      if (!this._config.entity) {
        throw new Error("entity is required");
      }
      this._open = this._open || new Set();
      this._chefPayload = this._chefPayload || null;
      this._chefPayloadKey = this._chefPayloadKey || "";
      this._chefLoading = false;
      this._chefError = "";
      this._favQuery = this._favQuery || "";
    }

    set hass(hass) {
      this._hass = hass;
      this._loadChefkochFavorites().finally(() => this._render());
    }

    getCardSize() {
      return 6;
    }

    async _loadChefkochFavorites() {
      if (!this._hass || this._chefLoading) return;
      const primaryEntity = (this._config && this._config.entity) || "";
      const chefEnt = findCollectionsEntity(
        this._hass,
        "chefkoch",
        (this._config && this._config.chefkoch_entity) || "",
        primaryEntity
      );
      const chefSt = chefEnt ? this._hass.states[chefEnt] : null;
      const stateKey = chefSt
        ? `${chefEnt}|${chefSt.last_updated}|${chefSt.state}`
        : "none";
      // Always try the dedicated API (full nested folders/recipes).
      const apiKey = `api|${stateKey}`;
      if (apiKey === this._chefPayloadKey && this._chefPayload) return;

      this._chefLoading = true;
      try {
        const data = await this._hass.callApi(
          "GET",
          "chefkoch_collections/favorites"
        );
        if (
          data &&
          (Array.isArray(data.favorite_folders) ||
            Array.isArray(data.uncategorized))
        ) {
          this._chefPayload = data;
          this._chefPayloadKey = apiKey;
          this._chefError = "";
          return;
        }
      } catch (err) {
        // Fall back to entity attributes when API is unavailable.
        this._chefError = String((err && err.message) || err || "api_error");
      } finally {
        this._chefLoading = false;
      }

      // Cache under apiKey so we do not re-hit the API until the sensor changes.
      if (chefSt && chefSt.attributes) {
        this._chefPayload = {
          favorite_folders: chefSt.attributes.favorite_folders || [],
          uncategorized: chefSt.attributes.uncategorized || [],
          favorite_count: chefSt.attributes.favorite_count || chefSt.state,
          has_meal_planner: !!chefSt.attributes.has_meal_planner,
          week_meals: chefSt.attributes.week_meals || [],
          source: "chefkoch",
          entity_id: chefEnt,
        };
        this._chefPayloadKey = apiKey;
      } else {
        this._chefPayload = null;
        this._chefPayloadKey = apiKey;
      }
    }

    _toggle(id) {
      this._userClosed = this._userClosed || new Set();
      if (this._open.has(id)) {
        this._open.delete(id);
        this._userClosed.add(id);
      } else {
        this._open.add(id);
        this._userClosed.delete(id);
      }
      this._render();
    }

    _tagRecipes(recipes, source) {
      return (recipes || []).map((r) => ({ ...r, source: r.source || source }));
    }

    _mergeFavoriteSections(folders, uncategorized, partners, primarySource) {
      const byKey = new Map();
      const primary = primarySource || "fwl";
      const primaryCountKey =
        primary === "cookidoo"
          ? "cookCount"
          : primary === "chefkoch"
            ? "chefCount"
            : "fwlCount";
      const primaryIdKey =
        primary === "cookidoo"
          ? "cookFolderId"
          : primary === "chefkoch"
            ? "chefFolderId"
            : "fwlFolderId";

      const ensure = (name) => {
        const key = folderMergeKey(name);
        let sec = byKey.get(key);
        if (!sec) {
          sec = {
            id: key,
            name: folderDisplayName(key, name),
            recipes: [],
            fwlFolderId: null,
            cookFolderId: null,
            chefFolderId: null,
            fwlCount: 0,
            cookCount: 0,
            chefCount: 0,
          };
          byKey.set(key, sec);
        }
        return sec;
      };

      const ensureUncategorized = () => {
        let sec = byKey.get("__uncategorized__");
        if (!sec) {
          sec = {
            id: "__uncategorized__",
            name: "Ohne Ordner",
            recipes: [],
            fwlFolderId: null,
            cookFolderId: null,
            chefFolderId: null,
            fwlCount: 0,
            cookCount: 0,
            chefCount: 0,
          };
          byKey.set(sec.id, sec);
        }
        return sec;
      };

      if (uncategorized.length) {
        const sec = ensureUncategorized();
        sec.recipes.push(...this._tagRecipes(uncategorized, primary));
        sec[primaryCountKey] = uncategorized.length;
      }

      for (const f of folders) {
        const sec = ensure(f.name || "Ordner");
        if (f.id) sec[primaryIdKey] = f.id;
        sec.name = folderDisplayName(folderMergeKey(f.name), f.name);
        const tagged = this._tagRecipes(f.recipes || [], primary).map((r) => ({
          ...r,
          folder_id: f.id || r.folder_id || null,
        }));
        sec.recipes.push(...tagged);
        sec[primaryCountKey] = tagged.length;
      }

      for (const partner of partners || []) {
        const source = partner.source;
        const idKey =
          source === "cookidoo"
            ? "cookFolderId"
            : source === "chefkoch"
              ? "chefFolderId"
              : null;
        const countKey =
          source === "cookidoo"
            ? "cookCount"
            : source === "chefkoch"
              ? "chefCount"
              : null;
        if (!idKey) continue;
        const partnerUncategorized = partner.uncategorized || [];
        if (partnerUncategorized.length) {
          const sec = ensureUncategorized();
          const tagged = this._tagRecipes(partnerUncategorized, source);
          sec.recipes.push(...tagged);
          sec[countKey] = (sec[countKey] || 0) + tagged.length;
        }
        for (const f of partner.folders || []) {
          const sec = ensure(f.name || "Ordner");
          if (f.id) sec[idKey] = f.id;
          if (!sec.fwlFolderId) {
            sec.name = folderDisplayName(folderMergeKey(f.name), f.name);
          }
          const tagged = this._tagRecipes(f.recipes || [], source).map((r) => ({
            ...r,
            folder_id: f.id || r.folder_id || null,
          }));
          sec.recipes.push(...tagged);
          sec[countKey] = (sec[countKey] || 0) + tagged.length;
        }
      }

      const sections = [...byKey.values()].map((sec) => {
        sec.recipes.sort((a, b) =>
          String(a.title || "").localeCompare(String(b.title || ""), "de", {
            sensitivity: "base",
          })
        );
        sec.count = sec.recipes.length;
        sec.deletable =
          (!!sec.fwlFolderId && sec.fwlCount === 0) ||
          (!!sec.cookFolderId && sec.cookCount === 0) ||
          (!!sec.chefFolderId && sec.chefCount === 0);
        if (sec.id !== "__uncategorized__") {
          sec.id =
            sec.fwlFolderId ||
            (sec.cookFolderId
              ? `cook:${sec.cookFolderId}`
              : sec.chefFolderId
                ? `chef:${sec.chefFolderId}`
                : `merged:${sec.id}`);
        }
        return sec;
      });

      sections.sort((a, b) => {
        if (a.id === "__uncategorized__") return -1;
        if (b.id === "__uncategorized__") return 1;
        return String(a.name).localeCompare(String(b.name), "de", {
          sensitivity: "base",
        });
      });
      return sections;
    }

    _render() {
      if (!this._hass || !this._config) return;
      const st = this._hass.states[this._config.entity];
      const attrs = (st && st.attributes) || {};
      let folders = attrs.favorite_folders || [];
      let uncategorized = attrs.uncategorized || [];
      // Prefer sensor-declared source so a Chefkoch/Cookidoo primary entity
      // is not mis-tagged as FWL (which hid the Chefkoch badge).
      const primarySource =
        attrs.source === "chefkoch" || attrs.source === "cookidoo"
          ? attrs.source
          : "fwl";
      let total = Number(attrs.favorite_count || (st && st.state) || 0) || 0;
      const primaryEntity = this._config.entity || "";
      const cookEnt = findCollectionsEntity(
        this._hass,
        "cookidoo",
        this._config.cookidoo_entity || "",
        primaryEntity
      );
      const chefEnt = findCollectionsEntity(
        this._hass,
        "chefkoch",
        this._config.chefkoch_entity || "",
        primaryEntity
      );
      const partners = [];
      const labels = [
        primarySource === "chefkoch"
          ? "Chefkoch"
          : primarySource === "cookidoo"
            ? "Cookidoo"
            : "FWL",
      ];
      let cookFolders = [];
      let chefFolders = [];
      let chefCanPlan = true;
      let chefJoinWarn = "";
      if (cookEnt) {
        const cookSt = this._hass.states[cookEnt];
        const cookAttrs = (cookSt && cookSt.attributes) || {};
        cookFolders = cookAttrs.favorite_folders || [];
        const cookUnc = cookAttrs.uncategorized || [];
        total +=
          Number(cookAttrs.favorite_count || (cookSt && cookSt.state) || 0) || 0;
        partners.push({
          source: "cookidoo",
          folders: cookFolders,
          uncategorized: cookUnc,
          entity: cookEnt,
        });
        if (!labels.includes("Cookidoo")) labels.push("Cookidoo");
      }
      // Prefer API payload (full nested recipes); fall back to entity attrs.
      const chefPayload = this._chefPayload;
      const chefPayloadOk =
        !!chefPayload &&
        (Array.isArray(chefPayload.favorite_folders) ||
          Array.isArray(chefPayload.uncategorized));
      if (chefPayloadOk && primarySource === "chefkoch") {
        // Primary is Chefkoch: replace truncated state attrs with API data.
        chefFolders = chefPayload.favorite_folders || [];
        uncategorized = chefPayload.uncategorized || [];
        folders = chefFolders;
        chefCanPlan = !!chefPayload.has_meal_planner;
        total = Number(
          chefPayload.favorite_count != null
            ? chefPayload.favorite_count
            : partnerFolderStats(chefFolders, uncategorized).recipeCount
        );
      } else if (chefPayloadOk) {
        chefFolders = chefPayload.favorite_folders || [];
        const chefUnc = chefPayload.uncategorized || [];
        chefCanPlan = !!chefPayload.has_meal_planner;
        total +=
          Number(
            chefPayload.favorite_count != null
              ? chefPayload.favorite_count
              : partnerFolderStats(chefFolders, chefUnc).recipeCount
          ) || 0;
        partners.push({
          source: "chefkoch",
          folders: chefFolders,
          uncategorized: chefUnc,
          entity: chefEnt || "api:chefkoch_collections",
        });
        if (!labels.includes("Chefkoch")) labels.push("Chefkoch");
      } else if (this._config.chefkoch_entity) {
        chefJoinWarn = `Chefkoch: ${this._config.chefkoch_entity} nicht verfügbar`;
      } else if (this._chefError) {
        chefJoinWarn =
          "Chefkoch: API nicht erreichbar — Collections-Integration aktualisieren";
      }
      const joined = partners.length > 0 || primarySource === "chefkoch";
      const allSections = this._mergeFavoriteSections(
        folders,
        uncategorized,
        partners,
        primarySource
      );
      const search = filterFavoriteSections(allSections, this._favQuery || "");
      const sections = search.sections;

      // Keep Chefkoch folders expanded until the user collapses them.
      this._userClosed = this._userClosed || new Set();
      if (chefPayloadOk) {
        for (const sec of allSections) {
          if (sec.chefCount > 0 && !this._userClosed.has(sec.id)) {
            this._open.add(sec.id);
          }
        }
      }
      // While searching, expand every hit so matches are visible.
      if (search.active) {
        for (const sec of sections) {
          this._open.add(sec.id);
        }
      }

      let body;
      if (!allSections.length) {
        body = "<em>Keine Favoriten</em>";
      } else if (search.active && !sections.length) {
        body = "<em>Keine Treffer</em>";
      } else {
        body = sections
          .map((sec) => {
            const open = search.active || this._open.has(sec.id);
            const chev = open ? "▾" : "▸";
            const recipes = open
              ? (sec.recipes || [])
                  .map((r) => {
                    let folderForSource = r.folder_id || "";
                    if (!folderForSource) {
                      if (r.source === "cookidoo") {
                        folderForSource = sec.cookFolderId || "";
                      } else if (r.source === "chefkoch") {
                        folderForSource = sec.chefFolderId || "";
                      } else {
                        folderForSource = sec.fwlFolderId || "";
                      }
                    }
                    return favoriteRecipeRow(r, folderForSource, {
                      canPlan:
                        r.source !== "chefkoch" ? true : chefCanPlan,
                    });
                  })
                  .join("")
              : "";
            let del = "";
            if (sec.deletable) {
              if (sec.fwlFolderId && sec.fwlCount === 0) {
                del += `<button type="button" class="fwl-del-folder" title="Leeren FWL-Ordner löschen" aria-label="FWL-Ordner löschen" data-folder-id="${esc(sec.fwlFolderId)}" data-source="fwl">×</button>`;
              }
              if (sec.cookFolderId && sec.cookCount === 0) {
                del += `<button type="button" class="fwl-del-folder" title="Leeren Cookidoo-Ordner löschen" aria-label="Cookidoo-Ordner löschen" data-folder-id="${esc(sec.cookFolderId)}" data-source="cookidoo">×</button>`;
              }
              if (sec.chefFolderId && sec.chefCount === 0) {
                del += `<button type="button" class="fwl-del-folder" title="Leeren Chefkoch-Ordner löschen" aria-label="Chefkoch-Ordner löschen" data-folder-id="${esc(sec.chefFolderId)}" data-source="chefkoch">×</button>`;
              }
            }
            return `<div class="fwl-folder">
              <div class="fwl-folder-row">
                <button type="button" class="fwl-folder-head" data-id="${esc(sec.id)}">
                  <span class="chev">${chev}</span>
                  <span class="name">${esc(sec.name)}</span>
                  ${sectionSourceChips(sec)}
                  <span class="count">${esc(sec.count)}</span>
                </button>
                ${del}
              </div>
              ${
                open
                  ? `<div class="fwl-folder-body">${
                      recipes ||
                      (sec.chefFolderId && !sec.chefCount
                        ? "<em>Chefkoch-Ordner ohne Rezeptdaten — Collections aktualisieren (API)</em>"
                        : "<em>Leer</em>")
                    }</div>`
                  : ""
              }
            </div>`;
          })
          .join("");
      }

      const summary = joined
        ? `${total} Favoriten (${labels.join(" + ")})`
        : `${total} Favoriten`;
      const searchHintText =
        search.active && search.matchCount != null
          ? `${search.matchCount} Treffer`
          : "";
      const showChefRecipeBtn =
        chefPayloadOk ||
        primarySource === "chefkoch" ||
        partners.some((p) => p.source === "chefkoch");

      // Context for once-bound header actions + per-render body handlers.
      this._favCtx = {
        chefFolders,
        cookFolders,
        folders,
        partners,
        labels,
        joined,
        chefCanPlan,
      };

      const root = this.shadowRoot || this.attachShadow({ mode: "open" });
      // Keep the search <input> mounted — replacing innerHTML steals focus
      // (document.activeElement is the host inside open shadow trees).
      if (!root.querySelector("ha-card.fwl-fav-shell")) {
        root.innerHTML = `
        <ha-card class="fwl-fav-shell">
          <style>${sharedRowStyles()}
            .pad { padding: 12px 16px 16px; }
            .summary-row {
              display: flex; align-items: center; justify-content: space-between;
              gap: .75rem; margin-bottom: .65rem;
            }
            .summary { opacity: .75; font-size: .95rem; }
            .join-status.warn {
              margin: -.35rem 0 .65rem;
              color: var(--warning-color, #f44336);
              font-size: .85rem; font-weight: 600;
            }
            .fwl-search-row { margin: 0 0 .65rem; }
            input.fwl-fav-search {
              width: 100%; font: inherit; padding: .45rem .65rem;
              border-radius: 8px; border: 1px solid var(--divider-color, #ddd);
              background: transparent; color: inherit; box-sizing: border-box;
            }
            input.fwl-fav-search:focus {
              outline: none; border-color: var(--primary-color, #03a9f4);
            }
            .search-hint {
              margin: -.35rem 0 .55rem; opacity: .7; font-size: .85rem;
              min-height: 1.1em;
            }
            .search-hint:empty { display: none; }
            .summary-actions { display: flex; gap: .35rem; flex: 0 0 auto; flex-wrap: wrap; }
            button.fwl-new-folder, button.fwl-new-recipe {
              appearance: none; border: 1px solid var(--divider-color, #ddd);
              background: transparent; color: var(--primary-color, #03a9f4);
              border-radius: 8px; padding: .25rem .65rem; font: inherit; cursor: pointer;
              white-space: nowrap;
            }
            button.fwl-new-folder:hover, button.fwl-new-recipe:hover {
              border-color: currentColor;
            }
            button.fwl-new-folder:disabled, button.fwl-new-recipe:disabled {
              opacity: .4; cursor: wait;
            }
            .fwl-folder { border-top: 1px solid var(--divider-color, #3333); }
            .fwl-folder:first-of-type { border-top: 0; }
            .fwl-folder-row { display: flex; align-items: center; gap: .35rem; }
            button.fwl-folder-head {
              appearance: none; flex: 1; min-width: 0; display: flex; align-items: center;
              gap: .55rem; padding: .65rem 0; border: 0; background: transparent;
              color: inherit; font: inherit; cursor: pointer; text-align: left;
            }
            button.fwl-folder-head .chev { width: 1rem; opacity: .7; }
            button.fwl-folder-head .name { flex: 1; font-weight: 650; min-width: 0; }
            button.fwl-folder-head .count {
              opacity: .65; font-variant-numeric: tabular-nums;
            }
            .fwl-folder-body { padding: 0 0 .55rem .2rem; }
            button.fwl-add, button.fwl-move, button.fwl-del-folder {
              appearance: none; border: 1px solid var(--divider-color, #ddd);
              background: transparent; color: var(--primary-color, #03a9f4);
              width: 1.75rem; height: 1.75rem; border-radius: 999px;
              font-size: 1.05rem; line-height: 1; cursor: pointer; flex: 0 0 auto;
              display: inline-flex; align-items: center; justify-content: center;
            }
            button.fwl-add { font-size: 1.2rem; }
            button.fwl-del-folder { color: var(--error-color, #db4437); }
            button.fwl-add:hover, button.fwl-move:hover, button.fwl-del-folder:hover {
              border-color: currentColor;
            }
            button.fwl-add:disabled, button.fwl-move:disabled, button.fwl-del-folder:disabled {
              opacity: .4; cursor: wait;
            }
          </style>
          <div class="pad">
            <h2 class="fwl-fav-title" style="margin:0 0 .35rem;font-size:1.1rem;display:none;"></h2>
            <div class="summary-row">
              <div class="summary"></div>
              <div class="summary-actions">
                <button type="button" class="fwl-new-recipe" hidden>+ Rezept</button>
                <button type="button" class="fwl-new-folder">+ Ordner</button>
              </div>
            </div>
            <div class="fwl-search-row">
              <input type="search" class="fwl-fav-search" placeholder="Favoriten suchen…"
                autocomplete="off" spellcheck="false" />
            </div>
            <div class="search-hint"></div>
            <div class="join-status"></div>
            <div class="fwl-fav-body"></div>
          </div>
        </ha-card>`;

        const searchInput = root.querySelector("input.fwl-fav-search");
        searchInput.addEventListener("input", (ev) => {
          this._favQuery = ev.target.value || "";
          this._render();
        });
        searchInput.addEventListener("keydown", (ev) => {
          if (ev.key === "Escape" && (this._favQuery || searchInput.value)) {
            ev.preventDefault();
            this._favQuery = "";
            searchInput.value = "";
            this._render();
          }
        });

        const newRecipeBtn = root.querySelector("button.fwl-new-recipe");
        newRecipeBtn.addEventListener("click", async (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          const ctx = this._favCtx || {};
          const drafted = await promptPrivateRecipe(
            "Privates Chefkoch-Rezept",
            ctx.chefFolders || []
          );
          if (!drafted) return;
          newRecipeBtn.disabled = true;
          try {
            const data = {
              name: drafted.name,
              description: drafted.description || "",
            };
            if (drafted.folderId) data.folder_id = drafted.folderId;
            await this._hass.callService(
              "chefkoch_collections",
              "create_private_recipe",
              data
            );
            this._chefPayloadKey = "";
            await this._loadChefkochFavorites();
            this._render();
          } catch (err) {
            console.error("create private recipe failed", err);
            window.alert("Privates Rezept konnte nicht angelegt werden.");
            newRecipeBtn.disabled = false;
          }
        });

        const newFolderBtn = root.querySelector("button.fwl-new-folder");
        newFolderBtn.addEventListener("click", async (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          const ctx = this._favCtx || {};
          const name = await promptText(
            ctx.joined
              ? `Neuen Ordner anlegen (${(ctx.labels || []).join(" + ")})`
              : "Neuen Ordner anlegen",
            "Ordnername"
          );
          if (!name) return;
          newFolderBtn.disabled = true;
          const results = [];
          try {
            await this._hass.callService("foodwithlove", "create_favorite_folder", {
              name,
            });
            results.push("FWL: ok");
          } catch (err) {
            console.error("create folder failed", err);
            window.alert("FWL-Ordner konnte nicht angelegt werden.");
            newFolderBtn.disabled = false;
            return;
          }
          for (const partner of ctx.partners || []) {
            if (!partnerEntityAvailable(this._hass, partner.entity)) {
              results.push(`${partner.source}: übersprungen (nicht verfügbar)`);
              continue;
            }
            try {
              await this._hass.callService(
                collectionsDomain(partner.source),
                "create_favorite_folder",
                { name }
              );
              results.push(`${partner.source}: ok`);
            } catch (err) {
              console.error("create partner folder failed", partner.source, err);
              results.push(`${partner.source}: fehlgeschlagen`);
            }
          }
          const failed = results.filter((r) => r.includes("fehlgeschlagen"));
          if (failed.length) {
            window.alert(
              "Ordner teilweise angelegt:\n" + results.join("\n")
            );
          }
          newFolderBtn.disabled = false;
        });
      }

      const titleEl = root.querySelector(".fwl-fav-title");
      if (titleEl) {
        if (this._config.title) {
          titleEl.textContent = this._config.title;
          titleEl.style.display = "";
        } else {
          titleEl.textContent = "";
          titleEl.style.display = "none";
        }
      }
      const summaryEl = root.querySelector(".summary");
      if (summaryEl) summaryEl.textContent = summary;
      const recipeBtn = root.querySelector("button.fwl-new-recipe");
      if (recipeBtn) recipeBtn.hidden = !showChefRecipeBtn;
      const searchInput = root.querySelector("input.fwl-fav-search");
      if (searchInput && searchInput !== root.activeElement) {
        // Sync value only when the user is not typing in this field.
        if (searchInput.value !== (this._favQuery || "")) {
          searchInput.value = this._favQuery || "";
        }
      }
      const hintEl = root.querySelector(".search-hint");
      if (hintEl) hintEl.textContent = searchHintText;
      const joinEl = root.querySelector(".join-status");
      if (joinEl) {
        if (chefJoinWarn) {
          joinEl.className = "join-status warn";
          joinEl.textContent = chefJoinWarn;
        } else {
          joinEl.className = "join-status";
          joinEl.textContent = "";
        }
      }
      const bodyEl = root.querySelector(".fwl-fav-body");
      if (bodyEl) bodyEl.innerHTML = body;

      root.querySelectorAll("button.fwl-folder-head").forEach((btn) => {
        btn.addEventListener("click", () => this._toggle(btn.getAttribute("data-id")));
      });
      bindOpens(root, this._hass);

      root.querySelectorAll("button.fwl-del-folder").forEach((btn) => {
        btn.addEventListener("click", async (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          const folderId = btn.getAttribute("data-folder-id") || "";
          const source = btn.getAttribute("data-source") || "fwl";
          if (!folderId) return;
          if (!window.confirm("Leeren Ordner wirklich löschen?")) return;
          btn.disabled = true;
          try {
            await this._hass.callService(
              collectionsDomain(source),
              "delete_favorite_folder",
              { folder_id: folderId }
            );
          } catch (err) {
            console.error("delete folder failed", err);
            window.alert("Ordner konnte nicht gelöscht werden (nur leere Ordner).");
            btn.disabled = false;
          }
        });
      });

      root.querySelectorAll("button.fwl-move").forEach((btn) => {
        btn.addEventListener("click", async (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          const recipeId = btn.getAttribute("data-recipe-id") || "";
          const recipeTitle = btn.getAttribute("data-title") || "Rezept";
          const currentFolder = btn.getAttribute("data-folder-id") || "";
          const source = btn.getAttribute("data-source") || "fwl";
          if (!recipeId) return;
          const ctx = this._favCtx || {};
          const folderChoices =
            source === "cookidoo"
              ? ctx.cookFolders || []
              : source === "chefkoch"
                ? ctx.chefFolders || []
                : ctx.folders || [];
          const chosen = await pickFolder(
            `„${recipeTitle}“ verschieben`,
            folderChoices,
            currentFolder,
            {
              emptyLabel:
                source === "chefkoch" ? "Hauptsammlung" : "Ohne Ordner",
            }
          );
          if (chosen === undefined) return;
          const same =
            chosen === currentFolder ||
            (!chosen &&
              (currentFolder === "" || currentFolder === "__uncategorized__"));
          if (same) return;
          btn.disabled = true;
          try {
            const data = { recipe_id: recipeId };
            if (chosen) data.folder_id = chosen;
            await this._hass.callService(
              collectionsDomain(source),
              "move_favorite",
              data
            );
          } catch (err) {
            console.error("move favorite failed", err);
            window.alert("Konnte nicht verschieben.");
            btn.disabled = false;
          }
        });
      });

      root.querySelectorAll("button.fwl-add").forEach((btn) => {
        btn.addEventListener("click", async (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          const recipeId = btn.getAttribute("data-recipe-id") || "";
          const recipeTitle = btn.getAttribute("data-title") || "Rezept";
          const source = btn.getAttribute("data-source") || "fwl";
          if (source === "chefkoch" && !(this._favCtx || {}).chefCanPlan) {
            window.alert(
              "Chefkoch-Wochenplaner benötigt Chefkoch Plus (meal planner)."
            );
            return;
          }
          const day = await pickDate(`„${recipeTitle}“ planen`);
          if (!day || !recipeId) return;
          btn.disabled = true;
          try {
            await this._hass.callService(
              collectionsDomain(source),
              "add_weekplan_meal",
              { date: day, recipe_id: recipeId }
            );
          } catch (err) {
            console.error("add weekplan meal failed", err);
            window.alert(
              source === "chefkoch"
                ? "Konnte nicht zum Chefkoch-Wochenplan hinzufügen (Plus erforderlich?)."
                : "Konnte nicht zum Wochenplan hinzufügen."
            );
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
          week_mode: this._config.week_mode || "",
          cookidoo_entity: this._config.cookidoo_entity || "",
          chefkoch_entity: this._config.chefkoch_entity || "",
          cookidoo_calendar: this._config.cookidoo_calendar || "",
        });
        this._recipe.setConfig({
          entity:
            this._config.recipe_entity ||
            "sensor.food_with_love_rezept_des_tages",
          cookidoo_entity: this._config.cookidoo_recipe_entity || "",
          chefkoch_entity: this._config.chefkoch_recipe_entity || "",
          greeting_entity:
            this._config.greeting_entity ||
            "sensor.food_with_love_morgengruss",
          title: this._config.recipe_title || "Rezept des Tages",
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
      description:
        "Week overview; optional cookidoo_entity / chefkoch_entity (with images) or cookidoo_calendar",
    },
    {
      type: "fwl-recipe-card",
      name: "food with love recipe",
      description:
        "Compact recipe-of-the-day row (FWL + optional Cookidoo/Chefkoch)",
    },
    {
      type: "fwl-favorites-card",
      name: "food with love favorites",
      description:
        "Favorite folders; optional cookidoo_entity / chefkoch_entity for joined view",
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
