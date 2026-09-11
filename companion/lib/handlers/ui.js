/**
 * Ce que le content script ne peut pas calculer lui-même.
 *
 * `content/page-ui.js` est injecté comme script CLASSIQUE : il ne peut pas
 * `import`. Il en portait donc deux copies — la table de traductions et quatre
 * fonctions d'URL — que rien ne pouvait empêcher de diverger de leur original.
 * Il demande maintenant, au lieu de dupliquer.
 */
import {
  loadSettings,
  effectiveUiMode,
  normalizeBaseUrl,
  originFromUrl,
  tokenFromPastedUrl,
  isMetaKavitaUrl,
} from "../storage.js";
import { resolveUiLang, stringsFor } from "../i18n.js";

/**
 * Réglages + langue résolue + table de traductions, en un seul aller-retour.
 *
 * Un seul appel : `t()` doit rester SYNCHRONE côté page (il est appelé depuis
 * des gestionnaires d'événements), donc la table est mise en cache au montage.
 */
export async function uiBootstrap() {
  const settings = await loadSettings();
  const lang = resolveUiLang(settings.uiLang);
  // Le mode est DÉDUIT quand l'utilisateur n'a rien choisi : c'est au worker de
  // le trancher, pas à chaque page de refaire la déduction dans son coin.
  return { ok: true, settings, lang, uiMode: effectiveUiMode(settings), strings: stringsFor(lang) };
}

/**
 * Normalisation d'une URL saisie par l'utilisateur, faite côté worker.
 *
 * Tous les appelants sont des gestionnaires `async` (Enregistrer, Tester,
 * Activer ce site) : l'aller-retour n'ajoute aucune contrainte.
 *
 * ⚠️ Il n'existe PAS d'équivalent pour l'ouverture de la Super Review : la
 * décision « contenu mixte » doit précéder le `window.open` tant que le clic
 * compte encore comme une activation utilisateur. Elle lit `metaBaseUrl` dans
 * les réglages, que `saveSettings` normalise déjà à l'écriture.
 */
export async function urlInfo(msg) {
  const raw = String(msg.url || "");
  const settings = await loadSettings();
  const metaBaseUrl = msg.metaBaseUrl === undefined ? settings.metaBaseUrl : msg.metaBaseUrl;
  return {
    ok: true,
    base: normalizeBaseUrl(raw),
    origin: originFromUrl(raw),
    token: tokenFromPastedUrl(raw),
    isMeta: msg.pageUrl ? isMetaKavitaUrl(msg.pageUrl, metaBaseUrl) : false,
  };
}
