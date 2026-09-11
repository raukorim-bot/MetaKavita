/** Jeton d'embed pour la Super Review. */
import { loadSettings, normalizeBaseUrl } from "../storage.js";
import { mintEmbedToken } from "../embed-token.js";

export async function embedToken(msg) {
  const settings = await loadSettings();
  const base = normalizeBaseUrl(settings.metaBaseUrl);
  if (!base || !settings.webhookToken) return { ok: false, error: "not_configured" };

  const seriesId = Number(msg.seriesId);
  if (!Number.isFinite(seriesId) || seriesId <= 0) {
    return { ok: false, error: "missing_series_id" };
  }

  // Jeton FRAIS, pas celui du cache : la revue dure, et un jeton déjà entamé
  // mourrait en son milieu. Voir le commentaire de `getEmbedToken`.
  const minted = await mintEmbedToken(base, settings.webhookToken, seriesId, {
    parentOrigin: msg.parentOrigin,
  });
  return minted.ok
    ? { ok: true, embed_token: minted.token, series_id: minted.seriesId }
    : { ok: false, error: minted.error, code: minted.code, status: minted.status };
}
