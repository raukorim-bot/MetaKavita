/**
 * L'état d'une série, et la pastille qui le montre.
 *
 * C'est la seule information que le Companion donne sans qu'on ouvre le menu.
 * Elle doit donc être juste, se taire quand elle ne sait pas, et ne jamais
 * peindre l'état d'une série qu'on vient de quitter.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { installChrome, installFetch, reply } from "./helpers/fakes.mjs";
import { loadContentScripts } from "./helpers/fake-dom.mjs";
import { WATCH_FILES } from "../lib/watch-files.js";
import { badgeFor } from "../lib/handlers/status.js";
import { dispatch } from "../lib/handlers/index.js";

const META = "https://meta.example";
const CONFIGURED = { metaBaseUrl: META, webhookToken: "w-secret" };
const BADGE_STRINGS = {
  fabLogo: "Ouvrir le menu MetaKavita",
  badgeDone: "à jour",
  badgeWorking: "en cours de traitement",
  badgePending: "en attente d’enrichissement",
  badgeIgnored: "ignorée",
  badgeUnknown: "inconnue de MetaKavita",
};

// --- La règle de couleur, testée sans DOM ---------------------------------

test("une série que MetaKavita n'a jamais vue se dit inconnue", () => {
  assert.equal(badgeFor({ known: false }), "unknown");
  assert.equal(badgeFor(null), "unknown");
  assert.equal(badgeFor({}), "unknown");
});

test("l'état le plus actuel l'emporte sur l'état le plus ancien", () => {
  // Une série en file peut porter un « COMPLETED » d'une passe précédente, et
  // une série ignorée peut porter n'importe quoi. On annonce ce qui se passe
  // MAINTENANT, pas ce qui s'est passé.
  assert.equal(badgeFor({ known: true, status: "COMPLETED", queued: true }), "working");
  assert.equal(badgeFor({ known: true, status: "COMPLETED", running: true }), "working");
  assert.equal(badgeFor({ known: true, status: "COMPLETED", pending_review: true }), "working");
  assert.equal(badgeFor({ known: true, status: "COMPLETED", inventory_excluded: true }), "ignored");
  assert.equal(badgeFor({ known: true, status: "IGNORED", queued: true }), "ignored");
});

test("traitée veut dire trouvée OU explicitement introuvable", () => {
  assert.equal(badgeFor({ known: true, status: "COMPLETED" }), "done");
  // « Pas trouvée » est une conclusion, pas une attente : MetaKavita a cherché.
  assert.equal(badgeFor({ known: true, status: "NOT_FOUND" }), "done");
  assert.equal(badgeFor({ known: true, status: "PENDING" }), "pending");
  assert.equal(badgeFor({ known: true, status: null }), "pending");
});

// --- Le handler ------------------------------------------------------------

function arrange({ status = 200, body = null } = {}) {
  installChrome({ settings: CONFIGURED });
  return installFetch((url) =>
    url.includes("/companion/series/")
      ? reply({ ok: status < 400, status, body: body ?? { success: true, series_id: 42, known: true, status: "COMPLETED" } })
      : null
  );
}

test("le jeton webhook part en en-tête, jamais dans l'URL", async () => {
  const calls = arrange();
  await dispatch({ type: "seriesStatus", seriesId: 42 });

  const [call] = calls;
  assert.equal(call.headers["X-Webhook-Token"], "w-secret");
  assert.ok(!call.url.includes("w-secret"), "un jeton en query finit dans les journaux du proxy");
  assert.equal(call.url, `${META}/companion/series/42/status`);
});

test("une instance trop ancienne fait taire la pastille, pas planter le menu", async () => {
  // La route n'existe pas avant 1.7.3 : 404. Ce n'est pas une panne.
  arrange({ status: 404 });
  const res = await dispatch({ type: "seriesStatus", seriesId: 42 });

  assert.deepEqual(res, { ok: false, error: "unsupported" });
});

test("une réponse illisible est refusée plutôt qu'interprétée", async () => {
  arrange({ body: { success: false } });
  assert.equal((await dispatch({ type: "seriesStatus", seriesId: 42 })).error, "bad_payload");
});

test("sans configuration, rien ne part", async () => {
  installChrome({ settings: { metaBaseUrl: "", webhookToken: "" } });
  const calls = installFetch(() => reply({}));
  assert.deepEqual(await dispatch({ type: "seriesStatus", seriesId: 42 }), {
    ok: false,
    error: "not_configured",
  });
  assert.equal(calls.length, 0);
});

// --- La pastille dans la page ---------------------------------------------

async function mountWith(statusBody, { uiMode = "expert" } = {}) {
  installChrome({ settings: CONFIGURED });
  globalThis.chrome.runtime.sendMessage = async (msg) => {
    if (msg.type === "uiBootstrap") {
      return { ok: true, lang: "fr", uiMode, strings: BADGE_STRINGS, settings: CONFIGURED };
    }
    if (msg.type === "seriesStatus") {
      return statusBody
        ? { ok: true, status: statusBody, badge: badgeFor(statusBody) }
        : { ok: false, error: "unsupported" };
    }
    return { ok: true };
  };
  const env = loadContentScripts({ files: WATCH_FILES, chrome: globalThis.chrome, protocol: "http:" });
  await env.window.__mkCompanionPageUI.mount("42");
  await new Promise((r) => setTimeout(r, 10));
  const host = env.document.documentElement.childNodes.find((n) => n.id === "mk-companion-page-host");
  return { ...env, shadow: host._shadow };
}

const logo = (env) => env.shadow.getElementById("btnLogo");

test("la pastille prend la couleur de l'état", async () => {
  const done = await mountWith({ known: true, status: "COMPLETED" });
  assert.equal(logo(done).getAttribute("data-state"), "done");

  const ignored = await mountWith({ known: true, status: "IGNORED" });
  assert.equal(logo(ignored).getAttribute("data-state"), "ignored");

  const working = await mountWith({ known: true, status: "PENDING", queued: true });
  assert.equal(logo(working).getAttribute("data-state"), "working");
});

test("sur une instance qui ne sait pas répondre, il n'y a pas de pastille", async () => {
  const env = await mountWith(null);
  assert.equal(logo(env).getAttribute("data-state"), null, "pas de pastille, pas d'erreur");
});

test("l'état part aussi dans le nom accessible", async () => {
  // Une pastille qui n'existe qu'en couleur ne dit rien à qui ne la voit pas.
  const env = await mountWith({ known: true, status: "IGNORED" });
  const label = logo(env).getAttribute("aria-label");
  assert.ok(label.includes("ignorée"), label);
  assert.ok(logo(env).title.includes("ignorée"), logo(env).title);
});

test("les tomes coupés retirent le bouton Atelier", async () => {
  // Il mène à un 403 : mieux vaut pas de bouton qu'un bouton qui échoue.
  const off = await mountWith({ known: true, status: "COMPLETED", volumes_enabled: false });
  assert.equal(off.shadow.getElementById("btnWorkshop").style.display, "none");

  const on = await mountWith({ known: true, status: "COMPLETED", volumes_enabled: true });
  assert.notEqual(on.shadow.getElementById("btnWorkshop").style.display, "none");
});

test("tant que le serveur n'a rien dit, on ne présume pas de ce qu'il sait faire", async () => {
  const env = await mountWith(null);
  assert.notEqual(
    env.shadow.getElementById("btnWorkshop").style.display,
    "none",
    "une instance muette garde ses boutons"
  );
});
