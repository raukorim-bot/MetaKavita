/**
 * Géométrie de la constellation.
 *
 * L'arc unique ne tenait plus : `ARC_RANGES` s'arrête à 5 et il y avait déjà
 * 5 boutons. Sept sur un seul arc donnaient un rayon de 203 px et un menu qui
 * déborde de l'écran. Ces tests vérifient ce qu'un coup d'œil ne prouve pas —
 * que rien ne se chevauche, et que le quinconce est réel.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { installChrome } from "./helpers/fakes.mjs";
import { loadContentScripts } from "./helpers/fake-dom.mjs";
import { WATCH_FILES } from "../lib/watch-files.js";

const INNER_D = 46;
const OUTER_D = 38;

// La géométrie se vérifie en mode EXPERT : c'est lui qui porte les deux
// couronnes pleines. La composition par mode a ses propres tests.
async function mount({ innerWidth = 1440, innerHeight = 900, settings = {}, uiMode = "expert" } = {}) {
  installChrome();
  globalThis.chrome.runtime.sendMessage = async (msg) =>
    msg.type === "uiBootstrap"
      ? {
          ok: true,
          lang: "fr",
          uiMode,
          strings: {},
          settings: { metaBaseUrl: "https://m.example", webhookToken: "t", ...settings },
        }
      : { ok: true };

  const env = loadContentScripts({
    files: WATCH_FILES,
    chrome: globalThis.chrome,
    innerWidth,
    innerHeight,
  });
  await env.window.__mkCompanionPageUI.mount("42");
  await new Promise((r) => setTimeout(r, 5));

  // Le shadow root est fermé : la page n'y accède pas. Le stub le range à
  // part, comme le panneau Elements d'un navigateur le montre encore.
  const host = env.document.documentElement.childNodes.find((n) => n.id === "mk-companion-page-host");
  return { env, shadow: host._shadow, ui: env.window.__mkCompanionPageUI };
}

/** Position d'un bouton, lue dans les variables CSS que le layout a posées. */
function place(el) {
  const px = (k) => parseFloat(el.style.getPropertyValue(k) || "0");
  return { x: px("--x"), y: px("--y"), el };
}

function positions(shadow) {
  const fabs = shadow
    .byClass("fab")
    .filter((el) => el.style.display !== "none" && !String(el.className).includes("fab-logo"));
  return fabs.map((el) => ({
    ...place(el),
    id: el.id,
    diameter: String(el.className).includes("fab--outer") ? OUTER_D : INNER_D,
  }));
}

const hypot = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
const angle = (p) => (Math.atan2(-p.y, p.x) * 180) / Math.PI;

test("aucun bouton n'en chevauche un autre", async () => {
  const { shadow } = await mount();
  shadow.getElementById("btnLogo").dispatchEvent({ type: "click" });
  await new Promise((r) => setTimeout(r, 5));

  const all = positions(shadow);
  assert.equal(all.length, 7, "quatre actions plus trois raccourcis");

  for (let i = 0; i < all.length; i += 1) {
    for (let j = i + 1; j < all.length; j += 1) {
      const need = all[i].diameter / 2 + all[j].diameter / 2;
      const got = hypot(all[i], all[j]);
      assert.ok(got >= need, `${all[i].id} et ${all[j].id} se chevauchent (${got.toFixed(1)} < ${need})`);
    }
  }
});

test("la couronne extérieure est plus loin, et intercalée", async () => {
  const { shadow } = await mount();
  shadow.getElementById("btnLogo").dispatchEvent({ type: "click" });
  await new Promise((r) => setTimeout(r, 5));

  const all = positions(shadow);
  const inner = all.filter((p) => p.diameter === INNER_D);
  const outer = all.filter((p) => p.diameter === OUTER_D);
  const radius = (p) => Math.hypot(p.x, p.y);

  const innerMax = Math.max(...inner.map(radius));
  const outerMin = Math.min(...outer.map(radius));
  assert.ok(outerMin > innerMax, `couronne extérieure trop proche (${outerMin} ≤ ${innerMax})`);

  // Chaque item extérieur tombe STRICTEMENT entre deux items intérieurs :
  // c'est la définition du quinconce, et ce qui rend la figure lisible.
  const innerAngles = inner.map(angle).sort((a, b) => a - b);
  for (const p of outer) {
    const a = angle(p);
    assert.ok(
      a > innerAngles[0] && a < innerAngles[innerAngles.length - 1],
      `un raccourci sort de la fenêtre angulaire (${a.toFixed(1)}°)`
    );
    assert.ok(
      innerAngles.every((ia) => Math.abs(ia - a) > 4),
      `un raccourci est aligné sur une action (${a.toFixed(1)}°)`
    );
  }
});

test("toute la figure s'ouvre vers le haut et vers la gauche", async () => {
  // Le logo est ancré en bas à droite : un bouton à x > 0 ou y > 0 sortirait
  // de l'écran.
  const { shadow } = await mount();
  shadow.getElementById("btnLogo").dispatchEvent({ type: "click" });
  await new Promise((r) => setTimeout(r, 5));

  for (const p of positions(shadow)) {
    assert.ok(p.x <= 0, `${p.id} part vers la droite (x=${p.x})`);
    assert.ok(p.y <= 0, `${p.id} part vers le bas (y=${p.y})`);
  }
});

test("couronne intérieure masquée : l'extérieure prend sa place", async () => {
  // Décocher « Afficher les boutons » vide la couronne intérieure. La règle
  // « écarter les vides puis attribuer les rayons » doit faire remonter
  // l'extérieure au rayon intérieur, sans cas particulier.
  const plein = await mount();
  plein.shadow.getElementById("btnLogo").dispatchEvent({ type: "click" });
  await new Promise((r) => setTimeout(r, 5));
  const rayonInterieur = Math.min(
    ...positions(plein.shadow).filter((p) => p.diameter === INNER_D).map((p) => Math.hypot(p.x, p.y))
  );

  const vide = await mount({ settings: { showActionFabs: false } });
  vide.shadow.getElementById("btnLogo").dispatchEvent({ type: "click" });
  await new Promise((r) => setTimeout(r, 5));
  const restants = positions(vide.shadow);

  assert.equal(restants.length, 3, "seuls les raccourcis restent");
  const rayons = restants.map((p) => Math.hypot(p.x, p.y));
  assert.ok(
    Math.max(...rayons) < rayonInterieur + 40,
    `les raccourcis restent loin alors que la place est libre (${Math.max(...rayons)} contre ${rayonInterieur})`
  );
});

test("sur un téléphone, la constellation tient encore", async () => {
  // La figure s'étend à ~214 px du centre du logo, lui-même à 48 px du coin :
  // il lui faut ~280 px par axe. Un écran de téléphone les a.
  const { shadow } = await mount({ innerWidth: 375, innerHeight: 667 });
  shadow.getElementById("btnLogo").dispatchEvent({ type: "click" });
  await new Promise((r) => setTimeout(r, 5));

  const spread = new Set(positions(shadow).map((p) => p.x));
  assert.ok(spread.size > 1, "les boutons doivent rester déployés en arc");
});

test("dans une fenêtre vraiment exiguë, elle devient une colonne", async () => {
  const { shadow } = await mount({ innerWidth: 280, innerHeight: 520 });
  shadow.getElementById("btnLogo").dispatchEvent({ type: "click" });
  await new Promise((r) => setTimeout(r, 5));

  const all = positions(shadow);
  assert.ok(all.length > 0);
  for (const p of all) {
    assert.equal(p.x, 0, `${p.id} doit être aligné sur le logo`);
  }
  const ys = all.map((p) => p.y).sort((a, b) => b - a);
  assert.deepEqual(new Set(ys).size, ys.length, "aucun bouton ne doit en recouvrir un autre");
});
