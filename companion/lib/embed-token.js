/**
 * Jetons d'embed Companion : émission, cache, invalidation.
 *
 * Un jeton est émis pour UNE série et ouvre, pendant sa durée de vie, les
 * routes de review de cette série. Il en circule donc le moins possible.
 */

/**
 * Les jetons vivent 15 min côté serveur ; on expire les nôtres plus tôt pour
 * qu'une requête ne parte jamais avec un jeton qui meurt en vol.
 *
 * ⚠️ Ce plancher est un contrat avec le serveur : voir le commentaire de
 * `DEFAULT_TTL_SEC` dans `services/companion_embed_auth.py`, qui interdit de
 * descendre le TTL serveur sous ~11 min à cause de cette réutilisation.
 */
export const EMBED_TOKEN_REUSE_MS = 10 * 60 * 1000;

const embedTokenCache = new Map();

/**
 * Frappe la route d'émission. **Seul point du paquet qui la connaisse** — un
 * test l'exige, pour que le nombre de jetons vivants reste comptable.
 *
 * Rend le détail de l'échec (et non `""`) parce que l'ouverture de la Super
 * Review en dépend : `not_configured` ouvre le panneau de config, un HTTP 401
 * dit tout autre chose.
 *
 * @returns {Promise<{ok: boolean, token?: string, seriesId?: number, error?: string, code?: string, status?: number}>}
 */
export async function mintEmbedToken(base, webhookToken, seriesId, { parentOrigin = "" } = {}) {
  try {
    const res = await fetch(`${base}/companion/embed-token`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Webhook-Token": webhookToken,
      },
      body: JSON.stringify({
        seriesId,
        parent_origin: parentOrigin || chrome.runtime.getURL("").replace(/\/$/, ""),
      }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      return {
        ok: false,
        error: (body && body.message) || `HTTP ${res.status}`,
        code: body && body.code,
        status: res.status,
      };
    }
    if (!body.embed_token) return { ok: false, error: "no_token" };
    return { ok: true, token: body.embed_token, seriesId: body.series_id };
  } catch (e) {
    return { ok: false, error: String(e && e.message ? e.message : e) };
  }
}

/**
 * Un jeton par série, réutilisé tant qu'il vit. Ouvrir le cover picker, c'est
 * un appel pour la liste puis un par aperçu : en émettre un à chaque fois
 * demandait une vingtaine de jetons à MetaKavita pour afficher une grille, et
 * laissait autant d'accès vivants derrière soi.
 *
 * ⚠️ La Super Review, elle, appelle `mintEmbedToken` directement : elle a
 * besoin d'un jeton à durée pleine. Un jeton du cache peut n'avoir que quelques
 * minutes à vivre, ce qui suffit à un aperçu et pas à une revue.
 */
export async function getEmbedToken(base, webhookToken, seriesId) {
  const key = `${base}|${seriesId}`;
  const cached = embedTokenCache.get(key);
  if (cached && cached.expires > Date.now()) return cached.token;
  const res = await mintEmbedToken(base, webhookToken, seriesId);
  if (res.ok) {
    embedTokenCache.set(key, { token: res.token, expires: Date.now() + EMBED_TOKEN_REUSE_MS });
    return res.token;
  }
  return "";
}

/** Changer d'adresse ou de jeton webhook invalide tout ce qu'on détient. */
export function forgetEmbedTokens() {
  embedTokenCache.clear();
}
