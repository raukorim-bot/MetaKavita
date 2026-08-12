# MetaKavita Companion — Developer notes

Technical overview for contributors working on the extension. End-user install steps live in [README.md](./README.md).

## Layout

```
companion/
├── manifest.json              # Chrome / Edge MV3
├── manifest.firefox.json      # Firefox variant (copied over as manifest.json when packing)
├── background.js              # Service worker: settings, permissions, webhook, embed token, covers
├── options.html|js|css        # Toolbar popup + options page
├── content/
│   ├── page-ui.js             # Shadow DOM FABs + config panel (injected into Kavita)
│   └── watch.js               # Series URL watch, MR/cover panels, SPA navigation
├── lib/                       # storage, permissions, webhook, i18n
├── icons/
├── _locales/
├── scripts/                   # pack.mjs + self-checks run in CI
└── dist/                      # Generated artifacts (not source of truth)
```

**Only UI path:** `content/page-ui.js` + `content/watch.js` injected as registered content scripts on enabled Kavita origins. The `overlay/` iframe that predated them was removed in 1.0.27 — nothing loaded it any more, yet it kept shipping in both zips along with the unauthenticated `postMessage` bridge that served it.

**Two rules the self-checks enforce** (`node companion/scripts/selfcheck-i18n.mjs`, `verify-dist.mjs`, both wired into `.github/workflows/tests.yml`):

- `content/page-ui.js` is a classic content script, so it cannot import `lib/i18n.js` and carries a copy of the FR/EN tables. The two copies must stay identical — a drift is what made three keys render as raw identifiers.
- `dist/*.zip` is what users sideload and it is built by hand. Repack (`node companion/scripts/pack.mjs`) in the same commit as any source change.

**Secrets in the page:** the config panel lives in a **closed** shadow root, and the webhook token is written into its field only while the panel is open. An open shadow root is reachable from the page through `host.shadowRoot`; the isolated world protects our variables, not the nodes we insert.

## Runtime architecture

```
┌──────────────────── Kavita tab ────────────────────┐
│  content/page-ui.js   Shadow DOM FABs + Config     │
│  content/watch.js     seriesId watch, MR, covers   │
└─────────────── chrome.runtime.sendMessage ─────────┘
                        │
                        ▼
              background.js (service worker)
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
   MetaKavita      chrome.storage    chrome.permissions
   /webhook        settings          host grants
   /companion/*
```

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

## FAB menu (radial)

Implemented in `page-ui.js`:

- All action buttons are **identical 46px icon discs** (uniform footprint).
- Positions use closed-form arc math: chord length → radius, then `--x` / `--y` offsets from logo center.
- No CSS `rotate` chain for placement (avoids misalignment with variable-width pills).

When changing icons or diameter, update `FAB_DIAMETER` / `FAB_GAP` / `ARC_RANGES` together with the CSS `.fab` size.

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
| `fetchCovers` / `applyCover` | Cover pick APIs |
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

Bump **both** `manifest.json` and `manifest.firefox.json` `version` fields when shipping a user-visible change, and the version quoted in `README.md` (a test checks the three agree).

```bash
node companion/scripts/selfcheck-url-match.mjs   # URL detection + base URL normalisation
node companion/scripts/selfcheck-i18n.mjs        # the two FR/EN copies, and no key used without a translation
node companion/scripts/verify-dist.mjs           # the zips match the sources, versions agree
```

## Local debug tips

1. Load unpacked `companion/` (Chrome) for fast iteration; reload extension + hard-refresh Kavita after edits.
2. Inspect FABs: the host is `#mk-companion-page-host`. Its shadow root is **closed**, so `host.shadowRoot` is `null` from the console — use the Elements panel, which still shows it.
3. Permission failures from Config on the page: retry from the **toolbar popup** (`chrome.permissions` prompt is unreliable from content scripts).
4. Service worker logs: `chrome://extensions` → Companion → **Service worker** link.
5. After changing registered content scripts, disable/re-enable the Kavita site or reload the extension so `syncWatchRegistration` runs.

## MetaKavita server touchpoints

Companion expects MetaKavita to expose:

- `POST /webhook` with Companion flags (`seriesId`, `auto`, `super_review`, …)
- `GET/POST /companion/embed-token` (short-lived, series-scoped)
- `/companion/embed` (manual review UI for iframe or tab)
- Cover search/apply endpoints used by `fetchCovers` / `applyCover` (see `background.js`)

CSP / CSRF allowlists for embed token and companion routes live on the MetaKavita side (`companion_csp`, CSRF exemptions, etc.).

## Conventions

- Prefer small, focused diffs.
- User-facing copy: write it in `lib/i18n.js`, then mirror it verbatim into the `page-ui.js` tables (`selfcheck-i18n.mjs` refuses any divergence). `_locales/` only carries the extension name, description and a fallback subset.
- Do not commit secrets (tokens, `.env`).
- Do not add markdown docs unless asked — this file and README are the maintained docs.
