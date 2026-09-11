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
  // Décliné de `#mk-ico-workshop` (templates/partials/_icons_sprite.html),
  // simplifié pour tenir en trait de 19 px.
  const WORKSHOP_ICON = ICON(
    '<path d="M4 19.5v-11A2.5 2.5 0 0 1 6.5 6H10a2 2 0 0 1 2 2v11.5"/><path d="M20 19.5v-11A2.5 2.5 0 0 0 17.5 6H14a2 2 0 0 0-2 2"/><path d="M15.5 3.5l4 4-7 7H9.5v-3l6-8z"/>'
  );
  const META_ICON = ICON(
    '<path d="M14 4h6v6"/><path d="M20 4l-8.5 8.5"/><path d="M18 13.5V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5.5"/>'
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
    /* Pastille d'état : la seule information que le menu donne sans être ouvert. */
    .fab-logo::after {
      content: ""; position: absolute; right: 3px; bottom: 3px;
      width: 13px; height: 13px; border-radius: 50%;
      border: 2px solid rgba(15,23,42,.92);
      background: transparent; opacity: 0;
      transition: opacity .25s ease, background-color .25s ease;
    }
    .fab-logo[data-state]::after { opacity: 1; }
    .fab-logo[data-state="done"]::after { background: #34d399; }
    .fab-logo[data-state="working"]::after { background: #fbbf24; }
    .fab-logo[data-state="pending"]::after { background: #38bdf8; }
    .fab-logo[data-state="ignored"]::after { background: #f87171; }
    .fab-logo[data-state="unknown"]::after { background: #64748b; }
    .fab-actions {
      position: absolute; inset: 0; margin: 0; padding: 0;
      pointer-events: none;
    }
    /* Les disques d'une même couronne ont un diamètre identique : c'est ce qui
       permet la formule fermée de layoutConstellation (corde entre deux points
       d'un cercle) au lieu d'une boucle de collision. */
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
    .fab-workshop { color: #2dd4bf; border-color: rgba(45,212,191,.4); }
    .fab-meta { color: #a5b4fc; border-color: rgba(165,180,252,.4); }
    .fab-bmc { color: #e2c08d; border-color: rgba(226,192,141,.4); }
    /* Couronne extérieure : plus petite et plus sourde. La hiérarchie se lit
       avant même d'avoir survolé quoi que ce soit. */
    .fab--outer { width: 38px; height: 38px; opacity: 0; }
    .fab--outer svg { width: 16px; height: 16px; }
    .fab-stack.is-open .fab--outer { opacity: .86; }
    .fab-stack.is-open .fab--outer:hover { opacity: 1; }
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

    /* --- CALQUES D'OVERLAY (Super Review, cover picker) ------------------
       Frères de .wrap, jamais dedans : .fab-stack porte un transform, et un
       ancêtre transformé change le référentiel d'un position:fixed. Chacun
       redéclare pointer-events, que .wrap met à none. */
    .mk-layer {
      position: fixed; inset: 0; z-index: 2147483647; pointer-events: auto;
      background: rgba(2, 6, 23, .72);
      -webkit-backdrop-filter: blur(2px); backdrop-filter: blur(2px);
      color: #e2e8f0;
    }
    .mk-layer--cover { display: flex; align-items: center; justify-content: center; padding: 24px; }

    .mk-mr-frame {
      position: absolute; top: 3%; left: 3%; width: 94%; height: 94%;
      border: 0; border-radius: 12px; background: #0f1419;
      box-shadow: 0 24px 64px rgba(0, 0, 0, .55);
    }
    .mk-mr-close {
      position: absolute; top: calc(3% - 6px); right: 3.2%; transform: translateY(-100%);
      z-index: 1; padding: 6px 14px; border-radius: 8px;
      border: 1px solid rgba(148,163,184,.5); background: rgba(15,23,42,.9);
      color: #e2e8f0; font: 600 12px/1 "Segoe UI", system-ui, sans-serif; cursor: pointer;
    }
    .mk-mr-fallback {
      position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
      max-width: 26rem; padding: 24px; text-align: center; border-radius: 12px;
      background: #1e293b; box-shadow: 0 24px 64px rgba(0,0,0,.55);
      font: 500 13px/1.5 "Segoe UI", system-ui, sans-serif;
    }
    .mk-mr-fallback p { margin: 0 0 14px; color: #94a3b8; }
    .mk-mr-open-tab {
      padding: 8px 14px; border: 0; border-radius: 8px;
      background: #38bdf8; color: #0b1220; font-weight: 650; cursor: pointer;
    }

    .mk-confirm {
      position: absolute; right: 20px; bottom: 88px; width: min(320px, calc(100vw - 32px));
      padding: 16px; border-radius: 14px; background: #1e293b; color: #e2e8f0;
      border: 1px solid rgba(148,163,184,.28); box-shadow: 0 18px 48px rgba(2,6,23,.55);
      font: 500 13px/1.45 "Segoe UI", system-ui, sans-serif;
    }
    .mk-confirm p { margin: 0 0 14px; color: #cbd5e1; }
    .mk-confirm .mk-row { display: flex; flex-wrap: wrap; gap: 8px; }
    .mk-confirm .mk-btn--warn { background: #fbbf24; }

    .mk-cover-panel {
      width: min(920px, 100%); max-height: min(86vh, 820px); overflow: hidden;
      display: flex; flex-direction: column; border-radius: 14px;
      background: #1e293b; box-shadow: 0 24px 64px rgba(0,0,0,.55);
      border: 1px solid rgba(148,163,184,.28);
    }
    .mk-cover-head {
      display: flex; align-items: center; gap: 10px; padding: 14px 16px;
      border-bottom: 1px solid rgba(148,163,184,.2);
    }
    .mk-cover-title { flex: 1; font: 650 15px/1.2 "Segoe UI", system-ui, sans-serif; }
    .mk-cover-search {
      flex: 1.4; padding: 8px 10px; border-radius: 8px;
      border: 1px solid rgba(148,163,184,.35); background: #0f172a; color: #e2e8f0;
      font: 500 13px "Segoe UI", system-ui, sans-serif;
    }
    .mk-btn {
      padding: 8px 12px; border: 0; border-radius: 8px; background: #38bdf8;
      color: #0b1220; font: 650 12px "Segoe UI", system-ui, sans-serif; cursor: pointer;
    }
    .mk-btn:disabled { cursor: wait; opacity: .6; }
    .mk-btn--ghost {
      background: transparent; color: #e2e8f0; border: 1px solid rgba(148,163,184,.4);
    }
    .mk-cover-status {
      padding: 8px 16px; font: 500 12px "Segoe UI", system-ui, sans-serif; color: #94a3b8;
      min-height: 30px;
    }
    .mk-cover-grid {
      padding: 12px 16px 18px; overflow: auto; display: grid;
      grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 12px; min-height: 200px;
    }
    .mk-cover-card {
      border: 1px solid rgba(148,163,184,.25); border-radius: 10px; padding: 6px;
      background: #0f172a; color: #e2e8f0; text-align: left; cursor: pointer;
      transition: border-color .15s ease, transform .15s ease;
    }
    .mk-cover-card:hover { border-color: rgba(56,189,248,.55); transform: translateY(-2px); }
    .mk-cover-card:disabled { cursor: wait; opacity: .6; }
    .mk-cover-card img {
      width: 100%; aspect-ratio: 2 / 3; object-fit: cover; border-radius: 6px;
      display: block; background: #020617;
    }
    .mk-cover-cap {
      margin-top: 6px; font: 600 11px/1.3 "Segoe UI", system-ui, sans-serif;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
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
  let uiMode = "simple";

  /**
   * Ce que le serveur dit de cette série. Vide tant qu'il n'a pas répondu — et
   * sur une instance antérieure à la route, il ne répondra jamais : la pastille
   * se tait alors, et rien d'autre ne change.
   */
  let seriesState = null;

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
    // Le mode simplifié dit ce que le bouton FAIT ; le mode expert emploie les
    // noms produit, ceux de l'interface MetaKavita et de la documentation.
    const expert = uiMode === "expert";
    setLabel(els.btnSuper, expert ? "fabSuper" : "fabCompleteSeries");
    setLabel(els.btnAuto, expert ? "fabAuto" : "fabCompleteAuto");
    setLabel(els.btnCover, expert ? "fabCover" : "fabChangeCover");
    setLabel(els.btnWorkshop, "fabWorkshop");
    setLabel(els.btnMeta, "fabOpenMeta");
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

  /** Le toast appartient à `content/base.js` — chargé avant ce fichier. */
  function showToast(msg, isError) {
    if (typeof window.__mkCompanionShowToast === "function") {
      window.__mkCompanionShowToast(msg, !!isError);
    }
  }

  // Les disques d'une même couronne ont un diamètre identique, ce qui permet
  // une formule fermée (la corde entre deux points d'un cercle) au lieu d'une
  // boucle de collision : tous les écarts sortent égaux.
  const FAB_DIAMETER = 46;
  const FAB_DIAMETER_OUTER = 38;
  const FAB_GAP = 14;
  const RING_GAP = 16;
  // Fenêtre angulaire (degrés mathématiques, sens trigonométrique depuis l'est)
  // selon le nombre d'items, réglée pour que le plus éloigné reste franchement
  // au-dessus du logo au lieu de s'aligner à côté.
  const ARC_RANGES = {
    1: [135, 135],
    2: [118, 158],
    3: [104, 168],
    4: [98, 174],
    5: [93, 178],
  };
  // En deçà, la constellation déborderait : elle s'étend jusqu'à ~214 px du
  // centre du logo, lui-même à 48 px du coin. On bascule alors en colonne.
  const CONSTELLATION_MIN_VIEWPORT = 300;

  function ringRadius(count, start, end, diameter) {
    if (count <= 1) return 92;
    const stepRad = (((end - start) / (count - 1)) * Math.PI) / 180;
    return Math.round((diameter + FAB_GAP) / (2 * Math.sin(stepRad / 2)));
  }

  /**
   * Dispose les boutons en constellation : une couronne intérieure d'actions
   * (46 px) et une couronne extérieure de raccourcis (38 px), en quinconce.
   *
   * Les couronnes VIDES sont écartées avant l'attribution des rayons — c'est
   * ce qui fait que décocher « Afficher les boutons » laisse simplement la
   * couronne extérieure prendre la place de l'intérieure, sans cas particulier.
   *
   * Sur un petit viewport, bascule en colonne : même DOM, mêmes boutons.
   */
  function layoutConstellation() {
    if (!els.fabActions) return;
    const visible = (el) => el && el.style.display !== "none";
    const rings = [
      { items: (els.ringInner || []).filter(visible), diameter: FAB_DIAMETER },
      { items: (els.ringOuter || []).filter(visible), diameter: FAB_DIAMETER_OUTER },
    ].filter((ring) => ring.items.length);
    if (!rings.length) return;

    const total = rings.reduce((n, ring) => n + ring.items.length, 0);
    const tooSmall =
      Math.min(window.innerWidth || 0, window.innerHeight || 0) < CONSTELLATION_MIN_VIEWPORT;

    if (tooSmall) {
      let index = 0;
      for (const ring of rings) {
        for (const el of ring.items) {
          el.style.setProperty("--x", "0px");
          el.style.setProperty("--y", `${-(index + 1) * 56}px`);
          el.style.setProperty("--delay", `${(total - 1 - index) * 0.03}s`);
          index += 1;
        }
      }
      return;
    }

    // La fenêtre angulaire est celle de la couronne intérieure : les deux
    // couronnes la partagent, c'est ce qui rend le quinconce lisible.
    const [start, end] = ARC_RANGES[Math.min(rings[0].items.length, 5)] || ARC_RANGES[5];
    let radius = 0;
    let previousDiameter = 0;

    rings.forEach((ring, ringIndex) => {
      const count = ring.items.length;
      const own = ringRadius(count, start, end, ring.diameter);
      radius = ringIndex === 0
        ? own
        : Math.max(own, radius + previousDiameter / 2 + ring.diameter / 2 + RING_GAP);
      previousDiameter = ring.diameter;

      ring.items.forEach((el, i) => {
        // Intérieure : i/(n-1), des deux extrémités de la fenêtre.
        // Extérieure : (i+0.5)/n, donc décalée d'un demi-pas — le quinconce.
        const ratio = ringIndex === 0
          ? (count === 1 ? 0.5 : i / (count - 1))
          : (i + 0.5) / count;
        const rad = ((start + (end - start) * ratio) * Math.PI) / 180;
        el.style.setProperty("--x", `${Math.round(Math.cos(rad) * radius)}px`);
        el.style.setProperty("--y", `${Math.round(-Math.sin(rad) * radius)}px`);
        // La couronne intérieure éclot la première, l'extérieure suit.
        const delay = ringIndex === 0 ? (count - 1 - i) * 0.03 : 0.12 + i * 0.03;
        el.style.setProperty("--delay", `${delay.toFixed(2)}s`);
      });
    });
  }

  function setMenuOpen(open) {
    if (!uiAlive() || !els.fabActions) return;
    menuOpen = !!open;
    els.btnLogo.setAttribute("aria-expanded", menuOpen ? "true" : "false");
    if (menuOpen) {
      els.fabActions.hidden = false;
      layoutConstellation();
      const gen = mountGen;
      requestAnimationFrame(() => {
        if (gen !== mountGen || !els.fabStack) return;
        layoutConstellation();
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
    // Le champ montre le mode EFFECTIF, y compris quand il est déduit : laisser
    // le sélecteur vide sur une valeur non choisie ne dirait rien à personne.
    els.uiMode.value = uiMode;
  }

  /** Boutons qui ÉCRIVENT ou ouvrent un chantier — ce que « masquer » masque. */
  const ACTION_BUTTONS = ["btnSuper", "btnAuto", "btnCover", "btnWorkshop"];

  /**
   * Quels boutons existent, et dans quelle couronne. **Seul endroit qui décide.**
   *
   * Trois choses filtrent la même chose — le mode d'interface, la case
   * « masquer les boutons », et demain l'état du serveur (pas d'Atelier si
   * l'enrichissement des tomes est coupé). Les laisser décider chacun de son
   * côté recréerait exactement le désordre qu'on vient de retirer.
   *
   * En mode simplifié, `Auto` descend sur la couronne extérieure : c'est le
   * geste qui écrit SANS montrer, et il demande confirmation. « Fais-le sans me
   * demander » n'a de sens qu'une fois qu'on fait confiance à l'outil.
   */
  function composeRings() {
    const expert = uiMode === "expert";
    const showActions = !settings || settings.showActionFabs !== false;
    const rings = expert
      ? {
          inner: ["btnSuper", "btnAuto", "btnCover", "btnWorkshop"],
          outer: ["btnMeta", "btnConfig", "btnBmc"],
        }
      : {
          inner: ["btnSuper", "btnCover"],
          outer: ["btnAuto", "btnConfig", "btnBmc"],
        };
    // L'Atelier répond 403 quand l'enrichissement des tomes est coupé côté
    // serveur : un bouton qui mène à une erreur ne vaut pas mieux que pas de
    // bouton. On ne retire que sur un `false` explicite — tant que le serveur
    // n'a rien dit, on ne présume pas de ce qu'il sait faire.
    const volumesOff =
      seriesState && seriesState.status && seriesState.status.volumes_enabled === false;
    const keep = (name) =>
      (showActions || !ACTION_BUTTONS.includes(name)) &&
      !(name === "btnWorkshop" && volumesOff) &&
      els[name];
    return {
      inner: rings.inner.filter(keep).map((n) => els[n]),
      outer: rings.outer.filter(keep).map((n) => els[n]),
    };
  }

  /** Libellé de la pastille, dans la langue de l'utilisateur. */
  function badgeLabel(badge) {
    const key = {
      done: "badgeDone",
      working: "badgeWorking",
      pending: "badgePending",
      ignored: "badgeIgnored",
      unknown: "badgeUnknown",
    }[badge];
    return key ? t(key) : "";
  }

  function applyBadge() {
    if (!els.btnLogo) return;
    const badge = seriesState && seriesState.badge;
    if (!badge) {
      els.btnLogo.removeAttribute("data-state");
      els.btnLogo.title = "MetaKavita";
      els.btnLogo.setAttribute("aria-label", t("fabLogo"));
      return;
    }
    const label = badgeLabel(badge);
    els.btnLogo.setAttribute("data-state", badge);
    els.btnLogo.title = label ? "MetaKavita — " + label : "MetaKavita";
    // L'état part aussi dans le nom accessible : une pastille qui n'existe
    // qu'en couleur ne dit rien à qui ne la voit pas.
    els.btnLogo.setAttribute("aria-label", label ? t("fabLogo") + " — " + label : t("fabLogo"));
  }

  /** Interroge le serveur sur la série courante. Silencieux en cas d'échec. */
  async function refreshSeriesState(sid) {
    seriesState = null;
    applyBadge();
    if (!sid || !settings || !settings.metaBaseUrl || !settings.webhookToken) return;
    try {
      const res = await chrome.runtime.sendMessage({
        type: "seriesStatus",
        seriesId: Number(sid),
      });
      // Série changée entre-temps : ne pas peindre l'état de la précédente.
      if (String(seriesId) !== String(sid)) return;
      if (res && res.ok) {
        seriesState = res;
        applyBadge();
        refreshFabVisibility();
      }
    } catch {
      /* extension rechargée : la pastille reste muette */
    }
  }

  function refreshFabVisibility() {
    if (!els.btnLogo) return;
    const { inner, outer } = composeRings();
    const shown = new Set([...inner, ...outer]);
    for (const name of Object.keys(els)) {
      if (!name.startsWith("btn") || name === "btnLogo" || name === "btnCloseConfig") continue;
      const el = els[name];
      if (el && el.classList && el.classList.contains("fab")) {
        el.style.display = shown.has(el) ? "" : "none";
      }
    }
    // La couronne extérieure porte des disques plus petits et plus sourds : la
    // classe suit la couronne, pas le bouton, puisque Auto change de camp.
    inner.forEach((el) => el.classList.remove("fab--outer"));
    outer.forEach((el) => el.classList.add("fab--outer"));
    els.ringInner = inner;
    els.ringOuter = outer;
    if (menuOpen) layoutConstellation();
  }

  async function reloadSettings() {
    // Un seul aller-retour : réglages, langue résolue et table de traductions.
    const res = await chrome.runtime.sendMessage({ type: "uiBootstrap" });
    settings = (res && res.settings) || {};
    if (res && res.strings) STRINGS = res.strings;
    if (res && res.uiMode) uiMode = res.uiMode;
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
          reviewWin = window.open(finalUrl, "_blank");
        }
      } else {
        showToast(t("toastMixedContentTab"));
        reviewWin = window.open(finalUrl, "_blank");
      }
      // Le pont n'accepte un `mk:mr-done` que de CETTE fenêtre : sans cette
      // référence, la branche « fenêtre dédiée » ne vérifiait ni l'origine ni
      // l'émetteur, alors que la doc affirmait le contraire.
      if (typeof window.__mkCompanionRememberReviewWindow === "function") {
        window.__mkCompanionRememberReviewWindow(reviewWin);
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

  /**
   * Demande confirmation avant un geste qui écrit sans rien montrer.
   *
   * Dans le shadow root, et non via `window.confirm` : une boîte du navigateur
   * s'annonce au nom de Kavita, pas au nôtre — on demanderait à l'utilisateur
   * d'autoriser une écriture au nom d'un site qui n'en est pas l'auteur.
   *
   * Rend `"go"`, `"review"` (l'utilisateur préfère voir d'abord) ou `"cancel"`.
   */
  function askBeforeBlindWrite() {
    return new Promise((resolve) => {
      const layer = createOverlayLayer("confirm", () => resolve("cancel"));
      if (!layer) {
        resolve("go");
        return;
      }
      let settled = false;
      const answer = (value) => {
        if (settled) return;
        settled = true;
        resolve(value);
        layer.destroy();
      };

      const card = document.createElement("div");
      card.className = "mk-confirm";
      const text = document.createElement("p");
      text.textContent = t("confirmAutoBody");

      const row = document.createElement("div");
      row.className = "mk-row";
      const go = document.createElement("button");
      go.type = "button";
      go.className = "mk-btn mk-btn--warn";
      go.textContent = t("confirmGo");
      go.addEventListener("click", () => answer("go"));

      const review = document.createElement("button");
      review.type = "button";
      review.className = "mk-btn mk-btn--ghost";
      review.textContent = t("confirmAutoSeeFirst");
      review.addEventListener("click", () => answer("review"));

      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.className = "mk-btn mk-btn--ghost";
      cancel.textContent = t("confirmCancel");
      cancel.addEventListener("click", () => answer("cancel"));

      row.append(go, review, cancel);
      card.append(text, row);
      layer.node.className = "mk-layer mk-layer--confirm";
      layer.node.appendChild(card);
      layer.node.addEventListener("click", (e) => {
        if (e.target === layer.node) answer("cancel");
      });
      go.focus?.();
    });
  }

  /**
   * Ouvre une page MetaKavita dans un onglet, `$1$` remplacé par la série.
   *
   * `settings.metaBaseUrl` est déjà normalisée en stockage : rien à calculer,
   * donc rien à attendre — le `window.open` reste dans le geste de clic.
   */
  function openMetaPage(pathTemplate) {
    const base = String((settings && settings.metaBaseUrl) || "");
    if (!base) {
      showToast(t("toastNeedConfig"), true);
      openConfig();
      return;
    }
    if (!seriesId) {
      showToast(t("toastNeedSeriesPage"), true);
      return;
    }
    setMenuOpen(false);
    window.open(base + pathTemplate.replace("$1$", String(seriesId)), "_blank", "noopener");
  }

  /**
   * INDICE seulement : le nom fait foi côté serveur, qui l'obtient de Kavita.
   * Celui-ci ne sert que de texte d'attente dans le champ, et de repli quand
   * MetaKavita n'arrive pas à joindre Kavita.
   */
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
          count: t("coverCount"),
          needConfig: t("toastNeedConfig"),
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
          <button type="button" class="fab fab-workshop" id="btnWorkshop">${WORKSHOP_ICON}</button>
          <button type="button" class="fab fab--outer fab-meta" id="btnMeta">${META_ICON}</button>
          <button type="button" class="fab fab--outer fab-config" id="btnConfig">${CONFIG_ICON}</button>
          <button type="button" class="fab fab--outer fab-bmc" id="btnBmc">${BMC_ICON}</button>
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
          <label for="uiMode" data-i18n="configMode"></label>
          <select id="uiMode">
            <option value="simple" data-i18n="configModeSimple"></option>
            <option value="expert" data-i18n="configModeExpert"></option>
          </select>
        </div>
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
      btnWorkshop: shadow.getElementById("btnWorkshop"),
      btnMeta: shadow.getElementById("btnMeta"),
      btnConfig: shadow.getElementById("btnConfig"),
      btnBmc: shadow.getElementById("btnBmc"),
      configPanel: shadow.getElementById("configPanel"),
      metaUrl: shadow.getElementById("metaUrl"),
      token: shadow.getElementById("token"),
      showFabs: shadow.getElementById("showFabs"),
      cacheBust: shadow.getElementById("cacheBust"),
      uiLang: shadow.getElementById("uiLang"),
      uiMode: shadow.getElementById("uiMode"),
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
    // Atelier et fiche MetaKavita : de simples navigations de premier niveau.
    // Le cookie de session MetaKavita part avec (SameSite=Lax), donc aucune
    // API, aucun jeton, rien à émettre.
    els.btnWorkshop.addEventListener("click", () => openMetaPage("/series/$1$/volumes"));
    els.btnMeta.addEventListener("click", () => openMetaPage("/?series=$1$"));
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
        // Auto écrit dans Kavita sans rien montrer d'abord. En mode expert
        // c'est le geste attendu ; en mode simplifié, on demande — et on offre
        // la sortie utile : voir avant d'écrire.
        if (uiMode !== "expert") {
          setMenuOpen(false);
          const answer = await askBeforeBlindWrite();
          if (answer === "cancel") return;
          if (answer === "review") {
            const started = await runWebhook({ force: true, super_review: true });
            if (started) await openMr();
            return;
          }
        }
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
        uiMode: els.uiMode.value,
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
      const version = (result && result.server && result.server.version) || "";
      if (result && result.ok) {
        showToast(version ? t("toastTestOkVersion").replace("$1$", version) : t("toastTestOk"));
      }
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
    refreshSeriesState(sid);
  }

  const layers = new Set();

  /**
   * Point de montage pour un overlay, DANS le shadow root fermé.
   *
   * La poignée du shadow n'est jamais exposée : l'exposer rendrait le panneau
   * de config — champ jeton compris — atteignable depuis la page Kavita, ce
   * que `mode: "closed"` existe précisément pour empêcher.
   *
   * Le calque est frère de `.wrap`, jamais dedans : `.fab-stack` porte un
   * `transform`, et un ancêtre transformé change le référentiel d'un
   * `position: fixed`.
   */
  function createOverlayLayer(name, onDestroy) {
    if (!shadow) return null;
    const node = document.createElement("div");
    node.className = "mk-layer mk-layer--" + name;
    shadow.appendChild(node);
    const handle = {
      node,
      destroy() {
        if (!layers.has(handle)) return;
        layers.delete(handle);
        node.remove();
        if (typeof onDestroy === "function") onDestroy();
      },
    };
    layers.add(handle);
    return handle;
  }

  /** Ferme la couche la plus haute qui nous appartienne. Rend `true` si elle a agi. */
  function closeTop() {
    if (!uiAlive()) return false;
    if (els.configPanel.classList.contains("is-open")) {
      closeConfig();
      return true;
    }
    if (menuOpen) {
      setMenuOpen(false);
      return true;
    }
    return false;
  }

  function unmount() {
    mountGen += 1;
    // Les overlays d'abord : chacun annule ses propres timers en se détruisant.
    for (const layer of [...layers]) layer.destroy();
    if (typeof window.__mkCompanionRemoveToast === "function") {
      window.__mkCompanionRemoveToast();
    }
    if (root) root.remove();
    root = null;
    shadow = null;
    els = {};
    seriesId = null;
    menuOpen = false;
  }

  function setSeriesId(sid) {
    if (String(seriesId) === String(sid)) return;
    seriesId = sid;
    refreshSeriesState(sid);
  }

  window.__mkCompanionPageUI = { mount, unmount, setSeriesId, createOverlayLayer, closeTop };
})();
