/**
 * Les content scripts injectés dans une page Kavita, et leur ordre.
 *
 * Ce module ne doit ni importer ni produire d'effet de bord : il est chargé
 * tel quel par les tests, pour qu'ils lisent les scripts dans l'ordre réel de
 * production plutôt que dans un ordre recopié à la main.
 *
 * La liste vivait en double, littérale, dans `registerContentScripts` et dans
 * `executeScript` — deux endroits à tenir d'accord pour une seule vérité.
 */

export const WATCH_SCRIPT_ID = "mk-companion-watch";

/**
 * ⚠️ L'ordre compte. Ce sont des scripts classiques exécutés à la suite dans le
 * même monde isolé : un fichier définit ses globales au chargement et ne lit
 * celles des autres que dans un callback. `watch.js` fait exception — il amorce
 * la surveillance de navigation — et doit donc rester en dernier.
 */
export const WATCH_FILES = [
  "content/base.js",
  "content/page-ui.js",
  "content/overlay-mr.js",
  "content/overlay-cover.js",
  "content/watch.js",
];
