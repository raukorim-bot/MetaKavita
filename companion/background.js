import { loadSettings, saveSettings, originFromUrl, normalizeBaseUrl } from "./lib/storage.js";
import { hasOriginPermission, originFromMatchPattern } from "./lib/permissions.js";
import { postWebhook, testConnection } from "./lib/webhook.js";

const WATCH_SCRIPT_ID = "mk-companion-watch";

function stripOrigin(origin) {
  return String(origin || "").replace(/\/+$/, "");
}

let syncChain = Promise.resolve();

function queueSync(fn) {
  const run = syncChain.then(fn, fn);
  syncChain = run.catch(() => {});
  return run;
}

async function listEnabledKavitaOrigins() {
  const settings = await loadSettings();
  const metaOrigin = stripOrigin(originFromUrl(normalizeBaseUrl(settings.metaBaseUrl)));
  const unique = [];
  for (const raw of settings.kavitaOrigins || []) {
    const origin = stripOrigin(raw);
    if (!origin || origin === metaOrigin) continue;
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

async function enableKavitaOrigin(origin, { trustSenderOrigin = false } = {}) {
  const clean = stripOrigin(origin);
  if (!clean) return null;
  // Content scripts cannot call chrome.permissions; if the message comes from a
  // tab already on this origin, host access is already effective.
  if (!trustSenderOrigin && !(await hasOriginPermission(clean))) return null;
  const settings = await loadSettings();
  const metaOrigin = stripOrigin(originFromUrl(normalizeBaseUrl(settings.metaBaseUrl)));
  if (metaOrigin && clean === metaOrigin) return null;
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
      if (!origin || origin === metaOrigin) continue;
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
        try {
          if (sender.tab && sender.tab.url) {
            trustSenderOrigin = stripOrigin(new URL(sender.tab.url).origin) === clean;
          }
        } catch {
          trustSenderOrigin = false;
        }
        await saveSettings({ pendingEnableOrigin: clean });
        const enabled = await enableKavitaOrigin(clean, { trustSenderOrigin });
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
            sendResponse({ ok: true, covers: body.covers || [] });
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
