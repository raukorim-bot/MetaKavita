/** Test de connexion et webhook — les deux appels que la page fait à MetaKavita. */
import { loadSettings, normalizeBaseUrl, originFromUrl } from "../storage.js";
import { hasOriginPermission } from "../permissions.js";
import { postWebhook, testConnection as probeConnection } from "../webhook.js";

export async function testConnection(msg) {
  const settings = msg.settings || (await loadSettings());
  const metaOrigin = originFromUrl(normalizeBaseUrl(settings.metaBaseUrl));
  if (metaOrigin && !(await hasOriginPermission(metaOrigin))) {
    return { ok: false, result: { ok: false, reason: "permission" } };
  }
  return { ok: true, result: await probeConnection(settings) };
}

export async function webhook(msg) {
  const settings = await loadSettings();
  try {
    return { ok: true, body: await postWebhook(settings, msg.payload || {}) };
  } catch (e) {
    return {
      ok: false,
      error: String(e && e.message ? e.message : e),
      code: (e && e.code) || (e && e.body && e.body.code),
      status: e && e.status,
    };
  }
}
