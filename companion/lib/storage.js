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
  // U9: accept host:port without scheme (LAN → http)
  if (!/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(u)) {
    const host = u.split("/")[0];
    const isLocal =
      /^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/i.test(host) ||
      /^\d{1,3}(\.\d{1,3}){3}(:\d+)?$/i.test(host);
    u = (isLocal ? "http://" : "https://") + u;
  }
  u = u.replace(/\/+$/, "");
  return u;
}

export function originFromUrl(url) {
  try {
    return new URL(normalizeBaseUrl(url) || url).origin;
  } catch {
    return "";
  }
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
