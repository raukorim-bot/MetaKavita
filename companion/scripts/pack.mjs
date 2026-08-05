/**
 * Build Chrome + Firefox zip artifacts into companion/dist/
 * Usage: node companion/scripts/pack.mjs
 */
import { createWriteStream, existsSync, mkdirSync, cpSync, rmSync, readFileSync, writeFileSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";
import { execSync } from "child_process";

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

function zipDir(srcDir, outZip) {
  if (existsSync(outZip)) rmSync(outZip, { force: true });
  // Prefer PowerShell Compress-Archive on Windows; zip on Unix.
  try {
    execSync(
      `powershell -NoProfile -Command "Compress-Archive -Path '${srcDir}\\*' -DestinationPath '${outZip}' -Force"`,
      { stdio: "inherit" }
    );
  } catch {
    execSync(`cd "${srcDir}" && zip -r "${outZip}" .`, { stdio: "inherit", shell: true });
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
