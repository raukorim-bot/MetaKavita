/**
 * Routeur SPA : décide quand le menu flottant se monte et se démonte.
 *
 * Chargé en DERNIER (`lib/watch-files.js`) : c'est le seul fichier de `content/`
 * qui amorce quelque chose au chargement, donc le seul qui ait besoin que les
 * autres aient déjà défini leurs globales.
 */
(function () {
  "use strict";

  if (window.__mkCompanionWatch) {
    window.dispatchEvent(new Event("mk-companion-nav"));
    return;
  }
  window.__mkCompanionWatch = true;

  // Fiche série uniquement — pas les sous-chemins du lecteur (/manga/, /book/,
  // /chapter/).
  const SERIES_RE = /\/library\/(\d+)\/series\/(\d+)\/?$/;
  let appearTimer = null;
  let lastSeriesId = null;
  // Dernière série VUE DANS L'URL, distincte de celle réellement montée : le
  // montage est différé de 400 ms, et deux navigations rapprochées doivent
  // quand même refermer les overlays de la première.
  let lastPathSeriesId = null;

  function parseSeriesId(pathname) {
    const m = SERIES_RE.exec(pathname || "");
    return m ? m[2] : null;
  }

  function closeOverlays() {
    if (typeof window.__mkCompanionCloseCover === "function") window.__mkCompanionCloseCover();
    if (typeof window.__mkCompanionCloseMr === "function") window.__mkCompanionCloseMr();
  }

  function removeUi() {
    if (window.__mkCompanionPageUI) window.__mkCompanionPageUI.unmount();
    lastSeriesId = null;
  }

  function mountUi(seriesId) {
    if (lastSeriesId === seriesId && document.getElementById("mk-companion-page-host")) {
      if (window.__mkCompanionPageUI) window.__mkCompanionPageUI.setSeriesId(seriesId);
      return;
    }
    if (!chrome.runtime?.id) {
      removeUi();
      return;
    }
    lastSeriesId = seriesId;
    if (window.__mkCompanionPageUI) window.__mkCompanionPageUI.mount(seriesId);
  }

  function schedule() {
    if (appearTimer) {
      clearTimeout(appearTimer);
      appearTimer = null;
    }
    if (!chrome.runtime?.id) {
      closeOverlays();
      removeUi();
      return;
    }
    const seriesId = parseSeriesId(location.pathname);
    if (!seriesId) {
      closeOverlays();
      removeUi();
      lastPathSeriesId = null;
      return;
    }
    // Les overlays capturent leur série à l'ouverture. Laissés en place après
    // un changement de fiche, ils continueraient d'écrire sur la précédente —
    // une couverture appliquée à la série qu'on vient de quitter, sous les yeux
    // de quelqu'un qui en regarde une autre. On ferme dès la navigation, sans
    // attendre le montage différé.
    //
    // Le re-rendu de la MÊME fiche, lui, ne ferme rien : Angular republie
    // parfois la même URL, et refermer le sélecteur sous les doigts de
    // l'utilisateur serait aussi gênant que le laisser sur la mauvaise série.
    if (lastPathSeriesId !== null && lastPathSeriesId !== seriesId) closeOverlays();
    lastPathSeriesId = seriesId;
    appearTimer = setTimeout(function () {
      if (parseSeriesId(location.pathname) === seriesId) mountUi(seriesId);
    }, 400);
  }

  function patchHistory() {
    const wrap = (fn) =>
      function () {
        const ret = fn.apply(this, arguments);
        window.dispatchEvent(new Event("mk-companion-nav"));
        return ret;
      };
    try {
      history.pushState = wrap(history.pushState.bind(history));
      history.replaceState = wrap(history.replaceState.bind(history));
    } catch {
      /* ignore */
    }
    window.addEventListener("popstate", schedule);
    window.addEventListener("mk-companion-nav", schedule);
  }

  /**
   * UN SEUL écouteur d'Échap pour toute l'extension.
   *
   * Il y en avait deux — un dans `page-ui.js` en capture, un ici — qui
   * pouvaient fermer deux choses d'un même appui. Chaque couche ferme ce
   * qu'elle possède et dit si elle a agi ; on s'arrête à la première.
   *
   * L'événement traverse le shadow root fermé (il est composé), donc l'écouter
   * sur `document` suffit à couvrir les overlays.
   */
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    const closers = [
      window.__mkCompanionCloseCover,
      window.__mkCompanionCloseMr,
      window.__mkCompanionPageUI && window.__mkCompanionPageUI.closeTop,
    ];
    for (const close of closers) {
      if (typeof close === "function" && close()) return;
    }
  });

  patchHistory();
  schedule();
})();
