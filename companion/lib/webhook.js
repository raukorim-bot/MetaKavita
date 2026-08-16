import { isConfigured, normalizeBaseUrl } from "./storage.js";

function truthyResponse(res) {
  return { ok: res.ok, status: res.status, body: null };
}

export async function testConnection(settings) {
  const base = normalizeBaseUrl(settings.metaBaseUrl);
  const token = String(settings.webhookToken || "").trim();
  if (!base) return { ok: false, reason: "no_url" };
  if (!token) return { ok: false, reason: "no_token" };
  try {
    const health = await fetch(`${base}/healthz`, { method: "GET" });
    if (!health.ok) return { ok: false, reason: "healthz", status: health.status };
    const probe = await fetch(`${base}/webhook`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Webhook-Token": token,
      },
      // Server accepts probe without seriesId (no warning log).
      body: JSON.stringify({ probe: true }),
    });
    if (probe.status === 401) return { ok: false, reason: "token", status: 401 };
    if (probe.ok) return { ok: true, reason: "probe" };
    // Legacy servers: empty-body 400 still means token OK
    if (probe.status === 400) return { ok: true, reason: "probe_legacy" };
    return { ok: false, reason: "unexpected", status: probe.status };
  } catch (e) {
    return { ok: false, reason: "network", error: String(e && e.message ? e.message : e) };
  }
}

export async function postWebhook(settings, payload) {
  if (!isConfigured(settings)) {
    const err = new Error("not_configured");
    err.code = "not_configured";
    throw err;
  }
  const sid = payload && payload.seriesId;
  if (sid == null || sid === "" || Number(sid) !== Number(sid) || Number(sid) <= 0) {
    const err = new Error("missing_series_id");
    err.code = "missing_series_id";
    throw err;
  }
  const body = {
    ...payload,
    seriesId: Number(sid),
  };
  const base = normalizeBaseUrl(settings.metaBaseUrl);
  const res = await fetch(`${base}/webhook`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Webhook-Token": settings.webhookToken,
    },
    body: JSON.stringify(body),
  });
  let parsed = null;
  try {
    parsed = await res.json();
  } catch {
    parsed = null;
  }
  if (!res.ok) {
    const err = new Error((parsed && parsed.message) || `HTTP ${res.status}`);
    err.status = res.status;
    err.body = parsed;
    err.code = parsed && parsed.code;
    throw err;
  }
  return parsed;
}

export { truthyResponse };
