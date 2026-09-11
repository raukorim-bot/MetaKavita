/**
 * Table des messages acceptés par le service worker, et son répartiteur.
 *
 * Un handler REND sa réponse ; il ne reçoit pas `sendResponse`. C'est ce qui
 * le rend vérifiable hors du navigateur — un `sendResponse` en paramètre
 * imposerait de simuler le canal de messages pour observer quoi que ce soit.
 */
import { getSettings, saveSettingsHandler, pendingEnable } from "./settings.js";
import { hasHostPermission, requestHostPermission } from "./permissions.js";
import { enableKavitaOrigin } from "./sites.js";
import { testConnection, webhook } from "./connection.js";
import { embedToken } from "./embed.js";
import { fetchCovers, applyCover, fetchImageData } from "./covers.js";
import { uiBootstrap, urlInfo } from "./ui.js";
import { seriesStatus } from "./status.js";

export const HANDLERS = {
  uiBootstrap,
  urlInfo,
  seriesStatus,
  getSettings,
  saveSettings: saveSettingsHandler,
  pendingEnable,
  hasHostPermission,
  requestHostPermission,
  enableKavitaOrigin,
  testConnection,
  webhook,
  embedToken,
  fetchImageData,
  fetchCovers,
  applyCover,
};

/**
 * ⚠️ Les deux refus ne se confondent pas, et l'UI s'en sert : un message sans
 * `type` rend `{ok:false}` NU (un appel malformé, rien à dire), un type inconnu
 * rend `{ok:false, error:"unknown"}` (l'extension et la page ont divergé).
 */
export async function dispatch(msg, sender = {}) {
  if (!msg || !msg.type) return { ok: false };
  const handler = Object.prototype.hasOwnProperty.call(HANDLERS, msg.type)
    ? HANDLERS[msg.type]
    : null;
  if (!handler) return { ok: false, error: "unknown" };
  try {
    return await handler(msg, sender);
  } catch (e) {
    return { ok: false, error: String(e && e.message ? e.message : e) };
  }
}
