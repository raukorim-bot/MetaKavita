/**
 * Node self-check for the Companion translation tables.
 * Usage: node companion/scripts/selfcheck-i18n.mjs
 *
 * content/page-ui.js is a classic content script: it cannot import
 * lib/i18n.js, so it carries its own copy of FR/EN. That copy silently drifted
 * — three keys it actually calls were never declared, so users read
 * "toastMixedContentWindow" and "coverPreviewFail" as-is. This check keeps the
 * two copies byte-identical and refuses any key used without a translation.
 */
import { readFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const read = (p) => readFileSync(join(ROOT, p), "utf8");

const failures = [];
function check(cond, msg) {
  if (!cond) failures.push(msg);
}

/** Read a `const NAME = { … }` object literal of plain string values. */
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

const pageUiSrc = read("content/page-ui.js");
const i18nSrc = read("lib/i18n.js");

const tables = {
  "page-ui.js FR": extractTable(pageUiSrc, "FR", "content/page-ui.js"),
  "page-ui.js EN": extractTable(pageUiSrc, "EN", "content/page-ui.js"),
  "lib/i18n.js FR": extractTable(i18nSrc, "FR", "lib/i18n.js"),
  "lib/i18n.js EN": extractTable(i18nSrc, "EN", "lib/i18n.js"),
};

// 1. FR and EN cover the same keys, in each file.
for (const [a, b] of [
  ["page-ui.js FR", "page-ui.js EN"],
  ["lib/i18n.js FR", "lib/i18n.js EN"],
]) {
  for (const key of Object.keys(tables[a])) {
    check(key in tables[b], `${key} : présent dans ${a}, absent de ${b}`);
  }
  for (const key of Object.keys(tables[b])) {
    check(key in tables[a], `${key} : présent dans ${b}, absent de ${a}`);
  }
}

// 2. The duplicated copy matches the module, key for key and text for text.
for (const lang of ["FR", "EN"]) {
  const copy = tables[`page-ui.js ${lang}`];
  const source = tables[`lib/i18n.js ${lang}`];
  for (const key of Object.keys(source)) {
    check(
      key in copy,
      `${key} (${lang}) : dans lib/i18n.js, absent de content/page-ui.js`,
    );
    if (key in copy) {
      check(
        copy[key] === source[key],
        `${key} (${lang}) : textes divergents\n     page-ui : ${copy[key]}\n     lib     : ${source[key]}`,
      );
    }
  }
  for (const key of Object.keys(copy)) {
    check(
      key in source,
      `${key} (${lang}) : dans content/page-ui.js, absent de lib/i18n.js`,
    );
  }
}

// 3. Every key actually called has a translation to return.
const localeKeys = new Set(
  Object.keys(JSON.parse(read("_locales/en/messages.json"))),
);
const CALLERS = [
  { file: "content/page-ui.js", table: tables["page-ui.js FR"], locales: false },
  { file: "options.js", table: tables["lib/i18n.js FR"], locales: true },
];
for (const caller of CALLERS) {
  const src = read(caller.file);
  const used = new Set(
    [...src.matchAll(/\bt\("([A-Za-z0-9_]+)"/g)].map((m) => m[1]),
  );
  for (const key of used) {
    const known = key in caller.table || (caller.locales && localeKeys.has(key));
    check(known, `${caller.file} appelle t("${key}") sans traduction déclarée`);
  }
}

if (failures.length) {
  console.error(`selfcheck-i18n: ${failures.length} problème(s)`);
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
console.log(
  `selfcheck-i18n: ok (${Object.keys(tables["lib/i18n.js FR"]).length} clés, deux copies alignées)`,
);
