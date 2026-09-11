/**
 * Le répartiteur de messages.
 *
 * La chaîne de `if (msg.type === …)` qu'il remplace portait trois nuances que
 * rien ne verrouillait, et qui se seraient perdues à la traduction.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { installChrome, installFetch, reply } from "./helpers/fakes.mjs";
import { HANDLERS, dispatch } from "../lib/handlers/index.js";

test("un message malformé et un type inconnu ne se confondent pas", async () => {
  // Nu : l'appel n'a rien dit, il n'y a rien à répondre.
  assert.deepEqual(await dispatch(null), { ok: false });
  assert.deepEqual(await dispatch({}), { ok: false });
  assert.deepEqual(await dispatch({ type: "" }), { ok: false });
  // Motivé : l'extension et la page ont divergé, et l'UI le dit.
  assert.deepEqual(await dispatch({ type: "nExistePas" }), { ok: false, error: "unknown" });
});

test("un handler qui lève est rattrapé, il ne casse pas le canal", async () => {
  installChrome();
  // `enableKavitaOrigin` construit une URL depuis l'onglet émetteur, hors
  // try/catch : une URL illisible y lève pour de bon. Sans filet, la promesse
  // du listener partirait en rejet et le canal de message resterait ouvert
  // jusqu'à son expiration, sans réponse.
  const out = await dispatch({ type: "enableKavitaOrigin" }, { tab: { url: "pas-une-url" } });

  assert.equal(out.ok, false);
  assert.equal(typeof out.error, "string");
  assert.ok(out.error.length > 0, "l'échec doit être nommé, pas vide");
});

test("un échec réseau du webhook remonte en réponse, pas en exception", async () => {
  installChrome({ settings: { metaBaseUrl: "https://meta.example", webhookToken: "a" } });
  globalThis.fetch = async () => {
    throw new Error("réseau coupé");
  };

  const out = await dispatch({ type: "webhook", payload: { seriesId: 42 } });
  assert.equal(out.ok, false);
  assert.match(out.error, /réseau coupé/);
});

test("les clés héritées d'Object ne sont pas des messages", async () => {
  // `HANDLERS[msg.type]` sans garde rendait `constructor`, `toString`,
  // `__proto__`… donc un `handler` tronçonné appelé sur un message arbitraire.
  for (const type of ["constructor", "toString", "__proto__", "hasOwnProperty"]) {
    assert.deepEqual(
      await dispatch({ type }),
      { ok: false, error: "unknown" },
      `${type} ne doit pas être joignable comme message`
    );
  }
});

test("la table couvre exactement les messages que la page envoie", () => {
  // Un message retiré de la table sans être retiré des appelants tombe en
  // « unknown » à l'exécution, silencieusement.
  assert.deepEqual(Object.keys(HANDLERS).sort(), [
    "applyCover",
    "embedToken",
    "enableKavitaOrigin",
    "fetchCovers",
    "fetchImageData",
    "getSettings",
    "hasHostPermission",
    "pendingEnable",
    "requestHostPermission",
    "saveSettings",
    "seriesStatus",
    "testConnection",
    "uiBootstrap",
    "urlInfo",
    "webhook",
  ]);
});

test("saveSettings invalide les jetons d'embed détenus", async () => {
  // Changer d'adresse ou de jeton webhook rend caducs les jetons du cache.
  // Sans cette invalidation, le cover picker frapperait l'ancienne instance.
  const store = installChrome({ settings: { metaBaseUrl: "https://old.example", webhookToken: "a" } });
  let minted = 0;
  installFetch((url) => {
    if (url.includes("/companion/embed-token")) {
      minted += 1;
      return reply({ body: { embed_token: `tok-${minted}` } });
    }
    return reply({ body: { covers: [] } });
  });

  await dispatch({ type: "fetchCovers", seriesId: 1, seriesName: "x" });
  assert.equal(minted, 1);

  await dispatch({ type: "saveSettings", settings: { metaBaseUrl: "https://new.example" } });
  assert.equal(store.metaBaseUrl, "https://new.example");

  await dispatch({ type: "fetchCovers", seriesId: 1, seriesName: "x" });
  assert.equal(minted, 2, "le jeton de l'ancienne instance ne doit pas resservir");
});

test("le cover picker refuse d'agir hors d'un périmètre série", async () => {
  installChrome({ settings: { metaBaseUrl: "https://meta.example", webhookToken: "a" } });
  const calls = installFetch(() => reply({ body: {} }));

  for (const type of ["fetchCovers", "applyCover"]) {
    assert.deepEqual(await dispatch({ type }), { ok: false, error: "missing_series_id" });
    assert.deepEqual(await dispatch({ type, seriesId: 0 }), { ok: false, error: "missing_series_id" });
    assert.deepEqual(await dispatch({ type, seriesId: "abc" }), { ok: false, error: "missing_series_id" });
  }
  assert.equal(calls.length, 0, "aucun appel réseau sans série");
});

test("sans configuration, aucun handler réseau ne part", async () => {
  installChrome({ settings: { metaBaseUrl: "", webhookToken: "" } });
  const calls = installFetch(() => reply({ body: {} }));

  for (const msg of [
    { type: "embedToken", seriesId: 1 },
    { type: "fetchCovers", seriesId: 1 },
    { type: "applyCover", seriesId: 1 },
    { type: "fetchImageData", url: "/x.png" },
  ]) {
    assert.deepEqual(await dispatch(msg), { ok: false, error: "not_configured" }, msg.type);
  }
  assert.equal(calls.length, 0);
});
