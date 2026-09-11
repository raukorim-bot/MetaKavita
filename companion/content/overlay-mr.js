/**
 * Super Review : l'iframe d'embed, son repli, et le pont `postMessage`.
 *
 * L'overlay vit dans le shadow root FERMÉ de `page-ui.js`, obtenu par
 * `createOverlayLayer` — la poignée du shadow n'est jamais exposée. Avant, il
 * était bâti dans le DOM clair de Kavita : le CSS du site pouvait le casser, et
 * la page pouvait lire et modifier ses nœuds.
 */
(function () {
  "use strict";

  if (window.__mkCompanionOverlayMr) return;
  window.__mkCompanionOverlayMr = true;

  let state = null;

  /**
   * Fenêtre dédiée ouverte en contenu mixte. Mémorisée ici pour que le pont
   * puisse vérifier l'ÉMETTEUR d'un `mk:mr-done` : sans elle, cette branche
   * n'avait ni contrôle d'origine ni contrôle de source, alors que la
   * documentation affirmait le contraire.
   */
  let reviewWin = null;

  function rememberReviewWindow(win) {
    reviewWin = win || null;
  }

  function closeMr() {
    // Quitter la fiche referme aussi le canal de la fenêtre dédiée.
    reviewWin = null;
    if (!state) return false;
    if (state.readyTimer) clearTimeout(state.readyTimer);
    const layer = state.layer;
    state = null;
    if (layer) layer.destroy();
    return true;
  }

  function showMrFallback() {
    if (!state || !state.fallback) return;
    state.fallback.hidden = false;
    if (typeof window.__mkCompanionShowToast === "function") {
      window.__mkCompanionShowToast(state.labels.timeout, true);
    }
  }

  function openMrOverlay(opts) {
    closeMr();
    if (typeof window.__mkCompanionCloseCover === "function") window.__mkCompanionCloseCover();

    const ui = window.__mkCompanionPageUI;
    if (!ui || typeof ui.createOverlayLayer !== "function") return;
    const layer = ui.createOverlayLayer("mr", closeMr);
    if (!layer) return;

    const labels = (opts && opts.labels) || {};
    const backdrop = layer.node;
    backdrop.className = "mk-layer mk-layer--mr";
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) closeMr();
    });

    const iframe = document.createElement("iframe");
    iframe.title = labels.title || "MetaKavita Super Review";
    iframe.setAttribute("allow", "clipboard-write");
    iframe.className = "mk-mr-frame";
    iframe.src = opts.url;

    const closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "mk-mr-close";
    closeBtn.textContent = labels.close || "Close";
    closeBtn.addEventListener("click", closeMr);

    const fallback = document.createElement("div");
    fallback.hidden = true;
    fallback.className = "mk-mr-fallback";
    const fbText = document.createElement("p");
    fbText.textContent = labels.blocked || "Super Review couldn't load here.";
    const fbLink = document.createElement("button");
    fbLink.type = "button";
    fbLink.className = "mk-mr-open-tab";
    fbLink.textContent = labels.openTab || "Open in a new tab";
    fbLink.addEventListener("click", () => {
      // Garder l'opener : c'est lui qui permet à la revue de redonner le focus
      // à Kavita et de fermer sa propre fenêtre en fin de parcours.
      rememberReviewWindow(window.open(opts.url, "_blank"));
      window.setTimeout(closeMr, 150);
    });
    fallback.appendChild(fbText);
    fallback.appendChild(fbLink);

    backdrop.appendChild(iframe);
    backdrop.appendChild(closeBtn);
    backdrop.appendChild(fallback);

    state = {
      layer,
      iframe,
      fallback,
      labels,
      metaOrigin: opts.metaOrigin || "",
      cacheBust: !!opts.cacheBust,
      seriesId: opts.seriesId,
      ready: false,
      readyTimer: null,
    };
    state.readyTimer = setTimeout(() => {
      if (state && !state.ready) showMrFallback();
    }, 7000);
  }

  /**
   * Un seul émetteur a le droit de parler à cette page : l'embed MetaKavita.
   * Contrôlé sur `ev.origin` ET sur `ev.source`, sans exception — le pont
   * supprimé en 1.0.27 prenait ses ordres de n'importe quelle fenêtre.
   */
  window.addEventListener("message", (ev) => {
    const data = ev.data;
    if (!data || data.source !== "metakavita-companion") return;

    // Super Review ouverte en fenêtre dédiée (contenu mixte) : elle poste vers
    // son opener, sans iframe dans la page. C'est la fenêtre QUE NOUS AVONS
    // OUVERTE qui est acceptée, pas n'importe laquelle.
    if (!state || !state.iframe) {
      if (!reviewWin || ev.source !== reviewWin) return;
      if (data.type === "mk:mr-done") {
        if (data.outcome === "confirm" && data.seriesId
            && typeof window.__mkCompanionCacheBust === "function") {
          window.__mkCompanionCacheBust(String(data.seriesId));
        }
        // La revue est conclue : cette fenêtre n'a plus rien à nous dire, et la
        // garder en mémoire laisserait un émetteur autorisé traîner.
        reviewWin = null;
      }
      return;
    }

    if (ev.source !== state.iframe.contentWindow) return;
    if (state.metaOrigin && ev.origin !== state.metaOrigin) return;

    if (data.type === "mk:embed-ready") {
      state.ready = true;
      clearTimeout(state.readyTimer);
      state.readyTimer = null;
      if (state.fallback) state.fallback.hidden = true;
      return;
    }
    if (data.type === "mk:mr-timeout") {
      if (typeof window.__mkCompanionShowToast === "function") {
        window.__mkCompanionShowToast(state.labels.timeout, true);
      }
      return;
    }
    if (data.type === "mk:mr-done") {
      const shouldBust = data.outcome === "confirm" && state.cacheBust;
      const sid = state.seriesId;
      closeMr();
      if (shouldBust && typeof window.__mkCompanionCacheBust === "function") {
        window.__mkCompanionCacheBust(sid);
      }
    }
  });

  window.__mkCompanionOpenMr = openMrOverlay;
  window.__mkCompanionCloseMr = closeMr;
  window.__mkCompanionRememberReviewWindow = rememberReviewWindow;
})();
