/**
 * Les deux modes d'interface.
 *
 * Le réglage qui existait — « masquer les boutons d'action » — retirait
 * justement ce qui sert et gardait Config, Meta et Café. Un mode, lui, bouge
 * trois choses ensemble : le nombre d'actions, le vocabulaire, et le fait
 * qu'un geste qui écrit sans rien montrer demande d'abord.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { installChrome } from "./helpers/fakes.mjs";
import { loadContentScripts } from "./helpers/fake-dom.mjs";
import { WATCH_FILES } from "../lib/watch-files.js";
import { defaultUiMode, effectiveUiMode } from "../lib/storage.js";

const STRINGS = {
  fabSuper: "Super Review",
  fabAuto: "Auto",
  fabCover: "Cover",
  fabWorkshop: "Atelier des tomes",
  fabCompleteSeries: "Compléter cette série",
  fabCompleteAuto: "Compléter sans me demander",
  fabChangeCover: "Changer la couverture",
  confirmAutoBody: "Les métadonnées vont être remplacées. Continuer ?",
  confirmAutoSeeFirst: "Voir avant d’écrire",
  confirmGo: "Continuer",
  confirmCancel: "Annuler",
};

async function mount({ uiMode = "simple", settings = {} } = {}) {
  installChrome();
  const sent = [];
  globalThis.chrome.runtime.sendMessage = async (msg) => {
    sent.push(msg);
    if (msg.type === "uiBootstrap") {
      return {
        ok: true,
        lang: "fr",
        uiMode,
        strings: STRINGS,
        settings: { metaBaseUrl: "https://m.example", webhookToken: "t", ...settings },
      };
    }
    return { ok: true, body: {} };
  };
  const env = loadContentScripts({ files: WATCH_FILES, chrome: globalThis.chrome, protocol: "http:" });
  await env.window.__mkCompanionPageUI.mount("42");
  await new Promise((r) => setTimeout(r, 5));
  const host = env.document.documentElement.childNodes.find((n) => n.id === "mk-companion-page-host");
  return { ...env, sent, shadow: host._shadow, win: env.window };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

function visible(shadow) {
  return shadow
    .byClass("fab")
    .filter((el) => el.style.display !== "none")
    .map((el) => el.id);
}

test("le mode simplifié n'offre que ce qu'on fait couramment", async () => {
  const { shadow } = await mount({ uiMode: "simple" });

  assert.deepEqual(visible(shadow).sort(), ["btnAuto", "btnBmc", "btnConfig", "btnCover", "btnSuper"]);
  // Ni l'Atelier ni « Ouvrir dans MetaKavita » : deux chantiers pour qui sait
  // déjà ce qu'il cherche.
  assert.ok(!visible(shadow).includes("btnWorkshop"));
  assert.ok(!visible(shadow).includes("btnMeta"));
});

test("Auto descend d'une couronne en mode simplifié", async () => {
  // Il écrit sans rien montrer : il n'a pas sa place au premier rang.
  const simple = await mount({ uiMode: "simple" });
  assert.ok(simple.shadow.getElementById("btnAuto").className.includes("fab--outer"));

  const expert = await mount({ uiMode: "expert" });
  assert.ok(!expert.shadow.getElementById("btnAuto").className.includes("fab--outer"));
});

test("le vocabulaire change avec le mode", async () => {
  const simple = await mount({ uiMode: "simple" });
  assert.equal(simple.shadow.getElementById("btnSuper").title, "Compléter cette série");
  assert.equal(simple.shadow.getElementById("btnCover").title, "Changer la couverture");

  const expert = await mount({ uiMode: "expert" });
  // Les noms produit, ceux de l'interface MetaKavita et de la documentation.
  assert.equal(expert.shadow.getElementById("btnSuper").title, "Super Review");
  assert.equal(expert.shadow.getElementById("btnCover").title, "Cover");
});

test("en mode simplifié, Auto demande avant d'écrire", async () => {
  const env = await mount({ uiMode: "simple" });
  env.shadow.getElementById("btnAuto").dispatchEvent({ type: "click" });
  await flush();

  const carte = env.shadow.byClass("mk-confirm")[0];
  assert.ok(carte, "une confirmation doit s'afficher");
  assert.ok(carte.textContent.includes("Continuer ?"));
  assert.equal(
    env.sent.filter((m) => m.type === "webhook").length,
    0,
    "rien ne doit partir avant la réponse"
  );
});

test("annuler n'écrit rien du tout", async () => {
  const env = await mount({ uiMode: "simple" });
  env.shadow.getElementById("btnAuto").dispatchEvent({ type: "click" });
  await flush();

  env.shadow
    .byClass("mk-confirm")[0]
    .findAll((n) => n.textContent === "Annuler")[0]
    .dispatchEvent({ type: "click" });
  await flush();
  await flush();

  assert.equal(env.sent.filter((m) => m.type === "webhook").length, 0);
  assert.equal(env.shadow.byClass("mk-confirm").length, 0, "la carte doit se refermer");
});

test("« Voir avant d'écrire » bascule sur la revue, pas sur l'écriture aveugle", async () => {
  const env = await mount({ uiMode: "simple" });
  env.shadow.getElementById("btnAuto").dispatchEvent({ type: "click" });
  await flush();

  env.shadow
    .byClass("mk-confirm")[0]
    .findAll((n) => n.textContent === "Voir avant d’écrire")[0]
    .dispatchEvent({ type: "click" });
  await flush();
  await flush();

  const hooks = env.sent.filter((m) => m.type === "webhook");
  assert.equal(hooks.length, 1);
  assert.equal(hooks[0].payload.super_review, true, "la revue montre avant d'écrire");
  assert.ok(!hooks[0].payload.auto, "et surtout pas l'écriture directe");
});

test("confirmer lance bien l'écriture directe", async () => {
  const env = await mount({ uiMode: "simple" });
  env.shadow.getElementById("btnAuto").dispatchEvent({ type: "click" });
  await flush();

  env.shadow
    .byClass("mk-confirm")[0]
    .findAll((n) => n.textContent === "Continuer")[0]
    .dispatchEvent({ type: "click" });
  await flush();
  await flush();

  const hooks = env.sent.filter((m) => m.type === "webhook");
  assert.equal(hooks.length, 1);
  assert.equal(hooks[0].payload.auto, true);
});

test("en mode expert, Auto part sans rien demander", async () => {
  // C'est tout l'intérêt du mode : un clic, une écriture.
  const env = await mount({ uiMode: "expert" });
  env.shadow.getElementById("btnAuto").dispatchEvent({ type: "click" });
  await flush();
  await flush();

  assert.equal(env.shadow.byClass("mk-confirm").length, 0);
  assert.equal(env.sent.filter((m) => m.type === "webhook")[0].payload.auto, true);
});

test("masquer les boutons d'action retire les actions des DEUX couronnes", async () => {
  // En simplifié, Auto vit sur la couronne extérieure : la case doit l'emporter
  // lui aussi, sans quoi elle ne masquerait qu'une partie de ce qu'elle annonce.
  const { shadow } = await mount({ uiMode: "simple", settings: { showActionFabs: false } });

  assert.deepEqual(visible(shadow).sort(), ["btnBmc", "btnConfig"]);
});

test("une installation déjà appairée ne se fait pas rétrograder", async () => {
  // Le mode est déduit tant que l'utilisateur n'a rien choisi. Quelqu'un qui a
  // déjà appairé son instance connaît l'outil : lui retirer des boutons à la
  // mise à jour serait une régression silencieuse.
  assert.equal(defaultUiMode({ metaBaseUrl: "https://m.example" }), "expert");
  assert.equal(defaultUiMode({ kavitaOrigins: ["https://kavita.example"] }), "expert");
  assert.equal(defaultUiMode({}), "simple");
  assert.equal(defaultUiMode({ metaBaseUrl: "", kavitaOrigins: [] }), "simple");
});

test("un choix explicite l'emporte toujours sur la déduction", async () => {
  assert.equal(effectiveUiMode({ uiMode: "simple", metaBaseUrl: "https://m.example" }), "simple");
  assert.equal(effectiveUiMode({ uiMode: "expert" }), "expert");
  assert.equal(effectiveUiMode({ uiMode: "", metaBaseUrl: "https://m.example" }), "expert");
  assert.equal(effectiveUiMode({ uiMode: "n’importe quoi" }), "simple");
});
