/**
 * `<img src>` est du DOM nu : la page Kavita le lit. Le jeton d'embed qui s'y
 * trouverait ouvrirait toutes les routes de review de sa série.
 *
 * Remplace les assertions textuelles qui figeaient le nom de la variable
 * locale `parsed` dans `background.js`.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { resolveCoverDisplayUrl } from "../lib/cover-url.js";

const META = "https://meta.example";

test("un jeton déjà posé par le serveur est retiré de l'URL absolue", () => {
  const out = resolveCoverDisplayUrl(
    `${META}/api/proxy-image?u=http%3A%2F%2Fx%2Fa.jpg&embed_token=SECRET`,
    "",
    META
  );
  assert.ok(!out.includes("embed_token"), out);
  assert.ok(!out.includes("SECRET"), out);
  assert.ok(out.includes("/api/proxy-image"), out);
});

test("une display_url relative est absolutisée sur MetaKavita, pas sur Kavita", () => {
  const out = resolveCoverDisplayUrl("/api/proxy-image?u=x", "", META);
  assert.equal(new URL(out).origin, META);
});

test("le jeton est retiré même quand l'URL vient d'être absolutisée", () => {
  const out = resolveCoverDisplayUrl("/api/proxy-image?u=x&embed_token=SECRET", "", META);
  assert.ok(!out.includes("SECRET"), out);
});

test("une instance servie sous un sous-chemin garde ce sous-chemin", () => {
  const base = "https://host.example/metakavita";
  // Le chemin est déjà porté par l'URL relative : ne pas le doubler.
  assert.equal(
    resolveCoverDisplayUrl("/metakavita/api/proxy-image?u=x", "", base),
    "https://host.example/metakavita/api/proxy-image?u=x"
  );
  // Le chemin manque : il est ajouté.
  assert.equal(
    resolveCoverDisplayUrl("/api/proxy-image?u=x", "", base),
    "https://host.example/metakavita/api/proxy-image?u=x"
  );
});

test("on retombe sur url quand display_url manque, et sur vide quand tout manque", () => {
  assert.equal(resolveCoverDisplayUrl("", "https://cdn.example/c.jpg", META), "https://cdn.example/c.jpg");
  assert.equal(resolveCoverDisplayUrl("", "", META), "");
  assert.equal(resolveCoverDisplayUrl(null, undefined, META), "");
});
