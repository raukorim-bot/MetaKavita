/**
 * Service worker : cycle de vie et répartition des messages.
 *
 * Point d'entrée volontairement mince. Il enregistre des écouteurs et amorce
 * au chargement — donc il n'est pas importable par un test. Toute la logique
 * vit sous `lib/`, où elle se charge à froid : c'est la raison du découpage.
 */
import { loadSettings, originFromUrl, normalizeBaseUrl } from "./lib/storage.js";
import { originFromMatchPattern } from "./lib/permissions.js";
import {
  stripOrigin,
  listEnabledKavitaOrigins,
  syncWatchRegistration,
  enableKavitaOrigin,
  injectWatchIntoTab,
  injectIntoOpenKavitaTabs,
  bootstrap,
} from "./lib/origins.js";
import { dispatch } from "./lib/handlers/index.js";

/** C1 : la popup peut mourir pendant permissions.request — finir via onAdded. */
chrome.permissions.onAdded.addListener((perms) => {
  (async () => {
    const settings = await loadSettings();
    const metaOrigin = stripOrigin(originFromUrl(normalizeBaseUrl(settings.metaBaseUrl)));
    const pending = stripOrigin(settings.pendingEnableOrigin || "");
    for (const pattern of perms.origins || []) {
      const origin = stripOrigin(originFromMatchPattern(pattern));
      if (!origin) continue;
      // Permission accordée pour Meta seul (Enregistrer / Tester) : ne pas
      // l'enregistrer comme un site Kavita, sauf si l'utilisateur a
      // explicitement demandé l'activation de cette origine (reverse proxy #34).
      if (origin === metaOrigin && !pending) continue;
      if (pending && origin !== pending) continue;
      const enabled = await enableKavitaOrigin(origin);
      if (enabled) await injectIntoOpenKavitaTabs([enabled]);
    }
    // Permission d'hôte Meta : resynchroniser seulement, sans injecter.
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
  dispatch(msg, sender).then(sendResponse, () => sendResponse({ ok: false, error: "internal" }));
  return true;
});
