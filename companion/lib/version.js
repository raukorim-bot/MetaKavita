/**
 * Comparaison de versions MetaKavita.
 *
 * L'extension parle à un serveur qu'elle ne contrôle pas et dont les routes
 * apparaissent au fil des versions. Sans ce test, une instance trop ancienne se
 * signalait en pannes successives — un bouton après l'autre, chacun avec son
 * propre message obscur.
 */

/** `"1.7.10"` → `[1, 7, 10]`. Les segments non numériques comptent pour 0. */
function parts(version) {
  return String(version || "")
    .trim()
    .split(/[.\-+]/)
    .map((p) => {
      const n = parseInt(p, 10);
      return Number.isFinite(n) ? n : 0;
    });
}

/** -1, 0 ou 1, comme un comparateur de tri. */
export function compareVersions(a, b) {
  const left = parts(a);
  const right = parts(b);
  const len = Math.max(left.length, right.length);
  for (let i = 0; i < len; i += 1) {
    const x = left[i] || 0;
    const y = right[i] || 0;
    if (x !== y) return x < y ? -1 : 1;
  }
  return 0;
}

/**
 * Vrai si `version` atteint `floor`.
 *
 * ⚠️ Une version INCONNUE (chaîne vide : instance qui ne l'annonce pas) rend
 * `true`. On ne retire pas une fonction sur un doute — le serveur répondra 404
 * et la fonction se retirera d'elle-même, ce qui est le bon ordre : mieux vaut
 * une fonction qui se tait qu'une fonction absente sans raison visible.
 */
export function atLeast(version, floor) {
  if (!String(version || "").trim()) return true;
  return compareVersions(version, floor) >= 0;
}
