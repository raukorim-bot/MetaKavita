/** Host permission helpers — request() must run in a user-gesture context (popup/options/overlay), not the service worker. */

export function originPattern(origin) {
  if (!origin) return "";
  const o = String(origin).replace(/\/+$/, "");
  return `${o}/*`;
}

export function originFromMatchPattern(pattern) {
  try {
    // http://host:port/* → http://host:port
    const p = String(pattern || "").replace(/\/\*$/, "").replace(/\/$/, "");
    return new URL(p).origin;
  } catch {
    return "";
  }
}

export async function hasOriginPermission(origin) {
  const pattern = originPattern(origin);
  if (!pattern || !chrome.permissions?.contains) return false;
  return chrome.permissions.contains({ origins: [pattern] });
}

/**
 * Prompt the user for optional host access. Must be called from a click/key handler.
 * @returns {Promise<boolean>}
 */
export async function requestOriginPermission(origin) {
  const pattern = originPattern(origin);
  if (!pattern) return false;
  if (await hasOriginPermission(origin)) return true;
  try {
    return await chrome.permissions.request({ origins: [pattern] });
  } catch {
    return false;
  }
}
