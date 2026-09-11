/**
 * Cover picker : recherche, grille d'aperçus, application.
 *
 * Vit dans le shadow root FERMÉ de `page-ui.js`. C'est un gain de sécurité
 * concret : les aperçus proxifiés arrivent en `data:` URL, et la page Kavita
 * ne peut plus lire le `src` de ces images.
 */
(function () {
  "use strict";

  if (window.__mkCompanionOverlayCover) return;
  window.__mkCompanionOverlayCover = true;

  let layerRef = null;

  function closeCover() {
    if (!layerRef) return false;
    const layer = layerRef;
    layerRef = null;
    layer.destroy();
    return true;
  }

  function toast(msg, isError) {
    if (typeof window.__mkCompanionShowToast === "function") {
      window.__mkCompanionShowToast(msg, !!isError);
    }
  }

  /**
   * Un aperçu passe par le service worker dans deux cas.
   *
   * Un aperçu proxifié exige des identifiants MetaKavita, et un `<img>` ne
   * porte ni cookie (cross-site) ni en-tête. Mettre le jeton d'embed dans
   * l'URL marchait — et livrait à tout script de la page un jeton bon pour
   * toutes les routes de review de la série.
   *
   * Et un aperçu `http://` est bloqué comme contenu mixte sur une page Kavita
   * `https://` ; les requêtes du worker y échappent.
   */
  function coverNeedsImageBridge(url) {
    if (!url || /^data:/i.test(url)) return false;
    if (url.indexOf("/api/proxy-image") !== -1) return true;
    return location.protocol === "https:" && /^http:\/\//i.test(url);
  }

  async function bridgeCoverImage(img, url, seriesId, onFail) {
    let error = "unavailable";
    try {
      const res = await chrome.runtime.sendMessage({ type: "fetchImageData", url, seriesId });
      if (res && res.ok && res.dataUrl) {
        img.src = res.dataUrl;
        return true;
      }
      error = (res && res.error) || error;
    } catch {
      error = "extension_reloaded";
    }
    if (typeof onFail === "function") onFail(error, url);
    return false;
  }

  function setCoverImageSrc(img, url, seriesId, onFail) {
    if (!url) return;
    if (coverNeedsImageBridge(url)) {
      bridgeCoverImage(img, url, seriesId, onFail);
      return;
    }
    img.addEventListener("error", () => bridgeCoverImage(img, url, seriesId, onFail), {
      once: true,
    });
    img.src = url;
  }

  function openCoverPicker(opts) {
    closeCover();
    if (typeof window.__mkCompanionCloseMr === "function") window.__mkCompanionCloseMr();

    const ui = window.__mkCompanionPageUI;
    if (!ui || typeof ui.createOverlayLayer !== "function") return;
    const layer = ui.createOverlayLayer("cover", () => {
      layerRef = null;
    });
    if (!layer) return;
    layerRef = layer;

    const labels = (opts && opts.labels) || {};
    const seriesId = opts.seriesId;
    const seriesName = opts.seriesName || "";

    const backdrop = layer.node;
    backdrop.className = "mk-layer mk-layer--cover";
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) closeCover();
    });

    const panel = document.createElement("div");
    panel.className = "mk-cover-panel";

    const header = document.createElement("div");
    header.className = "mk-cover-head";

    const title = document.createElement("strong");
    title.className = "mk-cover-title";
    title.textContent = labels.title || "Cover";

    const search = document.createElement("input");
    search.type = "text";
    search.className = "mk-cover-search";
    search.value = "";
    search.placeholder = seriesName || "";
    search.setAttribute("aria-label", labels.title || "Cover");

    const btnSearch = document.createElement("button");
    btnSearch.type = "button";
    btnSearch.className = "mk-btn";
    btnSearch.textContent = labels.search || "Search";

    const btnClose = document.createElement("button");
    btnClose.type = "button";
    btnClose.className = "mk-btn mk-btn--ghost";
    btnClose.textContent = labels.close || "Close";
    btnClose.addEventListener("click", closeCover);

    header.append(title, search, btnSearch, btnClose);

    const status = document.createElement("div");
    status.className = "mk-cover-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");

    const grid = document.createElement("div");
    grid.className = "mk-cover-grid";

    /** Motif technique → message traduit. L'erreur brute part en console. */
    function previewMessage(error) {
      if (error === "meta_login_required") return labels.previewLogin || "";
      if (error === "not_configured") return labels.needConfig || "";
      return labels.previewFail || "";
    }

    let resolvedOnce = false;

    /**
     * Premier chargement : on n'impose AUCUN nom, le serveur le résout auprès
     * de Kavita et nous le renvoie. Ensuite seulement, c'est ce que
     * l'utilisateur a tapé qui fait foi.
     *
     * Auparavant le nom était deviné dans le DOM de Kavita : un changement de
     * gabarit faisait chercher les couvertures d'une autre série, en silence.
     */
    async function loadCovers() {
      const typed = search.value.trim();
      grid.replaceChildren();
      status.textContent = labels.searching || "";
      btnSearch.disabled = true;
      try {
        const res = await chrome.runtime.sendMessage({
          type: "fetchCovers",
          seriesId,
          ...(resolvedOnce || typed ? { seriesName: typed } : { nameHint: seriesName }),
        });
        btnSearch.disabled = false;
        // Seulement sur SUCCÈS : marquer la résolution faite après un échec
        // réseau ferait partir la tentative suivante avec un nom vide — donc
        // une recherche sur la chaîne vide — au lieu de redemander au serveur.
        if (res && res.ok) {
          resolvedOnce = true;
          if (res.seriesName && !search.value.trim()) search.value = res.seriesName;
        }
        if (!res || !res.ok) {
          // Le motif technique (`HTTP 500`, `embed_token_failed`) n'a rien à
          // faire à l'écran d'une interface bilingue : il part en console.
          if (res && res.error) console.warn("[MetaKavita Companion] fetchCovers:", res.error);
          status.textContent = previewMessage(res && res.error) || labels.empty || "";
          return;
        }
        const covers = res.covers || [];
        if (!covers.length) {
          status.textContent = labels.empty || "";
          return;
        }
        status.textContent = (labels.count || "$1$").replace("$1$", String(covers.length));

        let reported = false;
        const reportPreviewError = (error, failedUrl) => {
          console.warn("[MetaKavita Companion] cover preview failed (" + error + "):", failedUrl);
          if (reported) return;
          reported = true;
          status.textContent = previewMessage(error) || labels.previewFail || "";
        };

        covers.forEach((cover) => {
          const card = document.createElement("button");
          card.type = "button";
          card.className = "mk-cover-card";

          const img = document.createElement("img");
          img.alt = "";
          img.title = cover.title || "";
          img.loading = "lazy";
          setCoverImageSrc(img, cover.display_url || cover.url || "", seriesId, reportPreviewError);

          const cap = document.createElement("div");
          cap.className = "mk-cover-cap";
          cap.textContent = cover.provider || cover.title || "";

          card.append(img, cap);
          card.addEventListener("click", async () => {
            card.disabled = true;
            const apply = await chrome.runtime.sendMessage({
              type: "applyCover",
              seriesId,
              // Le nom réellement cherché, pas l'indice tiré du DOM : il ne
              // sert qu'au journal côté serveur, qui retombe sur Kavita s'il
              // est vide. Mieux vaut rien qu'un titre faux.
              seriesName: search.value.trim(),
              coverUrl: cover.url,
            });
            card.disabled = false;
            if (apply && apply.ok) {
              toast(labels.applied || "");
              if (typeof window.__mkCompanionCacheBust === "function") {
                window.__mkCompanionCacheBust(seriesId);
              }
              closeCover();
            } else {
              if (apply && apply.error) {
                console.warn("[MetaKavita Companion] applyCover:", apply.error);
              }
              toast(labels.fail || "", true);
              status.textContent = labels.fail || "";
            }
          });
          grid.appendChild(card);
        });
      } catch {
        btnSearch.disabled = false;
        status.textContent = labels.fail || "";
      }
    }

    btnSearch.addEventListener("click", loadCovers);
    search.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        loadCovers();
      }
    });

    panel.append(header, status, grid);
    backdrop.appendChild(panel);
    loadCovers();
  }

  window.__mkCompanionOpenCover = openCoverPicker;
  window.__mkCompanionCloseCover = closeCover;
})();
