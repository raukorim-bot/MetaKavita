/**
 * Cover picker : recherche et application.
 *
 * Les deux restent dans le même module — même préambule, même échec
 * `embed_token_failed` avant tout appel réseau.
 */
import { loadSettings, normalizeBaseUrl } from "../storage.js";
import { getEmbedToken } from "../embed-token.js";
import { resolveCoverDisplayUrl } from "../cover-url.js";
import { fetchImageAsDataUrl } from "../image-bridge.js";

/** Préambule partagé : configuration, périmètre série, jeton. */
async function scoped(msg) {
  const settings = await loadSettings();
  const base = normalizeBaseUrl(settings.metaBaseUrl);
  if (!base || !settings.webhookToken) return { error: { ok: false, error: "not_configured" } };

  const seriesId = Number(msg.seriesId);
  if (!Number.isFinite(seriesId) || seriesId <= 0) {
    return { error: { ok: false, error: "missing_series_id" } };
  }

  const embedToken = await getEmbedToken(base, settings.webhookToken, seriesId);
  if (!embedToken) return { error: { ok: false, error: "embed_token_failed" } };

  return { base, seriesId, embedToken };
}

export async function fetchCovers(msg) {
  const ctx = await scoped(msg);
  if (ctx.error) return ctx.error;
  const { base, seriesId, embedToken } = ctx;

  try {
    const q = encodeURIComponent(String(msg.seriesName || ""));
    const res = await fetch(`${base}/api/series/${seriesId}/covers?series_name=${q}`, {
      headers: { "X-Companion-Embed-Token": embedToken },
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      return { ok: false, error: (body && (body.msg || body.message)) || `HTTP ${res.status}` };
    }
    const covers = (body.covers || []).map((c) => {
      if (!c || typeof c !== "object") return c;
      const display = resolveCoverDisplayUrl(c.display_url, c.url, base);
      return { ...c, display_url: display || c.display_url || c.url || "" };
    });
    return { ok: true, covers };
  } catch (e) {
    return { ok: false, error: String(e && e.message ? e.message : e) };
  }
}

export async function applyCover(msg) {
  const ctx = await scoped(msg);
  if (ctx.error) return ctx.error;
  const { base, seriesId, embedToken } = ctx;

  try {
    const res = await fetch(`${base}/api/series/${seriesId}/update-cover`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Companion-Embed-Token": embedToken,
      },
      body: JSON.stringify({ cover_url: msg.coverUrl, series_name: msg.seriesName || "" }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok || !body.success) {
      return { ok: false, error: (body && body.msg) || `HTTP ${res.status}` };
    }
    return { ok: true };
  } catch (e) {
    return { ok: false, error: String(e && e.message ? e.message : e) };
  }
}

export async function fetchImageData(msg) {
  return fetchImageAsDataUrl(await loadSettings(), { url: msg.url, seriesId: msg.seriesId });
}
