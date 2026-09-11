/**
 * Comparaison de versions serveur.
 *
 * Le piège classique — comparer des versions comme des chaînes — met 1.7.10
 * avant 1.7.9 et retire des fonctions à des instances parfaitement à jour.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { compareVersions, atLeast } from "../lib/version.js";

test("les segments se comparent en nombres, pas en texte", () => {
  assert.equal(compareVersions("1.7.10", "1.7.9"), 1, "1.7.10 vient APRÈS 1.7.9");
  assert.equal(compareVersions("1.10.0", "1.9.9"), 1);
  assert.equal(compareVersions("2.0.0", "1.99.99"), 1);
});

test("une version plus courte vaut la même complétée de zéros", () => {
  assert.equal(compareVersions("1.7", "1.7.0"), 0);
  assert.equal(compareVersions("1.7", "1.7.1"), -1);
  assert.equal(compareVersions("1.7.0.0", "1.7"), 0);
});

test("un suffixe de pré-version ne fait pas passer devant", () => {
  assert.equal(compareVersions("1.7.3-rc1", "1.7.3"), 0, "le serveur n'en publie pas, on ne s'y fie pas");
  assert.equal(compareVersions("1.7.3", "1.7.2"), 1);
});

test("atLeast tranche dans le bon sens", () => {
  assert.equal(atLeast("1.7.3", "1.7.3"), true);
  assert.equal(atLeast("1.7.4", "1.7.3"), true);
  assert.equal(atLeast("1.7.2", "1.7.3"), false);
  assert.equal(atLeast("1.6.5", "1.7.3"), false);
});

test("une version inconnue ne retire rien", () => {
  // Une instance qui n'annonce pas sa version garde ses boutons : le serveur
  // répondra 404 et la fonction se retirera d'elle-même. Mieux vaut une
  // fonction qui se tait qu'une fonction absente sans raison visible.
  assert.equal(atLeast("", "1.7.3"), true);
  assert.equal(atLeast(null, "1.7.3"), true);
  assert.equal(atLeast("   ", "1.7.3"), true);
});
