/**
 * Node self-check for isMetaKavitaUrl (issue #34) and normalizeBaseUrl.
 * Usage: node companion/scripts/selfcheck-url-match.mjs
 */
import { isMetaKavitaUrl, normalizeBaseUrl, originFromUrl } from "../lib/storage.js";

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

const meta = "https://example.com/metakavita";
const kavitaSeries = "https://example.com/kavita/library/1/series/42";
const metaPage = "https://example.com/metakavita/dashboard";
const otherHost = "https://kavita.other/library/1/series/42";

assert(!isMetaKavitaUrl(kavitaSeries, meta), "same-host Kavita series must not be Meta");
assert(isMetaKavitaUrl(metaPage, meta), "Meta subpath page must be Meta");
assert(isMetaKavitaUrl(meta, meta), "Meta base URL itself must be Meta");
assert(!isMetaKavitaUrl(otherHost, meta), "other host is not Meta");

const metaRoot = "https://meta.example.com";
assert(isMetaKavitaUrl("https://meta.example.com/login", metaRoot), "root Meta login is Meta");
assert(
  !isMetaKavitaUrl("https://meta.example.com/library/1/series/9", metaRoot),
  "series page on Meta root origin is treated as Kavita (enable allowed)"
);

// A saisie without a scheme must still produce a usable origin. "localhost:5011"
// used to parse as the scheme "localhost:" (origin null), and the failure
// surfaced as a permission error.
const NORMALIZED = [
  ["localhost:5011", "http://localhost:5011"],
  ["nas:5011", "http://nas:5011"],
  ["metakavita", "http://metakavita"],
  ["127.0.0.1:5011", "http://127.0.0.1:5011"],
  ["192.168.1.20:5011", "http://192.168.1.20:5011"],
  ["10.0.0.4", "http://10.0.0.4"],
  ["meta.example.com", "https://meta.example.com"],
  ["meta.example.com/metakavita/", "https://meta.example.com/metakavita"],
  ["http://localhost:5011/", "http://localhost:5011"],
  ["https://meta.example.com", "https://meta.example.com"],
];
for (const [input, expected] of NORMALIZED) {
  const got = normalizeBaseUrl(input);
  assert(got === expected, `normalizeBaseUrl(${input}) = ${got}, attendu ${expected}`);
  const origin = originFromUrl(input);
  assert(
    origin && origin !== "null",
    `originFromUrl(${input}) = ${origin} — origine inutilisable`,
  );
}
assert(normalizeBaseUrl("") === "", "chaîne vide inchangée");

console.log("selfcheck-url-match: ok");
