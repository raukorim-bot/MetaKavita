/**
 * Ce qui doit disparaître quand on change de série.
 *
 * Les overlays capturent leur `seriesId` à l'ouverture. Tant qu'ils survivent à
 * une navigation, ils continuent d'agir sur la série précédente — sous les yeux
 * de quelqu'un qui en regarde une autre.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { installChrome } from "./helpers/fakes.mjs";
import { loadContentScripts } from "./helpers/fake-dom.mjs";
import { WATCH_FILES } from "../lib/watch-files.js";

const A = "/library/1/series/42";
const B = "/library/1/series/77";

async function arrange() {
  installChrome();
  const sent = [];
  globalThis.chrome.runtime.sendMessage = async (msg) => {
    sent.push(msg);
    if (msg.type === "uiBootstrap") {
      return { ok: true, lang: "fr", strings: {}, settings: { metaBaseUrl: "https://m.example", webhookToken: "t" } };
    }
    if (msg.type === "fetchCovers") return { ok: true, covers: [{ url: "http://cdn/a.jpg" }], seriesName: "A" };
    if (msg.type === "applyCover") return { ok: true };
    return { ok: true };
  };
  const env = loadContentScripts({
    files: WATCH_FILES,
    chrome: globalThis.chrome,
    protocol: "http:",
  });
  // Passer par la vraie navigation : c'est elle qui fait mémoriser la série
  // courante au routeur. Le montage, lui, est différé de 400 ms — on le
  // déclenche à la main pour ne pas attendre.
  env.navigate(A);
  await env.window.__mkCompanionPageUI.mount("42");
  await new Promise((r) => setTimeout(r, 5));
  // Le shadow root est celui que `page-ui.js` s'est créé, pas celui du stub.
  const host = env.document.documentElement.childNodes.find(
    (n) => n.id === "mk-companion-page-host"
  );
  return { ...env, sent, win: env.window, shadow: host._shadow };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

test("changer de série referme le sélecteur de couverture", async () => {
  const env = await arrange();
  env.win.__mkCompanionOpenCover({ seriesId: 42, seriesName: "A", labels: {} });
  await flush();
  await flush();
  assert.equal(env.shadow.byClass("mk-cover-panel").length, 1, "le picker est ouvert");

  env.navigate(B);

  assert.equal(
    env.shadow.byClass("mk-cover-panel").length,
    0,
    "il capture seriesId=42 : laissé ouvert, il écrirait sur la série 42 " +
      "pendant qu'on en regarde une autre"
  );
});

test("changer de série referme la Super Review", async () => {
  const env = await arrange();
  env.win.__mkCompanionOpenMr({ url: "http://m.example/e", metaOrigin: "http://m.example", seriesId: 42, labels: {} });
  await flush();
  assert.ok(env.shadow.find((n) => n.tagName === "IFRAME"));

  env.navigate(B);

  assert.equal(env.shadow.find((n) => n.tagName === "IFRAME"), null);
});

test("re-rendre la MÊME série ne ferme rien", async () => {
  // Angular republie parfois la même URL : fermer le picker sous les doigts de
  // l'utilisateur serait aussi gênant que le laisser ouvert sur la mauvaise série.
  const env = await arrange();
  env.win.__mkCompanionOpenCover({ seriesId: 42, seriesName: "A", labels: {} });
  await flush();
  await flush();

  env.navigate(A);

  assert.equal(env.shadow.byClass("mk-cover-panel").length, 1);
});

test("quitter les fiches série ne laisse rien derrière dans la page", async () => {
  // Le toast vit dans le DOM clair de Kavita — c'est voulu, il doit pouvoir
  // parler quand le shadow root n'est pas monté. Mais il ne doit pas survivre
  // au démontage : rien de nous ne reste dans la page de quelqu'un d'autre.
  const env = await arrange();
  env.win.__mkCompanionShowToast("Ajouté à la file");
  assert.ok(
    env.document.documentElement.walk().some((n) => n.id === "mk-companion-page-toast"),
    "le toast est bien affiché"
  );

  env.navigate("/library/1");

  const reste = env.document.documentElement.walk().map((n) => n.id).filter(Boolean);
  assert.deepEqual(reste, [], `nœuds laissés dans la page : ${reste}`);
});
