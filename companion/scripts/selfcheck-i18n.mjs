/**
 * Contrôle des tables de traduction du Companion.
 * Usage : node companion/scripts/selfcheck-i18n.mjs
 *
 * `content/page-ui.js` est un content script classique : il ne peut pas
 * importer `lib/i18n.js`. Il en portait donc une COPIE des 58 clés, que ce
 * script maintenait alignée — après qu'elle eut dérivé au point de faire
 * afficher « toastMixedContentWindow » et « coverPreviewFail » tels quels.
 *
 * La copie a disparu : le content script demande la table au service worker
 * (message `uiBootstrap`). Le contrôle se retourne donc en son inverse — il
 * n'existe qu'UNE table — ce qui rend la dérive impossible au lieu de la
 * surveiller. Restent la parité FR/EN et le refus d'une clé sans traduction,
 * ce dernier étendu à tous les content scripts.
 */
import { readFileSync, readdirSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const read = (p) => readFileSync(join(ROOT, p), "utf8");

const failures = [];
function check(cond, msg) {
  if (!cond) failures.push(msg);
}

/** Lit un littéral `const NAME = { … }` de valeurs chaînes. */
function extractTable(src, name, where) {
  const start = src.indexOf(`const ${name} = {`);
  if (start === -1) throw new Error(`${where}: table ${name} introuvable`);
  const open = src.indexOf("{", start);
  let depth = 0;
  let end = -1;
  for (let i = open; i < src.length; i += 1) {
    if (src[i] === "{") depth += 1;
    else if (src[i] === "}") {
      depth -= 1;
      if (depth === 0) {
        end = i;
        break;
      }
    }
  }
  if (end === -1) throw new Error(`${where}: table ${name} non terminée`);
  const table = new Function(`return ${src.slice(open, end + 1)};`)();
  if (!table || typeof table !== "object") {
    throw new Error(`${where}: table ${name} illisible`);
  }
  return table;
}

const i18nSrc = read("lib/i18n.js");
const FR = extractTable(i18nSrc, "FR", "lib/i18n.js");
const EN = extractTable(i18nSrc, "EN", "lib/i18n.js");

// 1. FR et EN couvrent les mêmes clés.
for (const key of Object.keys(FR)) {
  check(key in EN, `${key} : présent en FR, absent en EN`);
}
for (const key of Object.keys(EN)) {
  check(key in FR, `${key} : présent en EN, absent en FR`);
}

// 2. Il n'existe qu'une table. Une seconde, où qu'elle soit, redeviendrait une
//    copie à tenir à jour à la main — c'est ce qui avait dérivé.
const contentFiles = readdirSync(join(ROOT, "content")).filter((f) => f.endsWith(".js"));
for (const rel of [...contentFiles.map((f) => `content/${f}`), "options.js", "background.js"]) {
  const src = read(rel);
  for (const name of ["FR", "EN"]) {
    check(
      src.indexOf(`const ${name} = {`) === -1,
      `${rel} déclare une table ${name} — la table vit dans lib/i18n.js, ` +
        "servie au content script par le message uiBootstrap",
    );
  }
}

// 3. Toute clé réellement appelée a une traduction à rendre.
const localeKeys = new Set(Object.keys(JSON.parse(read("_locales/en/messages.json"))));
const CALLERS = [
  // Les content scripts lisent la table servie par le worker (donc lib/i18n.js),
  // avec repli sur `_locales` quand l'aller-retour vient d'échouer.
  ...contentFiles.map((f) => ({ file: `content/${f}`, locales: true })),
  { file: "options.js", locales: true },
];
for (const caller of CALLERS) {
  const src = read(caller.file);
  const used = new Set([...src.matchAll(/\bt\("([A-Za-z0-9_]+)"/g)].map((m) => m[1]));
  for (const key of used) {
    const known = key in FR || (caller.locales && localeKeys.has(key));
    check(known, `${caller.file} appelle t("${key}") sans traduction déclarée`);
  }
}

// 4. Les clés de secours — celles qu'un content script affiche justement quand
//    l'aller-retour a échoué — doivent exister dans `_locales`, seul recours
//    synchrone qui reste à ce moment-là.
for (const key of ["toastExtensionReloaded", "toastNeedConfig"]) {
  check(localeKeys.has(key), `${key} manque dans _locales : c'est la clé de secours`);
}

if (failures.length) {
  console.error(`selfcheck-i18n: ${failures.length} problème(s)`);
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
console.log(`selfcheck-i18n: ok (${Object.keys(FR).length} clés, table unique)`);
