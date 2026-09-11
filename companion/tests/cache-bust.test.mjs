/**
 * Le rafraîchissement de jaquette après une écriture.
 *
 * L'ancienne version testait `src.includes(String(seriesId))` : pour la série
 * 12, « seriesId=125 » correspondait. Et la clause `/api/image` faisait
 * re-télécharger TOUTES les images de la page — y compris le bandeau de
 * recommandations — à chaque confirmation.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { installChrome } from "./helpers/fakes.mjs";
import { loadContentScripts, FakeNode } from "./helpers/fake-dom.mjs";

const KAVITA = "https://kavita.example";

function arrange(srcs) {
  installChrome();
  const env = loadContentScripts({
    files: ["content/base.js"],
    chrome: globalThis.chrome,
    origin: KAVITA,
  });
  const imgs = srcs.map((src) => {
    const img = new FakeNode("img");
    img.setAttribute("src", src);
    Object.defineProperty(img, "src", {
      get() {
        return this.getAttribute("src");
      },
      set(v) {
        this.setAttribute("src", v);
      },
      configurable: true,
    });
    return img;
  });
  env.document.querySelectorAll = (sel) => (sel === "img[src]" ? imgs : []);
  return { ...env, imgs, bust: env.window.__mkCompanionCacheBust };
}

const busted = (img) => img.getAttribute("src").includes("_mkcb=");

test("seule la jaquette de LA série visée est rafraîchie", () => {
  const env = arrange([
    `${KAVITA}/api/image/series-cover?seriesId=12&apiKey=k`,
    `${KAVITA}/api/image/series-cover?seriesId=125&apiKey=k`,
    `${KAVITA}/api/image/chapter-cover?chapterId=12&apiKey=k`,
    `${KAVITA}/assets/images/logo-12.png`,
  ]);

  env.bust(12);

  assert.ok(busted(env.imgs[0]), "la série 12");
  assert.ok(!busted(env.imgs[1]), "la série 125 n'est pas la série 12");
  assert.ok(!busted(env.imgs[2]), "un chapitre dont l'id vaut 12 non plus");
  assert.ok(!busted(env.imgs[3]), "ni un logo dont le nom contient 12");
});

test("le bandeau de recommandations n'est pas re-téléchargé en entier", () => {
  // C'était le coût réel : la clause `/api/image` emportait toute la page.
  const strip = Array.from(
    { length: 20 },
    (_, i) => `${KAVITA}/api/image/series-cover?seriesId=${200 + i}&apiKey=k`
  );
  const env = arrange([`${KAVITA}/api/image/series-cover?seriesId=42&apiKey=k`, ...strip]);

  env.bust(42);

  assert.equal(env.imgs.filter(busted).length, 1);
});

test("un identifiant vide ou absent ne touche à rien", () => {
  const env = arrange([`${KAVITA}/api/image/series-cover?seriesId=12`]);

  env.bust("");
  env.bust(null);
  env.bust(undefined);

  assert.ok(!busted(env.imgs[0]));
});

test("le filet se déclenche quand aucune URL ne porte l'identifiant", () => {
  // Kavita peut changer la forme de ses URL. Plutôt que de ne rien rafraîchir,
  // on se rabat sur les jaquettes DE SÉRIE — pas sur toute image servie.
  const env = arrange([
    `${KAVITA}/api/image/series-cover/abc`,
    `${KAVITA}/api/image/volume-cover?volumeId=7`,
  ]);

  env.bust(42);

  assert.ok(busted(env.imgs[0]), "la jaquette de série sert de filet");
  assert.ok(!busted(env.imgs[1]), "une jaquette de tome n'en fait pas partie");
});

test("le paramètre anti-cache remplace le précédent au lieu de s'empiler", () => {
  const env = arrange([`${KAVITA}/api/image/series-cover?seriesId=12&_mkcb=111`]);

  env.bust(12);

  const src = env.imgs[0].getAttribute("src");
  assert.equal(src.match(/_mkcb=/g).length, 1, `deux confirmations ne doivent pas allonger l'URL : ${src}`);
});
