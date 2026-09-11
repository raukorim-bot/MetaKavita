/**
 * Origines Kavita activées : mémorisation, enregistrement des content scripts,
 * injection dans les onglets déjà ouverts.
 */
import { loadSettings, saveSettings, isMetaKavitaUrl } from "./storage.js";
import { hasOriginPermission } from "./permissions.js";
import { WATCH_FILES, WATCH_SCRIPT_ID } from "./watch-files.js";

export function stripOrigin(origin) {
  return String(origin || "").replace(/\/+$/, "");
}

let syncChain = Promise.resolve();

function queueSync(fn) {
  const run = syncChain.then(fn, fn);
  syncChain = run.catch(() => {});
  return run;
}

export async function listEnabledKavitaOrigins() {
  const settings = await loadSettings();
  // Un reverse proxy peut servir Kavita et Meta sur la même origine, à des
  // chemins différents — ne pas exclure metaOrigin ici (issue #34). Les FABs ne
  // se montent que sur une URL de fiche série, via SERIES_RE dans watch.js.
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
 * Enregistre les content scripts pour les origines qui ont encore la
 * permission d'hôte. Ne RÉTRÉCIT PAS `kavitaOrigins` quand un contrôle de
 * permission échoue (U7) : une permission illisible n'est pas une révocation.
 */
export async function syncWatchRegistration() {
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
      js: WATCH_FILES,
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

export async function enableKavitaOrigin(origin, { trustSenderOrigin = false, pageUrl = "" } = {}) {
  const clean = stripOrigin(origin);
  if (!clean) return null;
  // Les content scripts ne peuvent pas appeler chrome.permissions ; si le
  // message vient d'un onglet déjà sur cette origine, l'accès est effectif.
  if (!trustSenderOrigin && !(await hasOriginPermission(clean))) return null;
  const settings = await loadSettings();
  // Ne bloquer que si l'onglet EST MetaKavita (au chemin près), pas simplement
  // s'il partage son origine.
  if (pageUrl && isMetaKavitaUrl(pageUrl, settings.metaBaseUrl)) return null;
  const next = Array.from(new Set([...(settings.kavitaOrigins || []).map(stripOrigin), clean]));
  await saveSettings({ kavitaOrigins: next, pendingEnableOrigin: "" });
  await syncWatchRegistration();
  return clean;
}

export async function injectWatchIntoTab(tabId) {
  if (tabId == null) return;
  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: WATCH_FILES });
  } catch {
    /* restricted / gone */
  }
}

export async function injectIntoOpenKavitaTabs(origins) {
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

export async function bootstrap() {
  try {
    const origins = await syncWatchRegistration();
    await injectIntoOpenKavitaTabs(origins);
  } catch {
    /* ignore */
  }
}
