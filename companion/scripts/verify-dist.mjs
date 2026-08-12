/**
 * Check that the shipped zips match the sources.
 * Usage: node companion/scripts/verify-dist.mjs
 *
 * The zips in dist/ are what users sideload, and they are built by hand. This
 * refuses a commit where a source file changed without a repack, an entry is
 * missing, or the two manifests disagree on the version.
 */
import { existsSync, readFileSync, readdirSync, statSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join, relative, sep } from "path";
import { inflateRawSync } from "zlib";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const DIST = join(ROOT, "dist");
const INCLUDE = [
  "manifest.json",
  "background.js",
  "options.html",
  "options.js",
  "options.css",
  "content",
  "lib",
  "_locales",
  "icons",
];

const failures = [];
function check(cond, msg) {
  if (!cond) failures.push(msg);
}

/** Minimal ZIP reader: central directory walk + raw inflate. */
function readZip(path) {
  const buf = readFileSync(path);
  let eocd = -1;
  for (let i = buf.length - 22; i >= 0; i -= 1) {
    if (buf.readUInt32LE(i) === 0x06054b50) {
      eocd = i;
      break;
    }
  }
  if (eocd === -1) throw new Error(`${path}: fin d'archive introuvable`);
  const count = buf.readUInt16LE(eocd + 10);
  let offset = buf.readUInt32LE(eocd + 16);
  const entries = new Map();
  for (let i = 0; i < count; i += 1) {
    if (buf.readUInt32LE(offset) !== 0x02014b50) {
      throw new Error(`${path}: entrée centrale ${i} corrompue`);
    }
    const method = buf.readUInt16LE(offset + 10);
    const compSize = buf.readUInt32LE(offset + 20);
    const nameLen = buf.readUInt16LE(offset + 28);
    const extraLen = buf.readUInt16LE(offset + 30);
    const commentLen = buf.readUInt16LE(offset + 32);
    const localOffset = buf.readUInt32LE(offset + 42);
    const name = buf.toString("utf8", offset + 46, offset + 46 + nameLen);
    const localNameLen = buf.readUInt16LE(localOffset + 26);
    const localExtraLen = buf.readUInt16LE(localOffset + 28);
    const dataStart = localOffset + 30 + localNameLen + localExtraLen;
    const raw = buf.subarray(dataStart, dataStart + compSize);
    entries.set(name, method === 8 ? inflateRawSync(raw) : Buffer.from(raw));
    offset += 46 + nameLen + extraLen + commentLen;
  }
  return entries;
}

function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...walk(p));
    else out.push(p);
  }
  return out;
}

function expectedEntries() {
  const out = new Map();
  for (const name of INCLUDE) {
    const src = join(ROOT, name);
    if (!existsSync(src)) continue;
    if (statSync(src).isDirectory()) {
      for (const abs of walk(src)) {
        out.set(relative(ROOT, abs).split(sep).join("/"), abs);
      }
    } else {
      out.set(name, src);
    }
  }
  return out;
}

const chromeVersion = JSON.parse(readFileSync(join(ROOT, "manifest.json"), "utf8")).version;
const firefoxVersion = JSON.parse(
  readFileSync(join(ROOT, "manifest.firefox.json"), "utf8"),
).version;
check(
  chromeVersion === firefoxVersion,
  `versions désaccordées : manifest.json ${chromeVersion} contre manifest.firefox.json ${firefoxVersion}`,
);

const expected = expectedEntries();

for (const [zipName, firefox] of [
  ["metakavita-companion-chrome.zip", false],
  ["metakavita-companion-firefox.zip", true],
]) {
  const zipPath = join(DIST, zipName);
  if (!existsSync(zipPath)) {
    failures.push(`${zipName} absent — lancer node companion/scripts/pack.mjs`);
    continue;
  }
  const entries = readZip(zipPath);

  for (const name of entries.keys()) {
    check(expected.has(name), `${zipName} : ${name} n'existe plus dans les sources`);
  }

  for (const [name, abs] of expected) {
    const packed = entries.get(name);
    if (!packed) {
      failures.push(`${zipName} : ${name} manquant — repacker`);
      continue;
    }
    // pack.mjs re-serialises the Firefox manifest, so compare its meaning.
    if (firefox && name === "manifest.json") {
      const onDisk = JSON.parse(
        readFileSync(join(ROOT, "manifest.firefox.json"), "utf8"),
      );
      check(
        JSON.stringify(JSON.parse(packed.toString("utf8"))) === JSON.stringify(onDisk),
        `${zipName} : le manifeste Firefox packé diffère de manifest.firefox.json`,
      );
      continue;
    }
    check(
      packed.equals(readFileSync(abs)),
      `${zipName} : ${name} diffère de la source — repacker`,
    );
  }
}

if (failures.length) {
  console.error(`verify-dist: ${failures.length} problème(s)`);
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
console.log(`verify-dist: ok (${expected.size} fichiers, version ${chromeVersion})`);
