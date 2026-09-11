/**
 * Le pont d'images : ce qui part RÉELLEMENT sur le réseau.
 *
 * Remplace les assertions qui figeaient les noms de variables locales `target`
 * et `embedToken` dans `background.js` — et va plus loin qu'elles : le jeton
 * absent de l'URL est vérifié sur la requête, pas sur le source.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { installChrome, installFetch, reply } from "./helpers/fakes.mjs";
import { fetchImageAsDataUrl } from "../lib/image-bridge.js";
import { forgetEmbedTokens } from "../lib/embed-token.js";

const BASE = "https://meta.example";
const SETTINGS = { metaBaseUrl: BASE, webhookToken: "hook-token" };

function arrange(imageReply = reply({ mime: "image/png", bytes: new Uint8Array([1, 2, 3, 4]) })) {
  installChrome();
  forgetEmbedTokens();
  return installFetch((url) =>
    url.includes("/companion/embed-token")
      ? reply({ body: { embed_token: "EMBED-SECRET" } })
      : imageReply
  );
}

function imageCall(calls) {
  return calls.find((c) => !c.url.includes("/companion/embed-token"));
}

test("le jeton d'embed part en en-tête et jamais dans l'URL demandée", async () => {
  const calls = arrange();
  const out = await fetchImageAsDataUrl(SETTINGS, {
    url: `${BASE}/api/proxy-image?u=x&embed_token=STALE`,
    seriesId: 42,
  });

  assert.equal(out.ok, true);
  const call = imageCall(calls);
  assert.equal(call.headers["X-Companion-Embed-Token"], "EMBED-SECRET");
  assert.ok(!call.url.includes("embed_token"), call.url);
  assert.ok(!call.url.includes("STALE"), "un jeton déjà présent dans l'URL est retiré");
});

test("les octets reviennent en data: URL, avec le bon type", async () => {
  arrange(reply({ mime: "image/webp", bytes: new Uint8Array([7, 7, 7]) }));
  const out = await fetchImageAsDataUrl(SETTINGS, { url: "/api/proxy-image?u=x", seriesId: 1 });

  assert.ok(out.dataUrl.startsWith("data:image/webp;base64,"), out.dataUrl.slice(0, 40));
});

test("une URL hors de l'origine MetaKavita est refusée avant tout appel", async () => {
  const calls = arrange();
  const out = await fetchImageAsDataUrl(SETTINGS, {
    url: "https://evil.example/steal.png",
    seriesId: 42,
  });

  assert.deepEqual(out, { ok: false, error: "not_meta_url" });
  assert.equal(imageCall(calls), undefined, "rien ne doit partir vers un tiers");
});

test("une redirection vers /login est nommée, pas déguisée en « pas une image »", async () => {
  // Un MetaKavita antérieur à l'acceptation du jeton sur /api/proxy-image
  // répond 302 → /login, que fetch suit jusqu'à une page HTML.
  arrange(reply({ url: `${BASE}/login?next=%2Fapi`, mime: "text/html" }));
  const out = await fetchImageAsDataUrl(SETTINGS, { url: "/api/proxy-image?u=x", seriesId: 1 });

  assert.deepEqual(out, { ok: false, error: "meta_login_required" });
});

test("une réponse qui n'est pas une image est refusée", async () => {
  arrange(reply({ mime: "text/html" }));
  const out = await fetchImageAsDataUrl(SETTINGS, { url: "/api/proxy-image?u=x", seriesId: 1 });

  assert.deepEqual(out, { ok: false, error: "not_an_image" });
});

test("le plafond de taille tient, et une réponse vide aussi", async () => {
  arrange(reply({ bytes: new Uint8Array(9 * 1024 * 1024) }));
  assert.deepEqual(
    await fetchImageAsDataUrl(SETTINGS, { url: "/api/proxy-image?u=x", seriesId: 1 }),
    { ok: false, error: "bad_size" }
  );

  arrange(reply({ bytes: new Uint8Array(0) }));
  assert.deepEqual(
    await fetchImageAsDataUrl(SETTINGS, { url: "/api/proxy-image?u=x", seriesId: 1 }),
    { ok: false, error: "bad_size" }
  );
});

test("sans configuration, rien ne part", async () => {
  const calls = arrange();
  assert.deepEqual(
    await fetchImageAsDataUrl({ metaBaseUrl: "", webhookToken: "" }, { url: "/x.png" }),
    { ok: false, error: "not_configured" }
  );
  assert.equal(calls.length, 0);
});

test("sans seriesId, la requête part sans jeton plutôt que d'en emprunter un", async () => {
  const calls = arrange();
  await fetchImageAsDataUrl(SETTINGS, { url: "/api/proxy-image?u=x" });

  const call = imageCall(calls);
  assert.equal(call.headers["X-Companion-Embed-Token"], undefined);
  assert.ok(
    !calls.some((c) => c.url.includes("/companion/embed-token")),
    "aucun jeton ne doit être émis pour une requête hors périmètre série"
  );
});
