/**
 * Socle des content scripts : le toast de page et le rafraîchissement des
 * jaquettes. Chargé en PREMIER (voir `lib/watch-files.js`).
 *
 * Règle de couplage, valable pour tous les fichiers de ce dossier : un fichier
 * DÉFINIT ses globales au chargement, et ne LIT celles d'un autre qu'à
 * l'intérieur d'un callback. `watch.js` fait seule exception — elle amorce la
 * surveillance de navigation — et se charge donc en dernier.
 *
 * Le toast vit délibérément dans le DOM clair de la page, et non dans le shadow
 * root de `page-ui.js` : il doit pouvoir s'afficher quand ce dernier n'est pas
 * monté, précisément pour annoncer que quelque chose a échoué. Il ne porte
 * aucun secret.
 */
(function () {
  "use strict";

  if (window.__mkCompanionBase) return;
  window.__mkCompanionBase = true;

  const TOAST_ID = "mk-companion-page-toast";

  function showPageToast(text, isError) {
    let el = document.getElementById(TOAST_ID);
    if (!el) {
      el = document.createElement("div");
      el.id = TOAST_ID;
      // Annoncé aux lecteurs d'écran : un toast qui n'est que visuel laisse
      // sans nouvelle l'utilisateur qui ne regarde pas ce coin de l'écran.
      el.setAttribute("role", "status");
      el.setAttribute("aria-live", "polite");
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
    el.textContent = text || "";
    el.style.borderColor = isError ? "#f87171" : "rgba(148,163,184,0.4)";
    el.style.opacity = "1";
    clearTimeout(el.__mkTimer);
    el.__mkTimer = setTimeout(() => {
      el.style.opacity = "0";
    }, 3200);
  }

  /**
   * Force Kavita à recharger la jaquette d'UNE série après une écriture.
   *
   * Kavita sert ses couvertures en `/api/image/series-cover?seriesId=<id>`.
   * L'ancien test était un `includes` sur l'URL entière : pour la série 12,
   * « seriesId=125 » correspondait aussi — et la clause `/api/image` faisait
   * re-télécharger TOUTES les jaquettes de la page, bandeau de recommandations
   * compris, à chaque confirmation.
   */
  function softCacheBust(seriesId) {
    const sid = String(seriesId == null ? "" : seriesId).trim();
    if (!sid) return;
    const ts = Date.now();
    // Frontière de valeur : `seriesId=12` et pas `seriesId=125`.
    const exact = new RegExp("[?&]seriesid=" + sid + "(?:$|[&#])", "i");

    const all = Array.from(document.querySelectorAll("img[src]"));
    let targets = all.filter((img) => exact.test(img.getAttribute("src") || ""));
    if (!targets.length) {
      // Filet : Kavita a pu changer la forme de ses URL. On se rabat sur les
      // jaquettes DE SÉRIE — il y en a une sur une fiche — et non sur toute
      // image servie par /api/image.
      targets = all.filter((img) =>
        (img.getAttribute("src") || "").toLowerCase().includes("series-cover")
      );
    }

    targets.forEach((img) => {
      const src = img.getAttribute("src") || "";
      try {
        const u = new URL(src, location.origin);
        u.searchParams.set("_mkcb", String(ts));
        img.src = u.toString();
      } catch {
        img.src = src + (src.includes("?") ? "&" : "?") + "_mkcb=" + ts;
      }
    });
  }

  /** Retire le toast du DOM de Kavita : rien de nous ne doit y survivre. */
  function removePageToast() {
    const el = document.getElementById(TOAST_ID);
    if (!el) return;
    clearTimeout(el.__mkTimer);
    el.remove();
  }

  window.__mkCompanionShowToast = showPageToast;
  window.__mkCompanionCacheBust = softCacheBust;
  window.__mkCompanionRemoveToast = removePageToast;
})();
