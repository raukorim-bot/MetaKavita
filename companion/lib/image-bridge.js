/**
 * Pont d'images : le service worker va chercher une image MetaKavita et la
 * rend en `data:` URL à la page Kavita.
 *
 * Deux raisons, pas une :
 *
 * 1. Un aperçu proxifié exige des identifiants MetaKavita, et un `<img>` ne
 *    porte ni cookie (cross-site) ni en-tête. Mettre le jeton d'embed dans
 *    l'URL marchait — et livrait à tout script de la page un jeton bon pour
 *    toutes les routes de review de la série.
 * 2. Une image `http://` est bloquée comme contenu mixte sur une page Kavita
 *    `https://`. Les requêtes du service worker, elles, y échappent.
 */
import { normalizeBaseUrl, originFromUrl } from "./storage.js";
import { getEmbedToken } from "./embed-token.js";

const IMAGE_BRIDGE_MAX_BYTES = 8 * 1024 * 1024;

function bytesToBase64(bytes) {
  let out = "";
  const step = 0x8000;
  for (let i = 0; i < bytes.length; i += step) {
    out += String.fromCharCode.apply(null, bytes.subarray(i, i + step));
  }
  return btoa(out);
}

/**
 * @param {{metaBaseUrl: string, webhookToken: string}} settings
 * @param {{url: string, seriesId?: number|string}} params
 * @returns {Promise<{ok: boolean, dataUrl?: string, error?: string}>}
 */
export async function fetchImageAsDataUrl(settings, { url, seriesId } = {}) {
  const base = normalizeBaseUrl(settings.metaBaseUrl);
  if (!base || !settings.webhookToken) return { ok: false, error: "not_configured" };

  let target;
  try {
    target = new URL(String(url || "").trim(), base + "/");
  } catch {
    return { ok: false, error: "bad_url" };
  }
  const metaOrigin = originFromUrl(base);
  if (!metaOrigin || originFromUrl(target.toString()) !== metaOrigin) {
    return { ok: false, error: "not_meta_url" };
  }

  const headers = {};
  const sid = Number(seriesId);
  if (Number.isFinite(sid) && sid > 0) {
    const token = await getEmbedToken(base, settings.webhookToken, sid);
    if (token) headers["X-Companion-Embed-Token"] = token;
  }
  // Jamais dans l'URL — elle finirait dans un `<img src>` que la page lit. Il
  // voyage en en-tête, ci-dessus.
  target.searchParams.delete("embed_token");

  try {
    const res = await fetch(target.toString(), { headers, credentials: "omit" });
    // Un MetaKavita antérieur à l'acceptation du jeton d'embed sur
    // /api/proxy-image répond 302 vers /login, que fetch suit jusqu'à une page
    // HTML. Nommer cet échec plutôt que d'annoncer « pas une image ».
    if (/\/login\b/i.test(res.url || "")) return { ok: false, error: "meta_login_required" };
    if (!res.ok) return { ok: false, error: `HTTP ${res.status}` };

    const mime = (res.headers.get("Content-Type") || "").split(";")[0].trim().toLowerCase();
    if (mime && !mime.startsWith("image/")) return { ok: false, error: "not_an_image" };

    const buf = await res.arrayBuffer();
    if (!buf.byteLength || buf.byteLength > IMAGE_BRIDGE_MAX_BYTES) {
      return { ok: false, error: "bad_size" };
    }
    const b64 = bytesToBase64(new Uint8Array(buf));
    return { ok: true, dataUrl: `data:${mime || "image/jpeg"};base64,${b64}` };
  } catch (e) {
    return { ok: false, error: String(e && e.message ? e.message : e) };
  }
}
