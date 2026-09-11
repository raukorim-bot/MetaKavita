# MetaKavita Companion — Developer notes

Technical overview for contributors working on the extension. End-user install steps live in [README.md](./README.md).

## Layout

```
companion/
├── manifest.json              # Chrome / Edge MV3
├── manifest.firefox.json      # Firefox variant (copied over as manifest.json when packing)
├── background.js              # Service worker: lifecycle listeners + message dispatch (~75 lines)
├── options.html|js|css        # Toolbar popup + options page
├── content/                   # Classic scripts, injected in this order
│   ├── base.js                # Page toast + cover cache-bust
│   ├── page-ui.js             # Closed shadow root: FABs, config panel, overlay layers
│   ├── overlay-mr.js          # Super Review iframe + postMessage bridge
│   ├── overlay-cover.js       # Cover picker
│   └── watch.js               # SPA router only: mounts/unmounts, single Escape handler
├── lib/
│   ├── storage.js permissions.js webhook.js i18n.js version.js
│   ├── cover-url.js embed-token.js image-bridge.js origins.js watch-files.js
│   └── handlers/              # One per domain + index.js (the table and dispatcher)
├── icons/
├── _locales/                  # Extension name/description + the two emergency keys
├── scripts/                   # pack.mjs + self-checks run in CI
├── tests/                     # node:test — NOT packed (absent from INCLUDE, like scripts/)
└── dist/                      # Generated artifacts (not source of truth)
```

**Only UI path:** the five `content/*.js` injected as registered content scripts on enabled Kavita origins. The `overlay/` iframe that predated them was removed in 1.0.27 — nothing loaded it any more, yet it kept shipping in both zips along with the unauthenticated `postMessage` bridge that served it.

### The coupling rule for `content/`

These are five **classic** scripts run in sequence in the same isolated world. Nothing in the language guarantees the order, so:

> A file **defines** its globals at load time. It only **reads** another file's global from inside a callback (click, message, navigation).

`watch.js` is the sole exception — it bootstraps — and therefore loads last. `lib/watch-files.js` is the single source for that list (it used to be duplicated between `registerContentScripts` and `executeScript`), and the tests import it so they load the scripts in production order. Two tests enforce the rule: each file must load alone without throwing, and `WATCH_FILES` must equal `content/*.js`.

### Rules the checks enforce

- **No second copy.** `content/page-ui.js` used to carry its own FR/EN table *and* its own copy of four URL helpers. The table is now served by the worker (`uiBootstrap`) and the helpers live behind `urlInfo` — `selfcheck-i18n.mjs` now refuses a second `const FR = {` anywhere, and `test_companion_hardening.py` asserts each helper is defined exactly once.
- **No `import` under `content/`.** It survives packing and `verify-dist`, then breaks the extension at runtime, silently. The CI syntax pass is split in two for exactly this: classic for `content/**`, `--input-type=module` for `background.js` + `lib/**`.
- **`dist/*.zip` is built by hand.** Repack (`node companion/scripts/pack.mjs`) in the same commit as any source change — `verify-dist.mjs` compares byte for byte.

**Secrets in the page:** the config panel lives in a **closed** shadow root, and the webhook token is written into its field only while the panel is open. An open shadow root is reachable from the page through `host.shadowRoot`; the isolated world protects our variables, not the nodes we insert.

## Runtime architecture

```
┌──────────────────────── Kavita tab ────────────────────────┐
│  base.js        toast, cover cache-bust                    │
│  page-ui.js     closed shadow root, FABs, createOverlayLayer│
│  overlay-mr.js  Super Review + postMessage bridge          │
│  overlay-cover  cover picker                               │
│  watch.js       SPA router, Escape                         │
└──────────────── chrome.runtime.sendMessage ────────────────┘
                        │
                        ▼
              background.js → lib/handlers/index.js
                        │   (HANDLERS table + dispatch)
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
   MetaKavita      chrome.storage    chrome.permissions
   /webhook        settings          host grants
   /companion/*
```

**Handler signature:** a handler **returns** its response; it never receives `sendResponse`. That is what makes it verifiable outside a browser — a `sendResponse` parameter would force every test to simulate the message channel to observe anything.

**Overlays live in the closed shadow root.** The handle is never exposed: `page-ui.js` hands out `createOverlayLayer(name, onDestroy) → { node, destroy }`. Layers are **siblings of `.wrap`**, never inside it — `.fab-stack` carries a `transform`, and a transformed ancestor changes the containing block of a `position: fixed` child. Each layer re-declares `pointer-events` (`.wrap` sets it to `none`), and ids are scoped to the shadow root, so `document.getElementById` no longer finds anything of ours.

1. User enables a Kavita origin → stored in `kavitaOrigins` + host permission.
2. `background.js` registers content scripts via `chrome.scripting.registerContentScripts` for those origins.
3. On a **series detail** URL only (`/library/{id}/series/{id}` exact), `watch.js` mounts the page UI.
4. Actions go through the service worker (content scripts cannot use `chrome.permissions` reliably).

**Same-host reverse proxy (issue #34):** Kavita and Meta may share one origin
(`https://host/kavita` + `https://host/metakavita`). Do **not** compare origins alone —
use `isMetaKavitaUrl(pageUrl, metaBaseUrl)` (path prefix). Content scripts may inject on
the whole origin; FABs still only mount on Kavita series URLs.

## Series page detection

```js
// watch.js — series detail only (not reader subpaths)
/\/library\/(\d+)\/series\/(\d+)\/?$/
```

Does **not** match `/manga/…`, `/book/…`, `/chapter/…`. Leaving a series page unmounts the FABs.

## FAB menu (two-ring constellation)

`layoutConstellation(rings)` in `page-ui.js`. Discs in a ring share a diameter, which is what allows closed-form arc math (chord between two points on a circle) instead of a collision loop: every gap comes out equal.

- **Inner ring**, 46 px. Radius derived from the chord constraint — **137 px** for four items over `ARC_RANGES[4] = [98°, 174°]`.
- **Outer ring**, 38 px and dimmer. Radius = inner + `(46/2 + 38/2 + RING_GAP)` = **195 px**, floored by its own chord constraint.
- **Staggered:** both rings share the angular window; inner places at `i/(n−1)`, outer at `(i+0.5)/n`. For 4 + 3 that gives `98·123·149·174` and `111·136·161`.
- **Empty rings are dropped before radii are assigned.** That is what makes "hide the action buttons" work with no special case: the outer ring simply moves up to the inner radius.
- Below ~300 px on either axis the figure would not fit (it reaches 214 px from the logo centre, itself 48 px from the corner), so it falls back to a column — same DOM, no extra CSS.

When changing icons or diameters, update `FAB_DIAMETER`, `FAB_DIAMETER_OUTER`, `FAB_GAP`, `RING_GAP` and `ARC_RANGES` together with the CSS `.fab` / `.fab--outer` sizes. `companion/tests/constellation.test.mjs` measures overlap and interleaving, so a mismatch fails rather than merely looking wrong.

## Interface modes

`uiMode` is `simple` | `expert`, and it moves three things at once — not just the number of buttons:

| | Simplified | Expert |
|---|---|---|
| Buttons | 5 | 7 |
| Vocabulary | plain ("Complete this series") | product names ("Super Review") |
| `Auto` | outer ring, **asks first** | inner ring, fires on click |

`Auto` sends `force: true` and overwrites Kavita metadata with no confirmation and no visible undo. That makes it the **expert** gesture, not the simple one: "do it without asking" only makes sense once you trust the tool. In simplified mode it drops a ring and asks, offering a third way out — *See it before writing*, which switches to Super Review.

The confirmation lives in the shadow root, not in `window.confirm`: a browser dialog announces itself under **Kavita's** name, which would mean asking the user to authorise a write on behalf of a site that did not author it.

**`composeRings()` is the only place that decides which buttons exist.** It takes the mode, the "hide action buttons" checkbox and the server state (no Workshop when volume enrichment is off). Letting each of the three filter on its own side is exactly the mess the 1.1.0 refactor removed.

**No migration to run.** The mode is *derived* while the user has not chosen: an already-paired install lands in expert, a fresh one in simplified (`defaultUiMode` / `effectiveUiMode` in `lib/storage.js`). Deriving rather than writing means nothing to play once, and nothing to replay if storage is reset.

## Mixed content (important)

Browsers block **HTTPS page → HTTP iframe** (mixed active content). The extension **cannot** override that.

Detection (`page-ui.js`, decided before any `await` so the popup still counts as a user gesture):

```text
location.protocol === "https:"  &&  MetaKavita base is http:
  → toast
  → window.open(embedUrl)  // keep opener (no noopener)
```

Otherwise Super Review is injected in-page (`watch.js` → `#mk-companion-mr` iframe) using a short-lived **embed token**.

When the embed runs as a **top-level tab**, `manual_review.js` `companionNotifyDone()`:

1. `postMessage` `mk:mr-done` to `window.opener` (Kavita) for cover cache-bust
2. `opener.focus()` then `window.close()`

Do **not** open that tab with `noopener` — otherwise `window.close()` / `opener` usually fail.

Documented for users in [README.md](./README.md) (EN: *Mixed content*; FR: *Contenu mixte*). Server-side Companion overview: [../DEVELOPER.md §13](../DEVELOPER.md#13-metakavita-companion-c33).

**Proper fix for in-page MR:** serve MetaKavita over HTTPS (or use HTTP Kavita on LAN).

## Message protocol

### Content / options → background

| `type` | Purpose |
|--------|---------|
| `getSettings` / `saveSettings` | Companion settings |
| `testConnection` | Meta health + token |
| `enableKavitaOrigin` / `pendingEnable` | Persist Kavita origin + sync scripts |
| `hasHostPermission` / `requestHostPermission` | Host grants (via SW) |
| `webhook` | `POST` Meta `/webhook` |
| `embedToken` | Short-lived token for `/companion/embed` |
| `fetchCovers` / `applyCover` | Cover pick APIs (`series_name` **absent** = let the server resolve it) |
| `uiBootstrap` | Settings + resolved language + **the whole FR/EN table**, in one round trip |
| `urlInfo` | Normalises a typed URL (`base`, `origin`, `token`, `isMeta`) |
| `seriesStatus` | `GET /companion/series/<id>/status` — feeds the badge and hides Workshop |
| `fetchImageData` | Meta-origin image → inline `data:` URL (all `/api/proxy-image` previews, and any http image on an https page) |

**Embed tokens** are minted by `getEmbedToken()` and cached per `base|seriesId`
for 10 min (server TTL: 15 min), cleared on `saveSettings`. They travel in the
`X-Companion-Embed-Token` header, **never** in a URL the page can read: a
`display_url` carrying `?embed_token=` is a credential published in the DOM,
which is why proxied previews go through the worker rather than straight into
an `<img>`.

### Embed → page bridge (`postMessage`)

`watch.js` accepts messages from **one** sender: the MetaKavita embed, checked on
both `ev.origin` and `ev.source`. Any new message type must keep that check —
the removed overlay bridge took orders from any window and opened the URL it was
handed.

| `type` | Direction | Purpose |
|--------|-----------|---------|
| `mk:embed-ready` | embed → watch | MR loaded (cancels the blocked-iframe fallback) |
| `mk:mr-timeout` | embed → watch | Scrape took too long, toast on the Kavita page |
| `mk:mr-done` | embed → watch / opener | Review finished; cover cache-bust, close the panel or window |

Page UI also exposes helpers on `window`: `__mkCompanionPageUI`, `__mkCompanionShowToast`, `__mkCompanionOpenMr`, `__mkCompanionOpenCover`.

## Settings shape

See `lib/storage.js`:

- `metaBaseUrl`, `webhookToken`
- `showActionFabs`, `cacheBustOnConfirm`
- `uiLang`: `auto` | `fr` | `en`
- `kavitaOrigins[]` — enabled Kavita origins
- `pendingEnableOrigin` — optional handoff from popup

## Packing

```bash
node companion/scripts/pack.mjs
```

- Stages `dist/_chrome` and `dist/_firefox` (Firefox swaps in `manifest.firefox.json`).
- Writes:
  - `dist/metakavita-companion-chrome.zip`
  - `dist/metakavita-companion-firefox.zip`
- Deletes staging folders after zip.
- Zip entries always use `/` (pure Node writer). Do **not** use PowerShell `Compress-Archive` — it stores `\` and breaks unzip on Linux/macOS.
- Text entries are written with LF (`scripts/zip-bytes.mjs`), so the artifact does not depend on whether git checked the sources out with CRLF on the machine that packed them.

Bump **both** `manifest.json` and `manifest.firefox.json` `version` fields when shipping a user-visible change, and the version quoted in `README.md` (a test checks the three agree).

## Tests

```bash
node --test companion/tests/*.test.mjs           # behaviour — 105 tests, no npm dependency
node companion/scripts/selfcheck-url-match.mjs   # URL detection + base URL normalisation
node companion/scripts/selfcheck-i18n.mjs        # one table only, and no key used without a translation
node companion/scripts/verify-dist.mjs           # the zips match the sources, versions agree
```

`companion/tests/` uses `node:test` and is **not packed** (absent from `INCLUDE`, like `scripts/`); the `.mjs` extension also keeps it out of the CI `find … -name '*.js'`. Helpers stub the only browser surface the code touches: `helpers/fakes.mjs` for `chrome` and `fetch`, `helpers/fake-dom.mjs` for a ~200-line DOM plus a `node:vm` loader that runs the content scripts in a blank global — which is what files starting with `if (window.__mkCompanionWatch) return;` require.

⚠️ Do **not** use a real `Response` in a fetch stub: `res.url` is read-only and empty there, and `lib/image-bridge.js` tests it against `/\/login/` to name a redirect to the login page.

Server-side counterparts: `tests/test_companion_hardening.py` (scans **every shipped script**, not one file at a time), `tests/test_companion_embed_auth.py` (embed-token scope + the pre-login boundary of `/companion/series/<id>/status`), `tests/test_routes_series_cover.py` (who decides the searched name).

## Local debug tips

1. Load unpacked `companion/` (Chrome) for fast iteration; reload extension + hard-refresh Kavita after edits.
2. Inspect FABs: the host is `#mk-companion-page-host`. Its shadow root is **closed**, so `host.shadowRoot` is `null` from the console — use the Elements panel, which still shows it. To script against it from a throwaway page, wrap `Element.prototype.attachShadow` *before* loading the content scripts and stash the root; that trick belongs in a harness, never in the extension.
3. Permission failures from Config on the page: retry from the **toolbar popup** (`chrome.permissions` prompt is unreliable from content scripts).
4. Service worker logs: `chrome://extensions` → Companion → **Service worker** link.
5. After changing registered content scripts, disable/re-enable the Kavita site or reload the extension so `syncWatchRegistration` runs.

## MetaKavita server touchpoints

Companion expects MetaKavita to expose:

- `POST /webhook` with Companion flags (`seriesId`, `auto`, `super_review`, …)
- `GET/POST /companion/embed-token` (short-lived, series-scoped)
- `/companion/embed` (manual review UI for iframe or tab)
- `GET /companion/series/<id>/status` (**1.7.3+**, webhook-token auth) — feeds the badge and `volumes_enabled`. A 404 is read as "this instance does not know": no badge, no error, every button kept.
- `GET /healthz` — its body carries `version` and `commit`; Test connection reads them (`lib/version.js` compares **numerically**, so 1.7.10 comes after 1.7.9).
- Cover search/apply endpoints used by `fetchCovers` / `applyCover`. `series_name` **absent** means "resolve it yourself"; empty or set means "search exactly this".

CSP / CSRF allowlists for embed token and companion routes live on the MetaKavita side (`companion_csp`, CSRF exemptions, etc.).

## Conventions

- Prefer small, focused diffs.
- User-facing copy: write it in `lib/i18n.js`, and **only** there. The content scripts receive the table through `uiBootstrap`; `selfcheck-i18n.mjs` refuses a second `const FR = {` anywhere in the package. `_locales/` carries the extension name, the description, and the two keys `t()` falls back on when the round trip itself has just failed (`toastExtensionReloaded`, `toastNeedConfig`) — the only case where a translation must be reachable synchronously.
- Never show a technical reason to the user: `HTTP 500`, `embed_token_failed` and friends go to `console.warn`, and the UI shows a translated message.
- Do not commit secrets (tokens, `.env`).
- Do not add markdown docs unless asked — this file and README are the maintained docs.
