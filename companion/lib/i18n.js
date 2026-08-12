const FR = {
  fabSuper: "Super Review",
  fabAuto: "Auto",
  fabCover: "Cover",
  fabConfig: "Config",
  fabBmc: "M'offrir un café",
  fabLogo: "Ouvrir le menu MetaKavita",
  configTitle: "Réglages Companion",
  configMetaUrl: "URL MetaKavita",
  configToken: "Jeton webhook",
  configShowFabs: "Afficher les boutons Super / Auto / Cover",
  coverTitle: "Choisir une couverture",
  coverSearch: "Rechercher",
  coverSearching: "Recherche des couvertures…",
  coverEmpty: "Aucune couverture trouvée",
  coverApplied: "Couverture appliquée",
  coverApplyFail: "Échec de l’application de la couverture",
  coverPreviewFail: "Aperçu indisponible",
  coverPreviewLogin: "Aperçus refusés par MetaKavita (connexion requise) — instance à jour ?",
  configCacheBust: "Rafraîchir la couverture après confirm (anti-cache)",
  configLang: "Langue",
  configLangAuto: "Auto (navigateur)",
  configLangFr: "Français",
  configLangEn: "English",
  configSave: "Enregistrer",
  configTest: "Tester la connexion",
  configEnableSite: "Activer sur ce site Kavita",
  toastSaved: "Réglages enregistrés",
  toastSavedNeedPermission: "Enregistré — autorisez l’accès au site MetaKavita",
  toastSiteEnabled: "Site Kavita mémorisé — valable pour toutes les fenêtres",
  toastSiteEnabledHintSeries: "Site mémorisé — ouvrez une fiche /library/…/series/…",
  toastNeedConfig: "Configurez d’abord le Companion",
  toastQueued: "Ajouté à la file d’enrichissement",
  toastError: "Erreur : $1$",
  toastTestOk: "Connexion OK",
  toastTestFail: "Échec de connexion",
  toastTestFailToken: "Jeton webhook invalide",
  toastTestFailHealth: "MetaKavita injoignable (/healthz)",
  toastTestFailNetwork: "Erreur réseau vers MetaKavita",
  toastNeedHosts: "Ouvrez d’abord un onglet Kavita, puis réessayez",
  toastNeedSeriesPage: "Ouvrez une fiche série Kavita (/library/…/series/…)",
  toastMetaIsNotKavita: "Ceci est MetaKavita — ouvrez votre site Kavita puis activez",
  toastPermissionDenied: "Permission refusée",
  toastSiteAlreadyEnabled: "Ce site Kavita est déjà activé",
  toastUsePopupForPermission: "Ouvrez le popup Companion (icône) pour autoriser MetaKavita",
  toastEnableFail: "Activation impossible — réessayez depuis le popup Companion",
  toastNeedMetaLogin: "Connectez-vous à MetaKavita dans un onglet, puis réessayez Super Review",
  toastKavitaUnreachable: "Kavita injoignable depuis MetaKavita",
  toastSeriesNotFound: "Série introuvable dans Kavita",
  toastMrTimeout: "Super Review : délai dépassé",
  toastExtensionReloaded: "Extension rechargée — rechargez la page Kavita",
  mrEmbedBlocked: "Super Review n’a pas pu s’afficher ici (navigateur/sécurité). Ouvrez-le dans un onglet.",
  mrOpenInTab: "Ouvrir dans un onglet",
  toastMixedContentTab: "Kavita est en HTTPS et MetaKavita en HTTP — Super Review s’ouvre dans un onglet",
  toastMixedContentWindow: "Kavita est en HTTPS et MetaKavita en HTTP — Super Review s’ouvre dans une fenêtre dédiée",
  close: "Fermer",
};

const EN = {
  fabSuper: "Super Review",
  fabAuto: "Auto",
  fabCover: "Cover",
  fabConfig: "Config",
  fabBmc: "Buy me a coffee",
  fabLogo: "Open MetaKavita menu",
  configTitle: "Companion settings",
  configMetaUrl: "MetaKavita URL",
  configToken: "Webhook token",
  configShowFabs: "Show Super / Auto / Cover buttons",
  coverTitle: "Pick a cover",
  coverSearch: "Search",
  coverSearching: "Searching covers…",
  coverEmpty: "No covers found",
  coverApplied: "Cover applied",
  coverApplyFail: "Failed to apply cover",
  coverPreviewFail: "Preview unavailable",
  coverPreviewLogin: "MetaKavita refused the previews (login required) — instance up to date?",
  configCacheBust: "Refresh cover after confirm (cache bust)",
  configLang: "Language",
  configLangAuto: "Auto (browser)",
  configLangFr: "Français",
  configLangEn: "English",
  configSave: "Save",
  configTest: "Test connection",
  configEnableSite: "Enable on this Kavita site",
  toastSaved: "Settings saved",
  toastSavedNeedPermission: "Saved — allow access to the MetaKavita site",
  toastSiteEnabled: "Kavita site saved — applies to all windows",
  toastSiteEnabledHintSeries: "Site saved — open a /library/…/series/… page",
  toastNeedConfig: "Configure Companion first",
  toastQueued: "Queued for enrichment",
  toastError: "Error: $1$",
  toastTestOk: "Connection OK",
  toastTestFail: "Connection failed",
  toastTestFailToken: "Invalid webhook token",
  toastTestFailHealth: "MetaKavita unreachable (/healthz)",
  toastTestFailNetwork: "Network error reaching MetaKavita",
  toastNeedHosts: "Open a Kavita tab first, then try again",
  toastNeedSeriesPage: "Open a Kavita series page (/library/…/series/…)",
  toastMetaIsNotKavita: "This is MetaKavita — open your Kavita site, then enable",
  toastPermissionDenied: "Permission denied",
  toastSiteAlreadyEnabled: "This Kavita site is already enabled",
  toastUsePopupForPermission: "Open the Companion popup (toolbar icon) to allow MetaKavita",
  toastEnableFail: "Could not enable — retry from the Companion popup",
  toastNeedMetaLogin: "Log into MetaKavita in a tab, then retry Super Review",
  toastKavitaUnreachable: "Kavita unreachable from MetaKavita",
  toastSeriesNotFound: "Series not found in Kavita",
  toastMrTimeout: "Super Review timed out",
  toastExtensionReloaded: "Extension reloaded — refresh the Kavita page",
  mrEmbedBlocked: "Super Review couldn’t load here (browser/security). Open it in a tab.",
  mrOpenInTab: "Open in a new tab",
  toastMixedContentTab: "Kavita is HTTPS and MetaKavita is HTTP — opening Super Review in a tab",
  toastMixedContentWindow: "Kavita is HTTPS and MetaKavita is HTTP — opening Super Review in a dedicated window",
  close: "Close",
};

let overrideLang = "auto";

export function setUiLang(lang) {
  overrideLang = lang || "auto";
}

function resolveLang() {
  if (overrideLang === "fr" || overrideLang === "en") return overrideLang;
  const ui = (chrome.i18n && chrome.i18n.getUILanguage && chrome.i18n.getUILanguage()) || "en";
  return String(ui).toLowerCase().startsWith("fr") ? "fr" : "en";
}

export function t(key, fallback) {
  const lang = resolveLang();
  const table = lang === "fr" ? FR : EN;
  if (table[key]) return table[key];
  try {
    const msg = chrome.i18n.getMessage(key);
    if (msg) return msg;
  } catch {
    /* ignore */
  }
  return fallback || key;
}

export function applyI18n(root) {
  const el = root || document;
  el.querySelectorAll("[data-i18n]").forEach((node) => {
    const key = node.getAttribute("data-i18n");
    if (key) node.textContent = t(key);
  });
  el.querySelectorAll("[data-i18n-title]").forEach((node) => {
    const key = node.getAttribute("data-i18n-title");
    if (key) node.setAttribute("title", t(key));
  });
  el.querySelectorAll("[data-i18n-aria]").forEach((node) => {
    const key = node.getAttribute("data-i18n-aria");
    if (key) node.setAttribute("aria-label", t(key));
  });
}
