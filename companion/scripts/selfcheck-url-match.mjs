/**
 * Node self-check for isMetaKavitaUrl (issue #34).
 * Usage: node companion/scripts/selfcheck-url-match.mjs
 */
import { isMetaKavitaUrl } from "../lib/storage.js";

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

console.log("selfcheck-url-match: ok");
