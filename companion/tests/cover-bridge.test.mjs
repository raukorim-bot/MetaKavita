/**
 * Le cover picker : aperçus, messages d'erreur, application.
 *
 * Couvre l'invariant que des assertions textuelles gardaient jusqu'ici — un
 * aperçu proxifié ne doit JAMAIS être posé tel quel dans un `<img src>`, parce
 * qu'il faudrait pour cela y mettre le jeton d'embed, que la page Kavita lirait.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { installChrome } from "./helpers/fakes.mjs";
import { loadContentScripts } from "./helpers/fake-dom.mjs";

const FILES = ["content/base.js", "content/overlay-cover.js"];
const LABELS = {
  title: "Choisir une couverture",
  search: "Rechercher",
  searching: "Recherche…",
  empty: "Aucune couverture trouvée",
  close: "Fermer",
  applied: "Couverture appliquée",
  fail: "Échec",
  previewFail: "Aperçu indisponible",
  previewLogin: "Aperçus refusés par MetaKavita",
  count: "$1$ couverture(s)",
  needConfig: "Configurez d'abord le Companion",
};

/** `chrome.runtime.sendMessage` enregistré, réponses scriptées par type. */
function arrange({ protocol = "https:", routes = {} } = {}) {
  installChrome();
  const sent = [];
  globalThis.chrome.runtime.sendMessage = async (msg) => {
    sent.push(msg);
    const route = routes[msg.type];
    return typeof route === "function" ? route(msg) : route || { ok: false, error: "unrouted" };
  };
  const env = loadContentScripts({ files: FILES, chrome: globalThis.chrome, protocol });
  return { ...env, sent, win: env.window };
}

const open = (env, opts = {}) =>
  env.win.__mkCompanionOpenCover({
    seriesId: 42,
    seriesName: "Vinland Saga",
    labels: LABELS,
    ...opts,
  });

const flush = () => new Promise((r) => setTimeout(r, 0));

const status = (env) => env.shadow.byClass("mk-cover-status")[0];
const images = (env) => env.shadow.findAll((n) => n.tagName === "IMG");

test("un aperçu proxifié passe par le worker, jamais par un img src direct", async () => {
  const env = arrange({
    routes: {
      fetchCovers: {
        ok: true,
        covers: [{ url: "https://cdn/a.jpg", display_url: "https://meta.example/api/proxy-image?u=a", provider: "MangaDex" }],
      },
      fetchImageData: { ok: true, dataUrl: "data:image/png;base64,AAA" },
    },
  });
  open(env);
  await flush();
  await flush();

  const bridged = env.sent.filter((m) => m.type === "fetchImageData");
  assert.equal(bridged.length, 1, "l'aperçu doit transiter par le service worker");
  assert.equal(bridged[0].seriesId, 42, "et rester borné à sa série");
  assert.equal(images(env)[0].src, "data:image/png;base64,AAA");
});

test("sur une page https, un aperçu http part aussi par le worker", async () => {
  // Contenu mixte : le navigateur bloquerait l'image ; le worker y échappe.
  const env = arrange({
    protocol: "https:",
    routes: {
      fetchCovers: { ok: true, covers: [{ url: "http://meta.lan/c.jpg", display_url: "http://meta.lan/c.jpg" }] },
      fetchImageData: { ok: true, dataUrl: "data:image/jpeg;base64,BBB" },
    },
  });
  open(env);
  await flush();
  await flush();

  assert.equal(env.sent.filter((m) => m.type === "fetchImageData").length, 1);
});

test("sur une page http, une jaquette directe s'affiche sans détour", async () => {
  const env = arrange({
    protocol: "http:",
    routes: {
      fetchCovers: { ok: true, covers: [{ url: "http://cdn/a.jpg", display_url: "http://cdn/a.jpg" }] },
    },
  });
  open(env);
  await flush();
  await flush();

  assert.equal(env.sent.filter((m) => m.type === "fetchImageData").length, 0);
  assert.equal(images(env)[0].src, "http://cdn/a.jpg");
});

test("le compte de couvertures est traduit, pas bricolé en anglais", async () => {
  // Il était écrit en dur : `covers.length + " cover(s)"`, dans une interface
  // par ailleurs entièrement bilingue.
  const env = arrange({
    routes: {
      fetchCovers: { ok: true, covers: [{ url: "http://cdn/a.jpg" }, { url: "http://cdn/b.jpg" }] },
    },
    protocol: "http:",
  });
  open(env);
  await flush();
  await flush();

  assert.equal(status(env).textContent, "2 couverture(s)");
});

test("un motif technique ne s'affiche pas : il part en console", async () => {
  const env = arrange({ routes: { fetchCovers: { ok: false, error: "HTTP 500" } } });
  open(env);
  await flush();
  await flush();

  const shown = status(env).textContent;
  assert.ok(!shown.includes("HTTP 500"), `« ${shown} » ne doit pas montrer le motif brut`);
  assert.equal(shown, LABELS.previewFail);
});

test("un refus de connexion MetaKavita a son propre message", async () => {
  const env = arrange({ routes: { fetchCovers: { ok: false, error: "meta_login_required" } } });
  open(env);
  await flush();
  await flush();

  assert.equal(status(env).textContent, LABELS.previewLogin);
});

test("aucune couverture trouvée n'est pas une erreur", async () => {
  const env = arrange({ routes: { fetchCovers: { ok: true, covers: [] } } });
  open(env);
  await flush();
  await flush();

  assert.equal(status(env).textContent, LABELS.empty);
});

test("appliquer une couverture rafraîchit la jaquette et referme", async () => {
  const env = arrange({
    protocol: "http:",
    routes: {
      fetchCovers: { ok: true, covers: [{ url: "http://cdn/a.jpg", provider: "MangaDex" }] },
      applyCover: { ok: true },
    },
  });
  const busted = [];
  env.win.__mkCompanionCacheBust = (sid) => busted.push(String(sid));
  open(env);
  await flush();
  await flush();

  const card = env.shadow.byClass("mk-cover-card")[0];
  card.dispatchEvent({ type: "click" });
  await flush();
  await flush();

  const applied = env.sent.find((m) => m.type === "applyCover");
  assert.equal(applied.coverUrl, "http://cdn/a.jpg");
  assert.deepEqual(busted, ["42"]);
  assert.equal(env.shadow.byClass("mk-cover-panel").length, 0, "le picker doit se refermer");
});

test("un échec d'application laisse le picker ouvert pour réessayer", async () => {
  const env = arrange({
    protocol: "http:",
    routes: {
      fetchCovers: { ok: true, covers: [{ url: "http://cdn/a.jpg" }] },
      applyCover: { ok: false, error: "HTTP 502" },
    },
  });
  open(env);
  await flush();
  await flush();

  env.shadow.byClass("mk-cover-card")[0].dispatchEvent({ type: "click" });
  await flush();
  await flush();

  assert.equal(env.shadow.byClass("mk-cover-panel").length, 1);
  assert.ok(!status(env).textContent.includes("502"));
});

test("à l'ouverture, le nom n'est PAS imposé : le serveur le résout", async () => {
  const env = arrange({
    protocol: "http:",
    routes: { fetchCovers: { ok: true, covers: [], seriesName: "Vinland Saga" } },
  });
  open(env, { seriesName: "Titre lu dans le DOM" });
  await flush();
  await flush();

  const [call] = env.sent.filter((m) => m.type === "fetchCovers");
  assert.equal(call.seriesName, undefined, "aucun nom imposé au premier chargement");
  assert.equal(call.nameHint, "Titre lu dans le DOM", "le DOM ne sert que de repli");

  const field = env.shadow.byClass("mk-cover-search")[0];
  assert.equal(field.value, "Vinland Saga", "le champ montre ce qui a été cherché");
});

test("ce que l'utilisateur tape fait foi, et n'est plus écrasé", async () => {
  const env = arrange({
    protocol: "http:",
    routes: { fetchCovers: { ok: true, covers: [], seriesName: "Vinland Saga" } },
  });
  open(env, { seriesName: "Titre DOM" });
  await flush();
  await flush();

  const field = env.shadow.byClass("mk-cover-search")[0];
  field.value = "Berserk Deluxe";
  env.shadow.byClass("mk-btn")[0].dispatchEvent({ type: "click" });
  await flush();
  await flush();

  const calls = env.sent.filter((m) => m.type === "fetchCovers");
  assert.equal(calls[1].seriesName, "Berserk Deluxe");
  assert.equal(field.value, "Berserk Deluxe", "la réponse ne doit pas réécrire la saisie");
});

test("après un premier chargement en échec, on redemande le nom au serveur", async () => {
  // `resolvedOnce` marqué avant de regarder le résultat faisait partir la
  // tentative suivante avec un nom VIDE — soit une recherche sur la chaîne
  // vide, au lieu de laisser le serveur résoudre.
  let call = 0;
  const env = arrange({
    protocol: "http:",
    routes: {
      fetchCovers: () => {
        call += 1;
        return call === 1
          ? { ok: false, error: "HTTP 503" }
          : { ok: true, covers: [], seriesName: "Vinland Saga" };
      },
    },
  });
  open(env, { seriesName: "Titre DOM" });
  await flush();
  await flush();

  env.shadow.byClass("mk-btn")[0].dispatchEvent({ type: "click" });
  await flush();
  await flush();

  const calls = env.sent.filter((m) => m.type === "fetchCovers");
  assert.equal(calls.length, 2);
  assert.equal(calls[1].seriesName, undefined, "le serveur doit encore résoudre");
  assert.equal(env.shadow.byClass("mk-cover-search")[0].value, "Vinland Saga");
});
