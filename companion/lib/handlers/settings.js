/** Réglages Companion : lecture, écriture, intention d'activation. */
import { loadSettings, saveSettings, originFromUrl } from "../storage.js";
import { hasOriginPermission } from "../permissions.js";
import { forgetEmbedTokens } from "../embed-token.js";
import { stripOrigin, syncWatchRegistration } from "../origins.js";

export async function getSettings() {
  return { ok: true, settings: await loadSettings() };
}

export async function saveSettingsHandler(msg) {
  // Persister D'ABORD : Chrome ferme la popup quand la demande de permission
  // s'affiche, ce qui tuerait un enregistrement qui viendrait après (C1).
  const next = await saveSettings(msg.settings || {});
  // Une nouvelle adresse ou un nouveau jeton webhook invalide ce qu'on détient.
  forgetEmbedTokens();
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
  return {
    ok: true,
    settings: await loadSettings(),
    permissionOk,
    error: permissionOk ? null : "permission_denied_meta",
  };
}

export async function pendingEnable(msg) {
  const origin = stripOrigin(msg.origin || "");
  await saveSettings({ pendingEnableOrigin: origin });
  return { ok: true, origin };
}
