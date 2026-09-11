/** Activation d'un site Kavita depuis la page ou depuis la popup. */
import { saveSettings } from "../storage.js";
import {
  stripOrigin,
  enableKavitaOrigin as persistKavitaOrigin,
  injectWatchIntoTab,
  injectIntoOpenKavitaTabs,
} from "../origins.js";

export async function enableKavitaOrigin(msg, sender = {}) {
  const origin = msg.origin || (sender.tab && new URL(sender.tab.url).origin);
  if (!origin) return { ok: false, error: "no_origin" };

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
  const enabled = await persistKavitaOrigin(clean, { trustSenderOrigin, pageUrl });
  if (!enabled) return { ok: false, error: "permission_denied" };

  const tabId = msg.tabId != null ? msg.tabId : sender.tab && sender.tab.id;
  await injectWatchIntoTab(tabId);
  await injectIntoOpenKavitaTabs([enabled]);
  return { ok: true, origin: enabled };
}
