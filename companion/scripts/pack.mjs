/**
 * Build Chrome + Firefox zip artifacts into companion/dist/
 * Usage: node companion/scripts/pack.mjs
 *
 * Uses a pure-Node ZIP writer so entry names always use forward slashes
 * (PowerShell Compress-Archive stores Windows backslashes, which break
 * unzip on Linux/macOS — files appear as literal "lib\\storage.js").
 */
import {
  existsSync,
  mkdirSync,
  cpSync,
  rmSync,
  readFileSync,
  writeFileSync,
  readdirSync,
  statSync,
} from "fs";
import { join, dirname, relative, sep } from "path";
import { fileURLToPath } from "url";
import { deflateRawSync } from "zlib";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");
const DIST = join(ROOT, "dist");
const INCLUDE = [
  "manifest.json",
  "background.js",
  "options.html",
  "options.js",
  "options.css",
  "content",
  "overlay",
  "lib",
  "_locales",
  "icons",
];

/** CRC-32 (ISO 3309 / ZIP) */
const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[i] = c >>> 0;
  }
  return t;
})();

function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function walkFiles(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...walkFiles(p));
    else out.push(p);
  }
  return out;
}

function u16(n) {
  const b = Buffer.alloc(2);
  b.writeUInt16LE(n, 0);
  return b;
}

function u32(n) {
  const b = Buffer.alloc(4);
  b.writeUInt32LE(n >>> 0, 0);
  return b;
}

/**
 * Write a ZIP with POSIX forward-slash paths (ZIP APPNOTE 4.4.17).
 */
function zipDir(srcDir, outZip) {
  if (existsSync(outZip)) rmSync(outZip, { force: true });

  const files = walkFiles(srcDir).sort();
  const localChunks = [];
  const centralChunks = [];
  let offset = 0;

  for (const abs of files) {
    const name = relative(srcDir, abs).split(sep).join("/");
    const nameBuf = Buffer.from(name, "utf8");
    const data = readFileSync(abs);
    const compressed = deflateRawSync(data);
    const crc = crc32(data);
    const method = 8; // deflate

    const local = Buffer.concat([
      u32(0x04034b50),
      u16(20), // version needed
      u16(0), // flags
      u16(method),
      u16(0), // time
      u16(0), // date
      u32(crc),
      u32(compressed.length),
      u32(data.length),
      u16(nameBuf.length),
      u16(0), // extra len
      nameBuf,
      compressed,
    ]);

    const central = Buffer.concat([
      u32(0x02014b50),
      u16(20), // version made by (0=DOS + 20)
      u16(20), // version needed
      u16(0),
      u16(method),
      u16(0),
      u16(0),
      u32(crc),
      u32(compressed.length),
      u32(data.length),
      u16(nameBuf.length),
      u16(0), // extra
      u16(0), // comment
      u16(0), // disk start
      u16(0), // int attrs
      u32(0), // ext attrs
      u32(offset),
      nameBuf,
    ]);

    localChunks.push(local);
    centralChunks.push(central);
    offset += local.length;
  }

  const centralDir = Buffer.concat(centralChunks);
  const end = Buffer.concat([
    u32(0x06054b50),
    u16(0),
    u16(0),
    u16(files.length),
    u16(files.length),
    u32(centralDir.length),
    u32(offset),
    u16(0),
  ]);

  writeFileSync(outZip, Buffer.concat([...localChunks, centralDir, end]));
}

function stage(dir, useFirefox) {
  if (existsSync(dir)) rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  for (const name of INCLUDE) {
    const src = join(ROOT, name);
    if (!existsSync(src)) continue;
    cpSync(src, join(dir, name), { recursive: true });
  }
  if (useFirefox) {
    const ff = JSON.parse(readFileSync(join(ROOT, "manifest.firefox.json"), "utf8"));
    writeFileSync(join(dir, "manifest.json"), JSON.stringify(ff, null, 2));
  }
}

mkdirSync(DIST, { recursive: true });
const chromeStage = join(DIST, "_chrome");
const firefoxStage = join(DIST, "_firefox");
stage(chromeStage, false);
stage(firefoxStage, true);
zipDir(chromeStage, join(DIST, "metakavita-companion-chrome.zip"));
zipDir(firefoxStage, join(DIST, "metakavita-companion-firefox.zip"));
rmSync(chromeStage, { recursive: true, force: true });
rmSync(firefoxStage, { recursive: true, force: true });
console.log("Wrote dist/metakavita-companion-chrome.zip");
console.log("Wrote dist/metakavita-companion-firefox.zip");
