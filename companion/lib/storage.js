/** @typedef {{ metaBaseUrl: string, webhookToken: string, showActionFabs: boolean, cacheBustOnConfirm: boolean, uiLang: 'auto'|'fr'|'en', kavitaOrigins: string[], pendingEnableOrigin: string }} CompanionSettings */

const DEFAULTS = {
  metaBaseUrl: "",
  webhookToken: "",
  showActionFabs: true,
  cacheBustOnConfirm: true,
  uiLang: "auto",
  kavitaOrigins: [],
  pendingEnableOrigin: "",
};

export function normalizeBaseUrl(url) {
  let u = String(url || "").trim();
  if (!u) return "";
  // U9: accept host:port without scheme (LAN → http).
  // Only http(s):// counts as a scheme here. Testing for "letters followed by
  // a colon" made "localhost:5011" and "nas:5011" parse as the schemes
  // "localhost:" and "nas:" — origin null, and the LAN fallback below never
  // reached the very hosts it was written for.
  if (!/^https?:\/\//i.test(u)) {
    const host = u.replace(/^\/+/, "").split("/")[0];
    const hostname = host.replace(/:\d+$/, "");
    const isLocal =
      /^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/i.test(hostname) ||
      /^\d{1,3}(\.\d{1,3}){3}$/.test(hostname) ||
      // A bare name with no dot is a LAN host (nas, metakavita), never a
      // public domain — and those are served over plain http far more often.
      !hostname.includes(".");
    u = (isLocal ? "http://" : "https://") + u.replace(/^\/+/, "");
  }
  // Config shows the webhook URL (`…/webhook?token=`). Pasted here it must
  // become the instance root, or Test hits `/webhook/healthz` and fails.
  u = u.split("#")[0];
  const q = u.indexOf("?");
  if (q !== -1) u = u.slice(0, q);
  u = u.replace(/\/+$/, "");
  u = u.replace(/\/webhook$/i, "");
  return u;
}

/** Token from a pasted Meta webhook URL (`?token=`). Empty if none. */
export function tokenFromPastedUrl(url) {
  try {
    const m = String(url || "").trim().match(/[?&]token=([^&]+)/i);
    return m ? decodeURIComponent(m[1].replace(/\+/g, " ")) : "";
  } catch {
    return "";
  }
}

export function originFromUrl(url) {
  try {
    return new URL(normalizeBaseUrl(url) || url).origin;
  } catch {
    return "";
  }
}

/**
 * True when pageUrl is the MetaKavita app (same origin + under metaBaseUrl path).
 * Supports reverse-proxy setups where Kavita and Meta share a host
 * (e.g. https://host/kavita vs https://host/metakavita) — origin equality alone
 * must not treat Kavita as Meta (issue #34).
 *
 * When Meta is configured at the host root (no path), only non-series pages on
 * that origin are treated as Meta so a same-origin /library/…/series/… Kavita
 * tab can still be enabled.
 */
export function isMetaKavitaUrl(pageUrl, metaBaseUrl) {
  const meta = normalizeBaseUrl(metaBaseUrl);
  if (!meta || !pageUrl) return false;
  let page;
  let base;
  try {
    page = new URL(String(pageUrl));
    base = new URL(meta);
  } catch {
    return false;
  }
  if (page.origin !== base.origin) return false;

  const metaPath = base.pathname.replace(/\/+$/, "") || "";
  if (!metaPath) {
    return !/\/library\/\d+\/series\/\d+\/?$/i.test(page.pathname || "");
  }
  const pagePath = page.pathname || "/";
  return pagePath === metaPath || pagePath.startsWith(`${metaPath}/`);
}

export async function loadSettings() {
  const data = await chrome.storage.local.get(Object.keys(DEFAULTS));
  return { ...DEFAULTS, ...data };
}

export async function saveSettings(partial) {
  const next = { ...(await loadSettings()), ...partial };
  if ("metaBaseUrl" in partial) {
    next.metaBaseUrl = normalizeBaseUrl(partial.metaBaseUrl);
  }
  await chrome.storage.local.set(next);
  return next;
}

export function isConfigured(settings) {
  return !!(settings.metaBaseUrl && settings.webhookToken);
}
