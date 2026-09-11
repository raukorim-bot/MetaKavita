/**
 * Permissions d'hôte, demandées depuis le service worker.
 *
 * `chrome.permissions` n'existe pas dans un content script : la page passe
 * forcément par ici. La demande, elle, réussit mieux depuis une page
 * d'extension (popup / options), qui a une activation utilisateur — d'où le
 * `need_ui` renvoyé en cas d'échec, qui renvoie l'utilisateur vers la popup.
 */
import { hasOriginPermission } from "../permissions.js";
import { stripOrigin } from "../origins.js";

export async function hasHostPermission(msg) {
  const origin = stripOrigin(msg.origin || "");
  return { ok: true, granted: origin ? await hasOriginPermission(origin) : false };
}

export async function requestHostPermission(msg) {
  const origin = stripOrigin(msg.origin || "");
  if (!origin) return { ok: false, granted: false, error: "no_origin" };
  if (await hasOriginPermission(origin)) return { ok: true, granted: true };
  try {
    const granted = await chrome.permissions.request({ origins: [`${origin}/*`] });
    return { ok: true, granted: !!granted };
  } catch (e) {
    return {
      ok: false,
      granted: false,
      error: String(e && e.message ? e.message : e),
      need_ui: true,
    };
  }
}
