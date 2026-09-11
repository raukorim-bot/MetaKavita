/**
 * Ce que le service worker sert au content script, en remplacement des deux
 * copies que `content/page-ui.js` portait.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { installChrome } from "./helpers/fakes.mjs";
import { dispatch } from "../lib/handlers/index.js";
import { stringsFor } from "../lib/i18n.js";

test("uiBootstrap sert réglages, langue et table en un seul aller-retour", async () => {
  // Un seul appel : `t()` doit rester synchrone côté page, donc la table est
  // mise en cache au montage — pas redemandée à chaque libellé.
  installChrome({ settings: { uiLang: "fr", metaBaseUrl: "https://meta.example" } });

  const out = await dispatch({ type: "uiBootstrap" });
  assert.equal(out.ok, true);
  assert.equal(out.lang, "fr");
  assert.equal(out.settings.metaBaseUrl, "https://meta.example");
  assert.equal(out.strings.fabConfig, "Config");
  assert.equal(out.strings.coverPreviewFail, "Aperçu indisponible");
});

test("la table servie est complète et couvre les clés qui s'affichaient brutes", async () => {
  installChrome({ settings: { uiLang: "en" } });
  const out = await dispatch({ type: "uiBootstrap" });

  for (const key of ["toastMixedContentWindow", "coverPreviewFail", "coverPreviewLogin"]) {
    assert.ok(out.strings[key], `${key} doit être servie, pas affichée brute`);
  }
  assert.deepEqual(Object.keys(out.strings).sort(), Object.keys(stringsFor("en")).sort());
});

test("uiLang auto suit la langue du navigateur", async () => {
  installChrome({ settings: { uiLang: "auto" } });
  globalThis.chrome.i18n.getUILanguage = () => "fr-CA";
  assert.equal((await dispatch({ type: "uiBootstrap" })).lang, "fr");

  globalThis.chrome.i18n.getUILanguage = () => "de-DE";
  assert.equal((await dispatch({ type: "uiBootstrap" })).lang, "en", "repli anglais");
});

test("urlInfo normalise une saisie LAN sans schéma", async () => {
  installChrome();
  // Le bug historique : « localhost:5011 » passait pour le schéma « localhost: »,
  // origine nulle, et l'échec se présentait comme un refus de permission.
  const out = await dispatch({ type: "urlInfo", url: "localhost:5011" });

  assert.equal(out.base, "http://localhost:5011");
  assert.equal(out.origin, "http://localhost:5011");
  assert.notEqual(out.origin, "null");
});

test("urlInfo extrait le jeton d'une URL de webhook collée, et réduit à la racine", async () => {
  installChrome();
  const out = await dispatch({
    type: "urlInfo",
    url: "https://meta.example/webhook?token=abc%20def",
  });

  assert.equal(out.base, "https://meta.example", "le suffixe /webhook doit sauter");
  assert.equal(out.token, "abc def");
});

test("urlInfo distingue Kavita de Meta derrière un même hôte", async () => {
  // Issue #34 : reverse proxy, https://host/kavita et https://host/metakavita.
  installChrome();
  const meta = "https://host.example/metakavita";

  const kavita = await dispatch({
    type: "urlInfo",
    url: meta,
    pageUrl: "https://host.example/kavita/library/1/series/42",
    metaBaseUrl: meta,
  });
  assert.equal(kavita.isMeta, false, "une fiche série Kavita n'est pas MetaKavita");

  const dashboard = await dispatch({
    type: "urlInfo",
    url: meta,
    pageUrl: "https://host.example/metakavita/",
    metaBaseUrl: meta,
  });
  assert.equal(dashboard.isMeta, true);
});

test("sans pageUrl, urlInfo ne prétend pas trancher", async () => {
  installChrome({ settings: { metaBaseUrl: "https://meta.example" } });
  const out = await dispatch({ type: "urlInfo", url: "https://meta.example" });

  assert.equal(out.isMeta, false);
});
