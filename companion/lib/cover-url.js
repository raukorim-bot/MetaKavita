/**
 * Résolution de l'URL d'aperçu d'une couverture, pour le cover picker.
 *
 * Module pur : ni `chrome`, ni `fetch`, ni état. C'est ce qui le rend
 * vérifiable à froid par `companion/tests/cover-url.test.mjs`.
 */

/**
 * Le cover picker rend ces URL en `<img>` sur la page Kavita. Une
 * `display_url` relative (`/api/proxy-image?…`) frapperait donc Kavita et non
 * MetaKavita : il faut l'absolutiser.
 *
 * Le jeton d'embed, lui, reste délibérément HORS de l'URL : un `<img src>` est
 * du DOM nu que n'importe quel script de la page Kavita peut lire, et ce jeton
 * ouvre toutes les routes de review de sa série. Les aperçus proxifiés passent
 * par `fetchImageAsDataUrl`, qui l'envoie en en-tête.
 */
export function resolveCoverDisplayUrl(displayUrl, rawUrl, metaBase) {
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
  try {
    const parsed = new URL(u);
    if (parsed.searchParams.has("embed_token")) {
      parsed.searchParams.delete("embed_token");
      return parsed.toString();
    }
  } catch {
    /* not absolute: nothing to strip */
  }
  return u;
}
