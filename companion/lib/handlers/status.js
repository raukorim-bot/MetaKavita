/**
 * Où en est cette série, vue de MetaKavita.
 *
 * Sert la pastille du menu flottant, et le retrait du bouton Atelier quand
 * l'enrichissement des tomes est coupé côté serveur.
 */
import { loadSettings, normalizeBaseUrl } from "../storage.js";

/** Séries que MetaKavita considère traitées. */
const SETTLED = ["COMPLETED", "NOT_FOUND"];

/**
 * Couleur de la pastille, décidée ICI et non côté page : c'est la même règle
 * pour tout le monde, et elle se teste sans DOM.
 *
 * L'ordre compte — une série ignorée peut aussi porter un vieux statut, et une
 * série en file peut être « COMPLETED » d'une passe précédente. On annonce
 * toujours l'état le plus actuel.
 */
export function badgeFor(status) {
  if (!status || status.known !== true) return "unknown";
  if (status.inventory_excluded || status.status === "IGNORED") return "ignored";
  if (status.running || status.queued || status.pending_review) return "working";
  if (SETTLED.includes(status.status)) return "done";
  return "pending";
}

export async function seriesStatus(msg) {
  const settings = await loadSettings();
  const base = normalizeBaseUrl(settings.metaBaseUrl);
  if (!base || !settings.webhookToken) return { ok: false, error: "not_configured" };

  const seriesId = Number(msg.seriesId);
  if (!Number.isFinite(seriesId) || seriesId <= 0) {
    return { ok: false, error: "missing_series_id" };
  }

  try {
    const res = await fetch(`${base}/companion/series/${seriesId}/status`, {
      headers: { "X-Webhook-Token": settings.webhookToken },
      credentials: "omit",
    });
    // Une instance antérieure à la route répond 404. Ce n'est pas une panne :
    // la pastille se tait, et le reste du menu continue de fonctionner.
    if (res.status === 404) return { ok: false, error: "unsupported" };
    if (!res.ok) return { ok: false, error: `HTTP ${res.status}` };
    const body = await res.json().catch(() => null);
    if (!body || body.success !== true) return { ok: false, error: "bad_payload" };
    return { ok: true, status: body, badge: badgeFor(body) };
  } catch (e) {
    return { ok: false, error: String(e && e.message ? e.message : e) };
  }
}
