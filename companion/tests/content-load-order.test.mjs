/**
 * La règle de couplage des content scripts.
 *
 * Ce sont cinq scripts CLASSIQUES exécutés à la suite dans le même monde isolé,
 * qui se parlent par des globales `window.__mkCompanion*`. Rien dans le langage
 * ne garantit l'ordre : un fichier qui lirait la globale d'un autre AU
 * CHARGEMENT casserait l'extension chez l'utilisateur, sans un mot.
 *
 * D'où la règle : on DÉFINIT au chargement, on ne LIT que dans un callback.
 * `watch.js` fait exception — elle amorce — et se charge donc en dernier.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { installChrome } from "./helpers/fakes.mjs";
import { loadContentScripts } from "./helpers/fake-dom.mjs";
import { WATCH_FILES } from "../lib/watch-files.js";

test("chaque script se charge SEUL sans rien exiger des autres", () => {
  // C'est la vérification de la règle : si un fichier lisait une globale au
  // chargement, il lèverait ici. Les tests des overlays, eux, les chargent par
  // paires — ceci couvre le cas dégradé.
  for (const file of WATCH_FILES) {
    installChrome();
    assert.doesNotThrow(
      () => loadContentScripts({ files: [file], chrome: globalThis.chrome }),
      `${file} ne doit dépendre de personne au chargement`
    );
  }
});

test("chargés dans l'ordre de production, tous les points d'entrée existent", () => {
  installChrome();
  const { window } = loadContentScripts({ files: WATCH_FILES, chrome: globalThis.chrome });

  for (const global of [
    "__mkCompanionShowToast",
    "__mkCompanionCacheBust",
    "__mkCompanionOpenMr",
    "__mkCompanionCloseMr",
    "__mkCompanionRememberReviewWindow",
    "__mkCompanionOpenCover",
    "__mkCompanionCloseCover",
  ]) {
    assert.equal(typeof window[global], "function", `${global} doit être défini`);
  }
});

test("watch.js est bien le dernier, et le seul à amorcer", () => {
  assert.ok(
    WATCH_FILES[WATCH_FILES.length - 1].endsWith("watch.js"),
    "watch.js lit les globales des autres : elle doit se charger après eux"
  );
});

test("un double chargement ne rejoue rien", () => {
  // `chrome.scripting.executeScript` peut réinjecter dans un onglet déjà servi
  // (voir `injectIntoOpenKavitaTabs`). Chaque fichier porte donc sa garde.
  installChrome();
  const env = loadContentScripts({ files: WATCH_FILES, chrome: globalThis.chrome });
  const before = env.window.__mkCompanionOpenCover;

  assert.doesNotThrow(() =>
    loadContentScripts({ files: WATCH_FILES, chrome: globalThis.chrome })
  );
  assert.equal(env.window.__mkCompanionOpenCover, before);
});

test("Échap ferme une seule couche à la fois, la plus haute d'abord", () => {
  installChrome();
  const { window, document } = loadContentScripts({
    files: WATCH_FILES,
    chrome: globalThis.chrome,
  });

  const closed = [];
  window.__mkCompanionCloseCover = () => {
    closed.push("cover");
    return true;
  };
  window.__mkCompanionCloseMr = () => {
    closed.push("mr");
    return true;
  };
  window.__mkCompanionPageUI = {
    closeTop() {
      closed.push("panel");
      return true;
    },
  };

  document.dispatchEvent({ type: "keydown", key: "Escape" });
  assert.deepEqual(closed, ["cover"], "le picker est au-dessus : il part seul");

  window.__mkCompanionCloseCover = () => false;
  document.dispatchEvent({ type: "keydown", key: "Escape" });
  assert.deepEqual(closed, ["cover", "mr"]);

  window.__mkCompanionCloseMr = () => false;
  document.dispatchEvent({ type: "keydown", key: "Escape" });
  assert.deepEqual(closed, ["cover", "mr", "panel"]);
});

test("une autre touche ne ferme rien", () => {
  installChrome();
  const { window, document } = loadContentScripts({
    files: WATCH_FILES,
    chrome: globalThis.chrome,
  });
  let calls = 0;
  window.__mkCompanionCloseCover = () => {
    calls += 1;
    return true;
  };

  document.dispatchEvent({ type: "keydown", key: "Enter" });
  assert.equal(calls, 0);
});
