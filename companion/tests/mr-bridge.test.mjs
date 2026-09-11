/**
 * Le pont `postMessage` de la Super Review.
 *
 * Remplace deux assertions textuelles qui figeaient le nom d'une variable
 * locale (`mrState`). Ici on injecte de vrais événements et on regarde ce que
 * la page fait — c'est le seul moyen de couvrir la branche « fenêtre dédiée »,
 * qui ne vérifiait NI l'origine NI l'émetteur alors que la documentation
 * affirmait le contraire.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { installChrome } from "./helpers/fakes.mjs";
import { loadContentScripts } from "./helpers/fake-dom.mjs";

const META = "https://meta.example";
const FILES = ["content/base.js", "content/overlay-mr.js"];

function arrange() {
  installChrome();
  const env = loadContentScripts({ files: FILES, chrome: globalThis.chrome });
  const win = env.window;
  const busted = [];
  win.__mkCompanionCacheBust = (sid) => busted.push(String(sid));
  return { ...env, win, busted };
}

function message({ source, origin = META, ...data }) {
  return { type: "message", source, origin, data: { source: "metakavita-companion", ...data } };
}

function openOverlay(win, extra = {}) {
  win.__mkCompanionOpenMr({
    url: `${META}/companion/embed?series_id=42`,
    metaOrigin: META,
    seriesId: 42,
    cacheBust: true,
    labels: { close: "Fermer", blocked: "Bloqué", openTab: "Onglet", timeout: "Délai" },
    ...extra,
  });
}

function iframeOf(env) {
  return env.shadow.find((n) => n.tagName === "IFRAME");
}

test("l'iframe ne reçoit d'ordres que de la bonne origine ET du bon émetteur", () => {
  const env = arrange();
  openOverlay(env.win);
  const iframe = iframeOf(env);
  iframe.contentWindow = { id: "embed" };
  const intrus = { id: "intrus" };

  // Bonne origine, mauvais émetteur : une autre iframe de la page Kavita.
  env.win.dispatchEvent(message({ source: intrus, type: "mk:mr-done", outcome: "confirm" }));
  assert.deepEqual(env.busted, [], "un émetteur inconnu ne déclenche rien");
  assert.ok(iframeOf(env), "et ne ferme pas l'overlay");

  // Bon émetteur, mauvaise origine : l'embed a été redirigé ailleurs.
  env.win.dispatchEvent(
    message({ source: iframe.contentWindow, origin: "https://evil.example", type: "mk:mr-done", outcome: "confirm" })
  );
  assert.deepEqual(env.busted, []);
  assert.ok(iframeOf(env));

  // Les deux bons : l'overlay se ferme et la jaquette se rafraîchit.
  env.win.dispatchEvent(message({ source: iframe.contentWindow, type: "mk:mr-done", outcome: "confirm" }));
  assert.deepEqual(env.busted, ["42"]);
  assert.equal(iframeOf(env), null, "l'overlay doit être détruit");
});

test("la fenêtre dédiée n'est écoutée que si c'est NOUS qui l'avons ouverte", () => {
  // Contenu mixte : pas d'iframe, la revue poste vers son opener. C'est la
  // branche qui n'avait aucun contrôle : n'importe quelle iframe de la page
  // pouvait poster un mk:mr-done.
  const env = arrange();
  const notre = { id: "la nôtre" };
  const autre = { id: "une autre" };

  env.win.dispatchEvent(message({ source: autre, type: "mk:mr-done", outcome: "confirm", seriesId: 42 }));
  assert.deepEqual(env.busted, [], "aucune fenêtre mémorisée : rien ne doit passer");

  env.win.__mkCompanionRememberReviewWindow(notre);
  env.win.dispatchEvent(message({ source: autre, type: "mk:mr-done", outcome: "confirm", seriesId: 42 }));
  assert.deepEqual(env.busted, [], "une fenêtre qui n'est pas la nôtre reste ignorée");

  env.win.dispatchEvent(message({ source: notre, type: "mk:mr-done", outcome: "confirm", seriesId: 42 }));
  assert.deepEqual(env.busted, ["42"]);
});

test("un message qui ne porte pas notre signature est ignoré", () => {
  const env = arrange();
  openOverlay(env.win);
  const iframe = iframeOf(env);
  iframe.contentWindow = { id: "embed" };

  env.win.dispatchEvent({
    type: "message",
    source: iframe.contentWindow,
    origin: META,
    data: { source: "autre-extension", type: "mk:mr-done", outcome: "confirm" },
  });
  assert.deepEqual(env.busted, []);
  assert.ok(iframeOf(env));
});

test("embed-ready annule le repli, et le délai le montre", () => {
  const env = arrange();
  openOverlay(env.win);
  const iframe = iframeOf(env);
  iframe.contentWindow = { id: "embed" };
  const fallback = env.shadow.byClass("mk-mr-fallback")[0];

  assert.equal(fallback.hidden, true, "le repli reste caché tant que rien n'a échoué");
  env.win.dispatchEvent(message({ source: iframe.contentWindow, type: "mk:embed-ready" }));
  assert.equal(fallback.hidden, true);
});

test("annuler ne rafraîchit pas la jaquette, confirmer oui", () => {
  const env = arrange();
  openOverlay(env.win);
  let iframe = iframeOf(env);
  iframe.contentWindow = { id: "embed" };

  env.win.dispatchEvent(message({ source: iframe.contentWindow, type: "mk:mr-done", outcome: "cancel" }));
  assert.deepEqual(env.busted, [], "une revue annulée n'a rien écrit");
  assert.equal(iframeOf(env), null, "mais l'overlay se ferme quand même");
});

test("cacheBust désactivé dans les réglages est respecté", () => {
  const env = arrange();
  openOverlay(env.win, { cacheBust: false });
  const iframe = iframeOf(env);
  iframe.contentWindow = { id: "embed" };

  env.win.dispatchEvent(message({ source: iframe.contentWindow, type: "mk:mr-done", outcome: "confirm" }));
  assert.deepEqual(env.busted, []);
});

test("ouvrir deux fois ne laisse qu'un overlay", () => {
  const env = arrange();
  openOverlay(env.win);
  openOverlay(env.win);

  assert.equal(env.shadow.findAll((n) => n.tagName === "IFRAME").length, 1);
});
