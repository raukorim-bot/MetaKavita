/**
 * Un jeton par série, réutilisé tant qu'il vit.
 *
 * Remplace `bg.count("mintEmbedToken(") == 2`, qui comptait des occurrences
 * dans le source : un `export` + un `import` suffisaient à le faire échouer, et
 * il ne disait rien du nombre réel de jetons émis. Ici on compte les requêtes.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { installChrome, installFetch, reply } from "./helpers/fakes.mjs";
import {
  mintEmbedToken,
  getEmbedToken,
  forgetEmbedTokens,
  EMBED_TOKEN_REUSE_MS,
} from "../lib/embed-token.js";

const BASE = "https://meta.example";
const WEBHOOK = "hook-token";

function arrange() {
  installChrome();
  let minted = 0;
  const calls = installFetch((url) => {
    if (!url.includes("/companion/embed-token")) return null;
    minted += 1;
    return reply({ body: { embed_token: `tok-${minted}`, series_id: 1 } });
  });
  forgetEmbedTokens(); // le cache est un Map de module : repartir de zéro
  return { calls, minted: () => minted };
}

test("une grille entière de couvertures ne coûte qu'un seul jeton", async () => {
  const ctx = arrange();
  // 1 appel pour la liste + 12 aperçus, sur la même série.
  const tokens = [];
  for (let i = 0; i < 13; i += 1) tokens.push(await getEmbedToken(BASE, WEBHOOK, 42));

  assert.equal(ctx.minted(), 1, "un seul jeton pour toute la grille");
  assert.deepEqual([...new Set(tokens)], ["tok-1"]);
});

test("deux séries sont deux périmètres, donc deux jetons", async () => {
  const ctx = arrange();
  const a = await getEmbedToken(BASE, WEBHOOK, 42);
  const b = await getEmbedToken(BASE, WEBHOOK, 43);

  assert.equal(ctx.minted(), 2);
  assert.notEqual(a, b, "un jeton de la série 42 n'ouvre pas la série 43");
});

test("changer d'adresse ou de jeton webhook invalide ce qu'on détient", async () => {
  const ctx = arrange();
  await getEmbedToken(BASE, WEBHOOK, 42);
  forgetEmbedTokens();
  await getEmbedToken(BASE, WEBHOOK, 42);

  assert.equal(ctx.minted(), 2, "après invalidation, le jeton suivant est refrappé");
});

test("un échec d'émission n'est pas mis en cache", async () => {
  installChrome();
  let attempts = 0;
  installFetch((url) => {
    if (!url.includes("/companion/embed-token")) return null;
    attempts += 1;
    return reply({ ok: false, status: 401, body: {} });
  });
  forgetEmbedTokens();

  assert.equal(await getEmbedToken(BASE, WEBHOOK, 7), "");
  assert.equal(await getEmbedToken(BASE, WEBHOOK, 7), "");
  assert.equal(attempts, 2, "un refus ne doit pas condamner la série pendant 10 min");
});

test("le jeton expire avant celui du serveur", () => {
  // L'invariant est le rapport au TTL serveur (15 min, DEFAULT_TTL_SEC dans
  // services/companion_embed_auth.py), pas la valeur elle-même : un jeton qui
  // survivrait au serveur mourrait en vol, au milieu d'une revue.
  assert.ok(
    EMBED_TOKEN_REUSE_MS < 15 * 60 * 1000,
    `réutilisation ${EMBED_TOKEN_REUSE_MS} ms — le serveur les révoque à 15 min`
  );
  // Et le serveur, symétriquement, ne peut pas descendre sous cette valeur.
  assert.ok(EMBED_TOKEN_REUSE_MS >= 5 * 60 * 1000, "refrapper à chaque aperçu annule le cache");
});

test("le jeton part en en-tête webhook, jamais en query", async () => {
  const ctx = arrange();
  await getEmbedToken(BASE, WEBHOOK, 42);

  const [call] = ctx.calls;
  assert.equal(call.method, "POST");
  assert.ok(!call.url.includes(WEBHOOK), "le jeton webhook n'a rien à faire dans l'URL");
  assert.equal(call.headers["X-Webhook-Token"], WEBHOOK);
});

test("la Super Review reçoit un jeton frais, jamais un jeton déjà entamé", async () => {
  const ctx = arrange();
  // Un aperçu a déjà mis un jeton en cache pour cette série…
  await getEmbedToken(BASE, WEBHOOK, 42);
  // …la revue en demande quand même un neuf : elle dure plus longtemps.
  const minted = await mintEmbedToken(BASE, WEBHOOK, 42);

  assert.equal(ctx.minted(), 2);
  assert.equal(minted.ok, true);
  assert.equal(minted.token, "tok-2", "un jeton du cache aurait pu mourir en pleine revue");
});

test("un refus d'émission remonte son motif, il n'est pas aplati en chaîne vide", async () => {
  installChrome();
  installFetch(() => reply({ ok: false, status: 401, body: { code: "unauthorized", message: "Unauthorized" } }));
  forgetEmbedTokens();

  const out = await mintEmbedToken(BASE, "mauvais-jeton", 42);
  assert.equal(out.ok, false);
  assert.equal(out.status, 401);
  assert.equal(out.code, "unauthorized");
  // Sans ce détail, l'atelier ouvrirait le panneau de config sur un jeton
  // simplement refusé — deux pannes très différentes.
  assert.notEqual(out.error, "not_configured");
});

test("une panne réseau ne lève pas, elle se raconte", async () => {
  installChrome();
  globalThis.fetch = async () => { throw new Error("Failed to fetch"); };
  forgetEmbedTokens();

  const out = await mintEmbedToken(BASE, WEBHOOK, 42);
  assert.equal(out.ok, false);
  assert.match(out.error, /Failed to fetch/);
});
