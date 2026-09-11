/**
 * Companion FAB UI injected into the Kavita page via Shadow DOM.
 * Avoids chrome-extension iframe opaque canvas (transparency) and toast resize glitches.
 */
(function () {
  "use strict";

  if (window.__mkCompanionPageUI) return;

  const HOST_ID = "mk-companion-page-host";
  const LOGO_URL = chrome.runtime.getURL("icons/logo.png");
  const BMC_URL = "https://buymeacoffee.com/raukorim";

  // Uniform 18px stroke icons — every FAB is icon-only so the radial layout
  // deals with identical circular footprints (no more mixed pill sizes).
  const ICON = (d) =>
    `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
  const SUPER_ICON = ICON(
    '<path d="M12 3l1.9 4.6L18.5 9l-4.6 1.9L12 15.5l-1.9-4.6L5.5 9l4.6-1.6L12 3z"/><path d="M19 14l.9 2.1L22 17l-2.1.9L19 20l-.9-2.1L16 17l2.1-.9L19 14z"/>'
  );
  const AUTO_ICON = ICON('<path d="M13 3 4 14h6l-1 7 9-11h-6l1-7z"/>');
  const COVER_ICON = ICON(
    '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="9" cy="9.5" r="1.6"/><path d="M21 15.5l-5.5-5-9.5 8.5"/>'
  );
  const CONFIG_ICON = ICON(
    '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.9 2.9l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.9-2.9l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.6-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.9-2.9l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.6V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.9 2.9l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.6 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.6 1z"/>'
  );
  const BMC_ICON = ICON(
    '<path d="M8 7h8a3 3 0 0 1 0 6h-1"/><path d="M7 7v8a3 3 0 0 0 3 3h2a3 3 0 0 0 3-3v-1"/><path d="M8 7V5.5A1.5 1.5 0 0 1 9.5 4h.5"/><path d="M7 21h8"/>'
  );

  const CSS = `
    :host { all: initial; }
    * { box-sizing: border-box; font-family: "Segoe UI", system-ui, sans-serif; }
    .wrap { position: fixed; inset: 0; pointer-events: none; z-index: 2147483646; }
    .fab-stack {
      position: fixed; right: 20px; bottom: 20px;
      width: 56px; height: 56px;
      pointer-events: none; opacity: 0; transform: translateY(10px) scale(0.96);
      transition: opacity .32s ease, transform .32s cubic-bezier(.22,1,.36,1);
    }
    .fab-stack.is-visible { opacity: 1; transform: none; }
    .fab-logo {
      position: relative; z-index: 2;
      pointer-events: auto; width: 56px; height: 56px; padding: 0; border-radius: 50%;
      border: 1px solid rgba(148,163,184,.28); cursor: pointer;
      background: radial-gradient(120% 120% at 50% 20%, rgba(30,41,59,.55), rgba(15,23,42,.45));
      -webkit-backdrop-filter: blur(12px) saturate(1.15);
      backdrop-filter: blur(12px) saturate(1.15);
      box-shadow: 0 10px 30px rgba(2,6,23,.35);
      display: grid; place-items: center;
      transition: transform .25s ease, box-shadow .25s ease, border-color .25s ease;
    }
    .fab-logo img { width: 34px; height: 34px; object-fit: contain; pointer-events: none; }
    .fab-logo:hover { transform: translateY(-1px) scale(1.05); border-color: rgba(56,189,248,.55); }
    .fab-logo[aria-expanded="true"] { border-color: rgba(56,189,248,.6); }
    .fab-actions {
      position: absolute; inset: 0; margin: 0; padding: 0;
      pointer-events: none;
    }
    /* Every action is the same 46px glass disc — uniform footprint is what
       makes the radial layout math (see layoutArc) land evenly every time. */
    .fab {
      -webkit-appearance: none; appearance: none; margin: 0;
      position: absolute; left: 50%; top: 50%; z-index: 1;
      --x: 0px; --y: 0px; --delay: 0s;
      width: 46px; height: 46px; padding: 0;
      display: flex; align-items: center; justify-content: center;
      border-radius: 50%;
      opacity: 0;
      transform: translate(-50%, -50%) scale(.4);
      transition: opacity .2s ease, transform .3s cubic-bezier(.22,1,.36,1),
        box-shadow .2s ease, border-color .2s ease;
      transition-delay: 0s;
      border: 1px solid rgba(148,163,184,.3);
      cursor: pointer; color: #e2e8f0;
      background: radial-gradient(120% 120% at 50% 18%, rgba(30,41,59,.8), rgba(15,23,42,.72));
      -webkit-backdrop-filter: blur(10px) saturate(1.15); backdrop-filter: blur(10px) saturate(1.15);
      box-shadow: 0 8px 20px rgba(2,6,23,.35), inset 0 0 0 1px rgba(255,255,255,.04);
      pointer-events: none;
    }
    .fab svg { width: 19px; height: 19px; display: block; pointer-events: none; }
    .fab-actions:not([hidden]) .fab { pointer-events: auto; }
    .fab-stack.is-open .fab {
      opacity: 1;
      transition-delay: var(--delay);
      transform: translate(-50%, -50%) translate(var(--x), var(--y));
    }
    .fab-stack.is-open .fab:hover {
      transform: translate(-50%, -50%) translate(var(--x), var(--y)) scale(1.1);
      box-shadow: 0 10px 26px rgba(2,6,23,.5), 0 0 0 5px color-mix(in srgb, currentColor 16%, transparent);
      border-color: color-mix(in srgb, currentColor 65%, transparent);
    }
    .fab-stack.is-open .fab:active {
      transform: translate(-50%, -50%) translate(var(--x), var(--y)) scale(.96);
    }
    .fab-super { color: #38bdf8; border-color: rgba(56,189,248,.4); }
    .fab-auto { color: #34d399; border-color: rgba(52,211,153,.4); }
    .fab-cover { color: #fbbf24; border-color: rgba(251,191,36,.4); }
    .fab-config { color: #e2e8f0; border-color: rgba(148,163,184,.4); }
    .fab-bmc { color: #e2c08d; border-color: rgba(226,192,141,.4); }
    .fab:disabled { cursor: wait; }
    .fab-stack.is-open .fab:disabled { opacity: .55; }
    .panel {
      position: fixed; right: 20px; bottom: 88px; width: min(320px, calc(100vw - 32px));
      max-height: min(58vh, 420px); overflow: auto; display: none; pointer-events: auto;
      background: rgba(30,41,59,.92); -webkit-backdrop-filter: blur(14px); backdrop-filter: blur(14px);
      border: 1px solid rgba(148,163,184,.28); border-radius: 16px; padding: 14px;
      box-shadow: 0 18px 48px rgba(2,6,23,.55); color: #e2e8f0;
    }
    .panel.is-open { display: block; }
    .panel h2 { margin: 0 0 12px; font-size: 15px; }
    .field { display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px; }
    .field label { font-size: 11px; color: #94a3b8; font-weight: 600; }
    .field input, .field select {
      width: 100%; padding: 8px 10px; border-radius: 8px;
      border: 1px solid rgba(148,163,184,.35); background: #0f172a; color: #e2e8f0; font: inherit;
    }
    .check { display: flex; gap: 8px; align-items: center; font-size: 12px; margin-bottom: 8px; }
    .row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
    .btn {
      border: 0; border-radius: 8px; padding: 8px 12px; font-weight: 650; cursor: pointer;
      background: #38bdf8; color: #0b1220; font-size: 12px;
    }
    .btn-secondary { background: transparent; color: #e2e8f0; border: 1px solid rgba(148,163,184,.4); }
  `;

  let seriesId = null;
  let settings = null;
  let menuOpen = false;
  let root = null;
  let shadow = null;
  let els = {};
  let mountGen = 0;

  // Servie par le service worker au montage (message `uiBootstrap`). Ce fichier
  // est injecté comme script CLASSIQUE : il ne peut pas importer lib/i18n.js.
  // Il en portait donc une copie des 58 clés, que seul un self-check empêchait
  // de dériver — et qui avait déjà dérivé, faisant afficher trois clés brutes.
  let STRINGS = {};

  /**
   * Reste SYNCHRONE : appelée depuis des gestionnaires d'événements. La table
   * est mise en cache une fois pour toutes au montage.
   *
   * Repli sur `_locales` quand elle n'est pas encore là — c'est exactement le
   * cas où l'aller-retour vient d'échouer (extension rechargée), donc le cas où
   * elle n'arrivera jamais. `chrome.i18n` est synchrone et embarqué.
   */
  function t(key) {
    if (STRINGS[key]) return STRINGS[key];
    try {
      const msg = chrome.i18n.getMessage(key);
      if (msg) return msg;
    } catch {
      /* extension rechargée : il ne reste que la clé */
    }
    return key;
  }

  function uiAlive() {
    return !!(els && els.fabStack && els.btnLogo && els.configPanel);
  }

  function setLabel(el, key) {
    if (!el) return;
    el.title = t(key);
    el.setAttribute("aria-label", t(key));
  }

  function applyLabels() {
    if (!uiAlive() || !els.btnSuper) return;
    setLabel(els.btnSuper, "fabSuper");
    setLabel(els.btnAuto, "fabAuto");
    setLabel(els.btnCover, "fabCover");
    setLabel(els.btnConfig, "fabConfig");
    setLabel(els.btnBmc, "fabBmc");
    els.btnLogo.setAttribute("aria-label", t("fabLogo"));
    els.btnLogo.title = "MetaKavita";
    if (!shadow) return;
    shadow.querySelectorAll("[data-i18n]").forEach((node) => {
      const key = node.getAttribute("data-i18n");
      if (key) node.textContent = t(key);
    });
  }

  function showToast(msg, isError) {
    // Always toast on the Kavita page — never expand an opaque iframe.
    if (typeof window.__mkCompanionShowToast === "function") {
      window.__mkCompanionShowToast(msg, !!isError);
      return;
    }
    let el = document.getElementById("mk-companion-page-toast");
    if (!el) {
      el = document.createElement("div");
      el.id = "mk-companion-page-toast";
      Object.assign(el.style, {
        position: "fixed",
        right: "16px",
        bottom: "88px",
        zIndex: "2147483647",
        maxWidth: "280px",
        padding: "10px 12px",
        borderRadius: "10px",
        background: "#1e293b",
        color: "#e2e8f0",
        border: "1px solid rgba(148,163,184,0.4)",
        font: "600 12px/1.35 Segoe UI, system-ui, sans-serif",
        pointerEvents: "none",
        opacity: "0",
        transition: "opacity 0.2s ease",
      });
      document.documentElement.appendChild(el);
    }
    el.textContent = msg || "";
    el.style.borderColor = isError ? "#f87171" : "rgba(148,163,184,0.4)";
    el.style.opacity = "1";
    clearTimeout(el.__mkTimer);
    el.__mkTimer = setTimeout(() => {
      el.style.opacity = "0";
    }, 3200);
  }

  // All FABs are the same 46px circle, so the arc math is a closed-form
  // formula (chord length between two points on a circle) instead of a
  // fragile per-pair collision loop — every gap comes out identical.
  const FAB_DIAMETER = 46;
  const FAB_GAP = 14;
  // Angular window (math degrees, CCW from east) per count, tuned so the
  // farthest item still sits clearly above the logo instead of levelling
  // out beside it.
  const ARC_RANGES = {
    1: [135, 135],
    2: [118, 158],
    3: [104, 168],
    4: [98, 174],
    5: [93, 178],
  };

  function layoutArc() {
    if (!els.fabActions) return;
    const fabs = Array.from(els.fabActions.querySelectorAll(".fab")).filter(
      (el) => el.style.display !== "none"
    );
    const n = fabs.length;
    if (!n) return;

    const [start, end] = ARC_RANGES[Math.min(n, 5)] || ARC_RANGES[5];
    let radius;
    if (n === 1) {
      radius = 92;
    } else {
      const stepRad = (((end - start) / (n - 1)) * Math.PI) / 180;
      const chordMin = FAB_DIAMETER + FAB_GAP;
      radius = Math.round(chordMin / (2 * Math.sin(stepRad / 2)));
    }

    fabs.forEach((el, i) => {
      const t = n === 1 ? 0.5 : i / (n - 1);
      const rad = ((start + (end - start) * t) * Math.PI) / 180;
      el.style.setProperty("--x", `${Math.round(Math.cos(rad) * radius)}px`);
      el.style.setProperty("--y", `${Math.round(-Math.sin(rad) * radius)}px`);
      el.style.setProperty("--delay", `${(n - 1 - i) * 0.03}s`);
    });
  }

  function setMenuOpen(open) {
    if (!uiAlive() || !els.fabActions) return;
    menuOpen = !!open;
    els.btnLogo.setAttribute("aria-expanded", menuOpen ? "true" : "false");
    if (menuOpen) {
      els.fabActions.hidden = false;
      layoutArc();
      const gen = mountGen;
      requestAnimationFrame(() => {
        if (gen !== mountGen || !els.fabStack) return;
        layoutArc();
        els.fabStack.classList.add("is-open");
      });
    } else {
      els.fabStack.classList.remove("is-open");
      const gen = mountGen;
      setTimeout(() => {
        if (gen !== mountGen || menuOpen || !els.fabActions) return;
        els.fabActions.hidden = true;
      }, 320);
    }
  }

  function openConfig() {
    if (!uiAlive()) return;
    setMenuOpen(false);
    fillForm({ includeToken: true });
    els.configPanel.classList.add("is-open");
  }

  function closeConfig() {
    if (!els.configPanel) return;
    els.configPanel.classList.remove("is-open");
    if (els.token) els.token.value = "";
  }

  /**
   * The webhook token only lands in the DOM while the panel is open. It grants
   * embed tokens for any series, and this UI lives inside the Kavita page: the
   * isolated world keeps our variables out of reach, not the nodes we insert.
   */
  function fillForm(opts) {
    if (!els.metaUrl || !els.token || !els.showFabs || !els.cacheBust || !els.uiLang) return;
    els.metaUrl.value = (settings && settings.metaBaseUrl) || "";
    if (opts && opts.includeToken) {
      els.token.value = (settings && settings.webhookToken) || "";
    }
    els.showFabs.checked = !settings || settings.showActionFabs !== false;
    els.cacheBust.checked = !settings || settings.cacheBustOnConfirm !== false;
    els.uiLang.value = (settings && settings.uiLang) || "auto";
  }

  function refreshFabVisibility() {
    if (!els.btnSuper || !els.btnAuto || !els.btnCover) return;
    const show = !settings || settings.showActionFabs !== false;
    els.btnSuper.style.display = show ? "" : "none";
    els.btnAuto.style.display = show ? "" : "none";
    els.btnCover.style.display = show ? "" : "none";
    if (menuOpen) layoutArc();
  }

  async function reloadSettings() {
    // Un seul aller-retour : réglages, langue résolue et table de traductions.
    const res = await chrome.runtime.sendMessage({ type: "uiBootstrap" });
    settings = (res && res.settings) || {};
    if (res && res.strings) STRINGS = res.strings;
    applyLabels();
    fillForm({
      includeToken: !!(els.configPanel && els.configPanel.classList.contains("is-open")),
    });
    refreshFabVisibility();
  }

  /**
   * Origine d'une URL DÉJÀ normalisée (celle des réglages). Ce n'est pas un
   * doublon de `lib/storage.js::originFromUrl`, qui normalise d'abord — ici il
   * n'y a rien à normaliser, et rien à attendre.
   */
  function originOf(url) {
    try {
      return new URL(url).origin;
    } catch {
      return "";
    }
  }

  /**
   * Normalisation d'une URL SAISIE, faite par le service worker.
   *
   * Ce fichier portait une copie de `normalizeBaseUrl`, `tokenFromPastedUrl`,
   * `originFromUrl` et `isMetaKavitaUrl` — quatre fonctions qu'aucun test ne
   * comparait à leur original, contrairement à la table de traductions. Tous
   * les appelants sont des gestionnaires `async` : l'aller-retour est gratuit.
   */
  async function urlInfo(url, extra) {
    try {
      const res = await chrome.runtime.sendMessage({ type: "urlInfo", url, ...(extra || {}) });
      if (res && res.ok) return res;
    } catch {
      /* extension rechargée */
    }
    return { base: "", origin: "", token: "", isMeta: false };
  }

  // chrome.permissions is NOT available in content scripts — always go via SW.
  async function hasHostPermission(origin) {
    if (!origin) return false;
    try {
      const res = await chrome.runtime.sendMessage({ type: "hasHostPermission", origin });
      return !!(res && res.granted);
    } catch {
      return false;
    }
  }

  async function requestHostPermission(origin) {
    if (!origin) return false;
    if (await hasHostPermission(origin)) return true;
    try {
      const res = await chrome.runtime.sendMessage({ type: "requestHostPermission", origin });
      return !!(res && res.granted);
    } catch {
      return false;
    }
  }

  async function runWebhook(payload) {
    if (!seriesId) {
      showToast(t("toastNeedSeriesPage"), true);
      return false;
    }
    try {
      const res = await chrome.runtime.sendMessage({
        type: "webhook",
        payload: { ...payload, seriesId: Number(seriesId) },
      });
      if (!res || !res.ok) {
        const err = (res && res.error) || "error";
        const code = res && res.code;
        if (err === "not_configured") {
          showToast(t("toastNeedConfig"), true);
          openConfig();
          return false;
        }
        if (code === "kavita_unreachable" || code === "kavita_auth") {
          showToast(t("toastKavitaUnreachable"), true);
          return false;
        }
        if (code === "series_not_found") {
          showToast(t("toastSeriesNotFound"), true);
          return false;
        }
        showToast(t("toastError").replace("$1$", err), true);
        return false;
      }
      return true;
    } catch {
      showToast(t("toastExtensionReloaded"), true);
      return false;
    }
  }

  /**
   * An HTTP MetaKavita iframe cannot live in an HTTPS Kavita page — no extension
   * trick gets around it (the mixed-content check looks at the top frame, so an
   * extension-hosted iframe is blocked too). A script-opened popup window is the
   * closest thing to a modal: chromeless, centered over Kavita, and still an
   * opener-linked window, which is what lets Super Review close itself.
   */
  function openReviewWindow() {
    const screenW = (window.screen && window.screen.availWidth) || 1440;
    const screenH = (window.screen && window.screen.availHeight) || 900;
    const w = Math.max(720, Math.min(1180, Math.round(screenW * 0.68)));
    const h = Math.max(620, Math.min(1000, Math.round(screenH * 0.88)));
    const hostW = window.outerWidth || screenW;
    const hostH = window.outerHeight || screenH;
    const left = Math.max(0, Math.round((window.screenX || 0) + (hostW - w) / 2));
    const top = Math.max(0, Math.round((window.screenY || 0) + (hostH - h) / 2));
    let win = null;
    try {
      win = window.open(
        "",
        "mkCompanionSuperReview",
        `popup=1,width=${w},height=${h},left=${left},top=${top}`
      );
    } catch {
      return null;
    }
    if (!win) return null;
    try {
      // about:blank inherits this origin, so the placeholder avoids a white flash
      // while the embed page loads.
      win.document.write(
        '<!doctype html><meta charset="utf-8"><title>MetaKavita — Super Review</title>' +
          '<body style="margin:0;height:100vh;display:flex;align-items:center;' +
          'justify-content:center;background:#0f172a;color:#94a3b8;' +
          'font:600 13px/1.4 Segoe UI,system-ui,sans-serif">Super Review…</body>'
      );
      win.document.close();
    } catch {
      /* placeholder is cosmetic */
    }
    return win;
  }

  async function openMr() {
    if (!settings || !settings.metaBaseUrl) {
      showToast(t("toastNeedConfig"), true);
      openConfig();
      return;
    }
    if (!seriesId) {
      showToast(t("toastNeedSeriesPage"), true);
      return;
    }
    closeConfig();
    setMenuOpen(false);
    // `settings.metaBaseUrl` est DÉJÀ normalisée : lib/storage.js::saveSettings
    // la normalise à l'écriture. Rien à recalculer, et surtout rien à attendre —
    // la décision « contenu mixte » doit précéder le window.open tant que le
    // clic compte encore comme une activation utilisateur, sinon le bloqueur de
    // popups tue la fenêtre.
    const base = String((settings && settings.metaBaseUrl) || "");
    const needsWindow = location.protocol === "https:" && /^http:/i.test(base);
    let reviewWin = null;
    if (needsWindow) {
      showToast(t("toastMixedContentWindow"));
      reviewWin = openReviewWindow();
    }
    const parentOrigin = chrome.runtime.getURL("").replace(/\/$/, "");
    let embedToken = "";
    try {
      const tokRes = await chrome.runtime.sendMessage({
        type: "embedToken",
        seriesId: Number(seriesId),
        parentOrigin,
      });
      if (tokRes && tokRes.ok && tokRes.embed_token) embedToken = tokRes.embed_token;
    } catch {
      /* ignore */
    }
    const url = new URL(base + "/companion/embed");
    url.searchParams.set("series_id", String(seriesId));
    url.searchParams.set("parent_origin", parentOrigin);
    url.searchParams.set("top_origin", location.origin);
    if (embedToken) url.searchParams.set("embed_token", embedToken);
    const finalUrl = url.toString();
    if (needsWindow) {
      // Keep opener so Super Review can focus Kavita and window.close() itself
      // when the review finishes (noopener would block both).
      if (reviewWin && !reviewWin.closed) {
        try {
          reviewWin.location.replace(finalUrl);
          reviewWin.focus();
        } catch {
          window.open(finalUrl, "_blank");
        }
      } else {
        showToast(t("toastMixedContentTab"));
        window.open(finalUrl, "_blank");
      }
      return;
    }
    if (typeof window.__mkCompanionOpenMr === "function") {
      window.__mkCompanionOpenMr({
        url: finalUrl,
        metaOrigin: originOf(base),
        seriesId: Number(seriesId),
        cacheBust: !(settings && settings.cacheBustOnConfirm === false),
        labels: {
          blocked: t("mrEmbedBlocked"),
          openTab: t("mrOpenInTab"),
          close: t("close"),
          timeout: t("toastMrTimeout"),
          login: t("toastNeedMetaLogin"),
        },
      });
    }
  }

  function seriesNameGuess() {
    const h1 = document.querySelector("h1, .series-name, app-series-detail h4");
    if (h1 && h1.textContent) return h1.textContent.trim();
    const title = (document.title || "").split("|")[0].trim();
    return title || ("#" + seriesId);
  }

  async function openCover() {
    if (!settings || !settings.metaBaseUrl) {
      showToast(t("toastNeedConfig"), true);
      openConfig();
      return;
    }
    if (!seriesId) {
      showToast(t("toastNeedSeriesPage"), true);
      return;
    }
    closeConfig();
    setMenuOpen(false);
    if (typeof window.__mkCompanionOpenCover === "function") {
      window.__mkCompanionOpenCover({
        seriesId: Number(seriesId),
        seriesName: seriesNameGuess(),
        labels: {
          title: t("coverTitle"),
          search: t("coverSearch"),
          searching: t("coverSearching"),
          empty: t("coverEmpty"),
          close: t("close"),
          applied: t("coverApplied"),
          fail: t("coverApplyFail"),
          previewFail: t("coverPreviewFail"),
          previewLogin: t("coverPreviewLogin"),
        },
      });
    }
  }

  function buildDom() {
    root = document.createElement("div");
    root.id = HOST_ID;
    // Closed: an open shadow root is reachable from the page through
    // host.shadowRoot, which would hand the settings panel — token field
    // included — to any script running on Kavita.
    shadow = root.attachShadow({ mode: "closed" });
    const style = document.createElement("style");
    style.textContent = CSS;
    shadow.appendChild(style);

    const wrap = document.createElement("div");
    wrap.className = "wrap";
    wrap.innerHTML = `
      <div class="fab-stack" id="fabStack">
        <div class="fab-actions" id="fabActions" hidden>
          <button type="button" class="fab fab-super" id="btnSuper">${SUPER_ICON}</button>
          <button type="button" class="fab fab-auto" id="btnAuto">${AUTO_ICON}</button>
          <button type="button" class="fab fab-cover" id="btnCover">${COVER_ICON}</button>
          <button type="button" class="fab fab-config" id="btnConfig">${CONFIG_ICON}</button>
          <button type="button" class="fab fab-bmc" id="btnBmc">${BMC_ICON}</button>
        </div>
        <button type="button" class="fab-logo" id="btnLogo" aria-expanded="false" aria-controls="fabActions">
          <img src="${LOGO_URL}" width="34" height="34" alt="MetaKavita" draggable="false">
        </button>
      </div>
      <div class="panel" id="configPanel" role="dialog">
        <h2 data-i18n="configTitle"></h2>
        <div class="field">
          <label for="metaUrl" data-i18n="configMetaUrl"></label>
          <input type="text" id="metaUrl" autocomplete="off" spellcheck="false" placeholder="http://192.168.x.x:5011">
        </div>
        <div class="field">
          <label for="token" data-i18n="configToken"></label>
          <input type="password" id="token" autocomplete="off" spellcheck="false">
        </div>
        <label class="check"><input type="checkbox" id="showFabs" checked> <span data-i18n="configShowFabs"></span></label>
        <label class="check"><input type="checkbox" id="cacheBust" checked> <span data-i18n="configCacheBust"></span></label>
        <div class="field">
          <label for="uiLang" data-i18n="configLang"></label>
          <select id="uiLang">
            <option value="auto" data-i18n="configLangAuto"></option>
            <option value="fr" data-i18n="configLangFr"></option>
            <option value="en" data-i18n="configLangEn"></option>
          </select>
        </div>
        <div class="row">
          <button type="button" class="btn" id="btnSave" data-i18n="configSave"></button>
          <button type="button" class="btn btn-secondary" id="btnTest" data-i18n="configTest"></button>
          <button type="button" class="btn btn-secondary" id="btnEnableSite" data-i18n="configEnableSite"></button>
          <button type="button" class="btn btn-secondary" id="btnCloseConfig" data-i18n="close"></button>
        </div>
      </div>
    `;
    shadow.appendChild(wrap);

    els = {
      fabStack: shadow.getElementById("fabStack"),
      fabActions: shadow.getElementById("fabActions"),
      btnLogo: shadow.getElementById("btnLogo"),
      btnSuper: shadow.getElementById("btnSuper"),
      btnAuto: shadow.getElementById("btnAuto"),
      btnCover: shadow.getElementById("btnCover"),
      btnConfig: shadow.getElementById("btnConfig"),
      btnBmc: shadow.getElementById("btnBmc"),
      configPanel: shadow.getElementById("configPanel"),
      metaUrl: shadow.getElementById("metaUrl"),
      token: shadow.getElementById("token"),
      showFabs: shadow.getElementById("showFabs"),
      cacheBust: shadow.getElementById("cacheBust"),
      uiLang: shadow.getElementById("uiLang"),
      btnSave: shadow.getElementById("btnSave"),
      btnTest: shadow.getElementById("btnTest"),
      btnEnableSite: shadow.getElementById("btnEnableSite"),
      btnCloseConfig: shadow.getElementById("btnCloseConfig"),
    };

    els.btnLogo.addEventListener("click", () => {
      if (!uiAlive()) return;
      if (els.configPanel.classList.contains("is-open")) {
        closeConfig();
        return;
      }
      setMenuOpen(!menuOpen);
    });
    els.btnConfig.addEventListener("click", () => {
      if (!uiAlive()) return;
      setMenuOpen(false);
      if (els.configPanel.classList.contains("is-open")) closeConfig();
      else openConfig();
    });
    els.btnBmc.addEventListener("click", () => {
      window.open(BMC_URL, "_blank", "noopener,noreferrer");
    });
    els.btnCloseConfig.addEventListener("click", closeConfig);
    els.btnSuper.addEventListener("click", async () => {
      els.btnSuper.disabled = true;
      try {
        const ok = await runWebhook({ force: true, super_review: true });
        if (ok) await openMr();
      } finally {
        els.btnSuper.disabled = false;
      }
    });
    els.btnAuto.addEventListener("click", async () => {
      els.btnAuto.disabled = true;
      try {
        const ok = await runWebhook({ force: true, auto: true });
        if (ok) {
          setMenuOpen(false);
          showToast(t("toastQueued"));
        }
      } finally {
        els.btnAuto.disabled = false;
      }
    });
    els.btnCover.addEventListener("click", async () => {
      els.btnCover.disabled = true;
      try {
        await openCover();
      } finally {
        els.btnCover.disabled = false;
      }
    });

    els.btnSave.addEventListener("click", async () => {
      const typed = await urlInfo(els.metaUrl.value);
      const partial = {
        metaBaseUrl: els.metaUrl.value,
        webhookToken: (els.token.value || typed.token).trim(),
        showActionFabs: els.showFabs.checked,
        cacheBustOnConfirm: els.cacheBust.checked,
        uiLang: els.uiLang.value,
      };
      if (partial.webhookToken && !els.token.value) els.token.value = partial.webhookToken;
      const metaOrigin = typed.origin;
      const res = await chrome.runtime.sendMessage({ type: "saveSettings", settings: partial });
      if (!res || !res.ok) {
        showToast(t("toastTestFail"), true);
        return;
      }
      settings = res.settings;
      // La langue a pu changer : redemander la table plutôt que la déduire.
      await reloadSettings();
      applyLabels();
      refreshFabVisibility();
      showToast(t("toastSaved"));
      if (metaOrigin && res.permissionOk === false) {
        const granted = await requestHostPermission(metaOrigin);
        showToast(
          granted ? t("toastSaved") : t("toastUsePopupForPermission"),
          !granted
        );
      }
    });

    els.btnTest.addEventListener("click", async () => {
      const typedToken = (els.token.value || "").trim();
      const typed = await urlInfo(els.metaUrl.value);
      const webhookToken =
        typedToken || typed.token || ((settings && settings.webhookToken) || "").trim();
      if (!els.token.value && webhookToken) els.token.value = webhookToken;
      const trial = { metaBaseUrl: els.metaUrl.value, webhookToken };
      if (!typed.base) {
        showToast(t("toastTestFailNoUrl"), true);
        return;
      }
      if (!webhookToken) {
        showToast(t("toastTestFailNoToken"), true);
        return;
      }
      await chrome.runtime.sendMessage({ type: "saveSettings", settings: trial });
      const metaOrigin = typed.origin;
      if (metaOrigin && !(await hasHostPermission(metaOrigin))) {
        const granted = await requestHostPermission(metaOrigin);
        if (!granted) {
          showToast(t("toastUsePopupForPermission"), true);
          return;
        }
      }
      const res = await chrome.runtime.sendMessage({ type: "testConnection", settings: trial });
      const result = res && res.result;
      const reason = result && result.reason;
      if (result && result.ok) showToast(t("toastTestOk"));
      else if (reason === "permission") showToast(t("toastUsePopupForPermission"), true);
      else if (reason === "no_url") showToast(t("toastTestFailNoUrl"), true);
      else if (reason === "no_token" || reason === "config") showToast(t("toastTestFailNoToken"), true);
      else if (reason === "token") showToast(t("toastTestFailToken"), true);
      else if (reason === "healthz") showToast(t("toastTestFailHealth"), true);
      else if (reason === "network") showToast(t("toastTestFailNetwork"), true);
      else if (reason === "unexpected") {
        showToast(t("toastTestFailUnexpected").replace("$1$", String(result.status || "?")), true);
      } else showToast(t("toastTestFail"), true);
    });

    els.btnEnableSite.addEventListener("click", async () => {
      const origin = location.origin;
      const here = await urlInfo(location.href, { pageUrl: location.href });
      if (here.isMeta) {
        showToast(t("toastMetaIsNotKavita"), true);
        return;
      }
      // Already injected here ⇒ site is usable; persist it without chrome.permissions
      // (unavailable in content scripts — was causing a false "Permission denied").
      const already = (settings.kavitaOrigins || []).map((o) => String(o).replace(/\/+$/, ""));
      const clean = String(origin).replace(/\/+$/, "");
      if (already.includes(clean)) {
        showToast(t("toastSiteAlreadyEnabled"));
        return;
      }
      const res = await chrome.runtime.sendMessage({
        type: "enableKavitaOrigin",
        origin,
        pageUrl: location.href,
      });
      if (res && res.ok) {
        settings = (await chrome.runtime.sendMessage({ type: "getSettings" })).settings || settings;
        showToast(t("toastSiteEnabled"));
      } else {
        showToast(t("toastEnableFail"), true);
      }
    });

    document.addEventListener(
      "keydown",
      (ev) => {
        if (ev.key !== "Escape") return;
        if (!uiAlive()) return;
        if (els.configPanel.classList.contains("is-open")) {
          closeConfig();
          return;
        }
        if (menuOpen) setMenuOpen(false);
      },
      true
    );
  }

  async function mount(sid) {
    seriesId = sid;
    const gen = ++mountGen;
    if (!root) {
      buildDom();
      document.documentElement.appendChild(root);
    }
    try {
      await reloadSettings();
    } catch {
      if (gen === mountGen) showToast(t("toastExtensionReloaded"), true);
      return;
    }
    if (gen !== mountGen || !uiAlive()) return;
    requestAnimationFrame(() => {
      if (gen !== mountGen || !els.fabStack) return;
      els.fabStack.classList.add("is-visible");
    });
    if (!settings || !settings.metaBaseUrl || !settings.webhookToken) openConfig();
  }

  function unmount() {
    mountGen += 1;
    if (root) root.remove();
    root = null;
    shadow = null;
    els = {};
    seriesId = null;
    menuOpen = false;
  }

  function setSeriesId(sid) {
    seriesId = sid;
  }

  window.__mkCompanionPageUI = { mount, unmount, setSeriesId };
})();
