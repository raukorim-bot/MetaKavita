import {
  loadSettings,
  saveSettings,
  originFromUrl,
  normalizeBaseUrl,
  isMetaKavitaUrl,
} from "./lib/storage.js";
import { hasOriginPermission, originFromMatchPattern } from "./lib/permissions.js";
import { postWebhook, testConnection } from "./lib/webhook.js";

const WATCH_SCRIPT_ID = "mk-companion-watch";

function stripOrigin(origin) {
  return String(origin || "").replace(/\/+$/, "");
}

/**
 * Cover picker runs as <img> on the Kavita page. Relative display_url
 * (/api/proxy-image?…) would hit Kavita, not Meta — and cross-origin Meta
 * needs ?embed_token= (no cookies / no custom headers on img).
 */
function resolveCompanionCoverDisplayUrl(displayUrl, rawUrl, metaBase, embedToken) {
  let u = String(displayUrl || rawUrl || "").trim();
  if (!u) return "";
  const base = String(metaBase || "").replace(/\/+$/, "");
  if (u.startsWith("/") && base) {
    try {
      const origin = new URL(base).origin;
      const basePath = new URL(base + "/").pathname.replace(/\/+$/, "") || "";
      if (basePath && (u === basePath || u.startsWith(basePath + "/"))) {
        u = origin + u;
      } else {
        u = base + u;
      }
    } catch {
      u = base + u;
    }
  }
  if (!embedToken || u.indexOf("/api/proxy-image") === -1) return u;
  try {
    const parsed = new URL(u);
    if (!parsed.searchParams.has("embed_token")) {
      parsed.searchParams.set("embed_token", embedToken);
    }
    return parsed.toString();
  } catch {
    return u;
  }
}

const IMAGE_BRIDGE_MAX_BYTES = 8 * 1024 * 1024;

function bytesToBase64(bytes) {
  let out = "";
  const step = 0x8000;
  for (let i = 0; i < bytes.length; i += step) {
    out += String.fromCharCode.apply(null, bytes.subarray(i, i + step));
  }
  return btoa(out);
}

async function mintEmbedToken(base, webhookToken, seriesId) {
  try {
    const res = await fetch(`${base}/companion/embed-token`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Webhook-Token": webhookToken,
      },
      body: JSON.stringify({
        seriesId,
        parent_origin: chrome.runtime.getURL("").replace(/\/$/, ""),
      }),
    });
    const body = await res.json().catch(() => ({}));
    return res.ok && body.embed_token ? body.embed_token : "";
  } catch {
    return "";
  }
}

let syncChain = Promise.resolve();

function queueSync(fn) {
  const run = syncChain.then(fn, fn);
  syncChain = run.catch(() => {});
  return run;
}

async function listEnabledKavitaOrigins() {
  const settings = await loadSettings();
  // Same-origin reverse proxies (Kavita + Meta on one host, different paths)
  // share an origin — do not exclude metaOrigin here (issue #34). FABs only
  // mount on Kavita series URLs via watch.js SERIES_RE.
  const unique = [];
  for (const raw of settings.kavitaOrigins || []) {
    const origin = stripOrigin(raw);
    if (!origin) continue;
    if (!(await hasOriginPermission(origin))) continue;
    if (!unique.includes(origin)) unique.push(origin);
  }
  return unique;
}

async function getRegisteredWatch() {
  try {
    const list = await chrome.scripting.getRegisteredContentScripts({
      ids: [WATCH_SCRIPT_ID],
    });
    return list && list.length ? list[0] : null;
  } catch {
    return null;
  }
}

/**
 * Register content scripts for origins that still have host permission.
 * Does NOT shrink stored kavitaOrigins when a permission check fails (U7).
 */
async function syncWatchRegistration() {
  return queueSync(async () => {
    const origins = await listEnabledKavitaOrigins();
    const existing = await getRegisteredWatch();

    if (!origins.length) {
      if (existing) {
        try {
          await chrome.scripting.unregisterContentScripts({ ids: [WATCH_SCRIPT_ID] });
        } catch {
          /* ignore */
        }
      }
      return origins;
    }

    const script = {
      id: WATCH_SCRIPT_ID,
      js: ["content/page-ui.js", "content/watch.js"],
      matches: origins.map((o) => `${o}/*`),
      runAt: "document_idle",
      persistAcrossSessions: true,
    };

    if (existing) {
      await chrome.scripting.updateContentScripts([script]);
    } else {
      try {
        await chrome.scripting.registerContentScripts([script]);
      } catch (e) {
        const msg = String(e && e.message ? e.message : e);
        if (/duplicate script id/i.test(msg)) {
          await chrome.scripting.unregisterContentScripts({ ids: [WATCH_SCRIPT_ID] }).catch(() => {});
          await chrome.scripting.registerContentScripts([script]);
        } else {
          throw e;
        }
      }
    }
    return origins;
  });
}

async function enableKavitaOrigin(
  origin,
  { trustSenderOrigin = false, pageUrl = "" } = {}
) {
  const clean = stripOrigin(origin);
  if (!clean) return null;
  // Content scripts cannot call chrome.permissions; if the message comes from a
  // tab already on this origin, host access is already effective.
  if (!trustSenderOrigin && !(await hasOriginPermission(clean))) return null;
  const settings = await loadSettings();
  // Block only when the tab is actually Meta (path-aware), not merely same origin.
  if (pageUrl && isMetaKavitaUrl(pageUrl, settings.metaBaseUrl)) return null;
  const next = Array.from(new Set([...(settings.kavitaOrigins || []).map(stripOrigin), clean]));
  await saveSettings({ kavitaOrigins: next, pendingEnableOrigin: "" });
  await syncWatchRegistration();
  return clean;
}

async function injectWatchIntoTab(tabId) {
  if (tabId == null) return;
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ["content/page-ui.js", "content/watch.js"],
    });
  } catch {
    /* restricted / gone */
  }
}

async function injectIntoOpenKavitaTabs(origins) {
  const allowed = origins || (await listEnabledKavitaOrigins());
  if (!allowed.length) return;
  let tabs = [];
  try {
    tabs = await chrome.tabs.query({});
  } catch {
    return;
  }
  for (const tab of tabs) {
    if (!tab.id || !tab.url) continue;
    try {
      const origin = stripOrigin(new URL(tab.url).origin);
      if (allowed.includes(origin)) await injectWatchIntoTab(tab.id);
    } catch {
      /* ignore */
    }
  }
}

async function bootstrap() {
  try {
    const origins = await syncWatchRegistration();
    await injectIntoOpenKavitaTabs(origins);
  } catch {
    /* ignore */
  }
}

/** C1: popup may die during permissions.request — finish enable via onAdded. */
chrome.permissions.onAdded.addListener((perms) => {
  (async () => {
    const settings = await loadSettings();
    const metaOrigin = stripOrigin(originFromUrl(normalizeBaseUrl(settings.metaBaseUrl)));
    const pending = stripOrigin(settings.pendingEnableOrigin || "");
    for (const pattern of perms.origins || []) {
      const origin = stripOrigin(originFromMatchPattern(pattern));
      if (!origin) continue;
      // Meta-only grant (Save/Test): do not register as Kavita unless user
      // explicitly pending-enabled this origin (same-host reverse proxy, #34).
      if (origin === metaOrigin && !pending) continue;
      if (pending && origin !== pending) continue;
      const enabled = await enableKavitaOrigin(origin);
      if (enabled) await injectIntoOpenKavitaTabs([enabled]);
    }
    // Meta host grant: just sync (no Kavita inject)
    try {
      await syncWatchRegistration();
    } catch {
      /* ignore */
    }
  })();
});

chrome.runtime.onInstalled.addListener(() => {
  bootstrap();
});

chrome.runtime.onStartup.addListener(() => {
  bootstrap();
});

bootstrap();

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete" || !tab?.url) return;
  (async () => {
    try {
      const origin = stripOrigin(new URL(tab.url).origin);
      const allowed = await listEnabledKavitaOrigins();
      if (!allowed.includes(origin)) return;
      await injectWatchIntoTab(tabId);
    } catch {
      /* ignore */
    }
  })();
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    try {
      if (!msg || !msg.type) {
        sendResponse({ ok: false });
        return;
      }
      if (msg.type === "getSettings") {
        sendResponse({ ok: true, settings: await loadSettings() });
        return;
      }
      if (msg.type === "saveSettings") {
        // Persist first so popup death after permission grant doesn't lose values (C1).
        const next = await saveSettings(msg.settings || {});
        const metaOrigin = originFromUrl(next.metaBaseUrl);
        let permissionOk = true;
        if (metaOrigin) {
          permissionOk = await hasOriginPermission(metaOrigin);
        }
        try {
          await syncWatchRegistration();
        } catch {
          /* ignore */
        }
        sendResponse({
          ok: true,
          settings: await loadSettings(),
          permissionOk,
          error: permissionOk ? null : "permission_denied_meta",
        });
        return;
      }
      if (msg.type === "pendingEnable") {
        const origin = stripOrigin(msg.origin || "");
        await saveSettings({ pendingEnableOrigin: origin });
        sendResponse({ ok: true, origin });
        return;
      }
      if (msg.type === "hasHostPermission") {
        const origin = stripOrigin(msg.origin || "");
        sendResponse({
          ok: true,
          granted: origin ? await hasOriginPermission(origin) : false,
        });
        return;
      }
      if (msg.type === "requestHostPermission") {
        // Prefer extension pages for the prompt; SW request may fail without gesture.
        const origin = stripOrigin(msg.origin || "");
        if (!origin) {
          sendResponse({ ok: false, granted: false, error: "no_origin" });
          return;
        }
        if (await hasOriginPermission(origin)) {
          sendResponse({ ok: true, granted: true });
          return;
        }
        try {
          const granted = await chrome.permissions.request({
            origins: [`${origin}/*`],
          });
          sendResponse({ ok: true, granted: !!granted });
        } catch (e) {
          sendResponse({
            ok: false,
            granted: false,
            error: String(e && e.message ? e.message : e),
            need_ui: true,
          });
        }
        return;
      }
      if (msg.type === "enableKavitaOrigin") {
        const origin = msg.origin || (sender.tab && new URL(sender.tab.url).origin);
        if (!origin) {
          sendResponse({ ok: false, error: "no_origin" });
          return;
        }
        const clean = stripOrigin(origin);
        let trustSenderOrigin = false;
        let pageUrl = typeof msg.pageUrl === "string" ? msg.pageUrl : "";
        try {
          if (sender.tab && sender.tab.url) {
            trustSenderOrigin = stripOrigin(new URL(sender.tab.url).origin) === clean;
            if (!pageUrl) pageUrl = sender.tab.url;
          }
        } catch {
          trustSenderOrigin = false;
        }
        await saveSettings({ pendingEnableOrigin: clean });
        const enabled = await enableKavitaOrigin(clean, {
          trustSenderOrigin,
          pageUrl,
        });
        if (!enabled) {
          sendResponse({ ok: false, error: "permission_denied" });
          return;
        }
        const tabId = msg.tabId != null ? msg.tabId : sender.tab && sender.tab.id;
        await injectWatchIntoTab(tabId);
        await injectIntoOpenKavitaTabs([enabled]);
        sendResponse({ ok: true, origin: enabled });
        return;
      }
      if (msg.type === "testConnection") {
        const settings = msg.settings || (await loadSettings());
        const metaOrigin = originFromUrl(normalizeBaseUrl(settings.metaBaseUrl));
        if (metaOrigin && !(await hasOriginPermission(metaOrigin))) {
          sendResponse({ ok: false, result: { ok: false, reason: "permission" } });
          return;
        }
        sendResponse({ ok: true, result: await testConnection(settings) });
        return;
      }
      if (msg.type === "webhook") {
        const settings = await loadSettings();
        try {
          const body = await postWebhook(settings, msg.payload || {});
          sendResponse({ ok: true, body });
        } catch (e) {
          sendResponse({
            ok: false,
            error: String(e && e.message ? e.message : e),
            code: (e && e.code) || (e && e.body && e.body.code),
            status: e && e.status,
          });
        }
        return;
      }
      if (msg.type === "embedToken") {
        const settings = await loadSettings();
        const base = normalizeBaseUrl(settings.metaBaseUrl);
        if (!base || !settings.webhookToken) {
          sendResponse({ ok: false, error: "not_configured" });
          return;
        }
        const seriesId = Number(msg.seriesId);
        if (!Number.isFinite(seriesId) || seriesId <= 0) {
          sendResponse({ ok: false, error: "missing_series_id" });
          return;
        }
        try {
          const res = await fetch(`${base}/companion/embed-token`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Webhook-Token": settings.webhookToken,
            },
            body: JSON.stringify({
              seriesId,
              parent_origin: msg.parentOrigin || chrome.runtime.getURL("").replace(/\/$/, ""),
            }),
          });
          const body = await res.json().catch(() => ({}));
          if (!res.ok) {
            sendResponse({
              ok: false,
              error: (body && body.message) || `HTTP ${res.status}`,
              code: body && body.code,
              status: res.status,
            });
            return;
          }
          sendResponse({ ok: true, embed_token: body.embed_token, series_id: body.series_id });
        } catch (e) {
          sendResponse({ ok: false, error: String(e && e.message ? e.message : e) });
        }
        return;
      }
      // An HTTPS Kavita page cannot render http://meta/api/proxy-image in an
      // <img> (mixed content). Service worker fetches are exempt, so the bytes
      // come back as a data: URL the page can always display.
      if (msg.type === "fetchImageData") {
        const settings = await loadSettings();
        const base = normalizeBaseUrl(settings.metaBaseUrl);
        if (!base || !settings.webhookToken) {
          sendResponse({ ok: false, error: "not_configured" });
          return;
        }
        let target;
        try {
          target = new URL(String(msg.url || "").trim(), base + "/");
        } catch {
          sendResponse({ ok: false, error: "bad_url" });
          return;
        }
        const metaOrigin = originFromUrl(base);
        if (!metaOrigin || originFromUrl(target.toString()) !== metaOrigin) {
          sendResponse({ ok: false, error: "not_meta_url" });
          return;
        }
        const headers = {};
        const seriesId = Number(msg.seriesId);
        if (Number.isFinite(seriesId) && seriesId > 0) {
          const token = await mintEmbedToken(base, settings.webhookToken, seriesId);
          if (token) {
            headers["X-Companion-Embed-Token"] = token;
            target.searchParams.delete("embed_token");
          }
        }
        try {
          const res = await fetch(target.toString(), {
            headers,
            credentials: "omit",
          });
          // A MetaKavita that predates the embed-token allowance on
          // /api/proxy-image answers 302 → /login, which fetch follows into an
          // HTML page. Name that failure instead of reporting "not an image".
          if (/\/login\b/i.test(res.url || "")) {
            sendResponse({ ok: false, error: "meta_login_required" });
            return;
          }
          if (!res.ok) {
            sendResponse({ ok: false, error: `HTTP ${res.status}` });
            return;
          }
          const mime = (res.headers.get("Content-Type") || "")
            .split(";")[0]
            .trim()
            .toLowerCase();
          if (mime && !mime.startsWith("image/")) {
            sendResponse({ ok: false, error: "not_an_image" });
            return;
          }
          const buf = await res.arrayBuffer();
          if (!buf.byteLength || buf.byteLength > IMAGE_BRIDGE_MAX_BYTES) {
            sendResponse({ ok: false, error: "bad_size" });
            return;
          }
          const b64 = bytesToBase64(new Uint8Array(buf));
          sendResponse({
            ok: true,
            dataUrl: `data:${mime || "image/jpeg"};base64,${b64}`,
          });
        } catch (e) {
          sendResponse({ ok: false, error: String(e && e.message ? e.message : e) });
        }
        return;
      }
      if (msg.type === "fetchCovers" || msg.type === "applyCover") {
        const settings = await loadSettings();
        const base = normalizeBaseUrl(settings.metaBaseUrl);
        if (!base || !settings.webhookToken) {
          sendResponse({ ok: false, error: "not_configured" });
          return;
        }
        const seriesId = Number(msg.seriesId);
        if (!Number.isFinite(seriesId) || seriesId <= 0) {
          sendResponse({ ok: false, error: "missing_series_id" });
          return;
        }
        const parentOrigin = chrome.runtime.getURL("").replace(/\/$/, "");
        let embedToken = "";
        try {
          const tokRes = await fetch(`${base}/companion/embed-token`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Webhook-Token": settings.webhookToken,
            },
            body: JSON.stringify({ seriesId, parent_origin: parentOrigin }),
          });
          const tokBody = await tokRes.json().catch(() => ({}));
          if (tokRes.ok && tokBody.embed_token) embedToken = tokBody.embed_token;
        } catch {
          /* ignore */
        }
        if (!embedToken) {
          sendResponse({ ok: false, error: "embed_token_failed" });
          return;
        }
        try {
          if (msg.type === "fetchCovers") {
            const q = encodeURIComponent(String(msg.seriesName || ""));
            const res = await fetch(
              `${base}/api/series/${seriesId}/covers?series_name=${q}`,
              { headers: { "X-Companion-Embed-Token": embedToken } }
            );
            const body = await res.json().catch(() => ({}));
            if (!res.ok) {
              sendResponse({
                ok: false,
                error: (body && (body.msg || body.message)) || `HTTP ${res.status}`,
              });
              return;
            }
            const covers = (body.covers || []).map((c) => {
              if (!c || typeof c !== "object") return c;
              const display = resolveCompanionCoverDisplayUrl(
                c.display_url,
                c.url,
                base,
                embedToken
              );
              return { ...c, display_url: display || c.display_url || c.url || "" };
            });
            sendResponse({ ok: true, covers });
            return;
          }
          const res = await fetch(`${base}/api/series/${seriesId}/update-cover`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Companion-Embed-Token": embedToken,
            },
            body: JSON.stringify({ cover_url: msg.coverUrl }),
          });
          const body = await res.json().catch(() => ({}));
          if (!res.ok || !body.success) {
            sendResponse({
              ok: false,
              error: (body && body.msg) || `HTTP ${res.status}`,
            });
            return;
          }
          sendResponse({ ok: true });
        } catch (e) {
          sendResponse({ ok: false, error: String(e && e.message ? e.message : e) });
        }
        return;
      }
      sendResponse({ ok: false, error: "unknown" });
    } catch (e) {
      try {
        sendResponse({ ok: false, error: String(e && e.message ? e.message : e) });
      } catch {
        /* channel closed */
      }
    }
  })();
  return true;
});
