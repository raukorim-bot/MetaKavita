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
│   └── watch.js               # Series URL watch, MR/cover overlays, SPA navigation
├── overlay/                   # Legacy iframe UI (kept in sync for pack / WAR)
├── lib/                       # storage, permissions, webhook, i18n
├── icons/
├── _locales/
├── scripts/pack.mjs           # Builds Chrome + Firefox zips into dist/
└── dist/                      # Generated artifacts (not source of truth)
```

**Primary UI path today:** `content/page-ui.js` + `content/watch.js` injected as registered content scripts on enabled Kavita origins. Prefer editing `page-ui.js` / `watch.js`; keep `overlay/` behavior aligned when you change Super Review / mixed-content / FAB logic.

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

Detection (same idea in `page-ui.js` and `overlay.js`):

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

### Overlay / page bridge (`postMessage`)

Used when the legacy overlay iframe talks to `watch.js` (and for MR sizing):

| `type` | Direction | Purpose |
|--------|-----------|---------|
| `mk:set-box` | overlay → parent | Resize opaque extension iframe |
| `mk:page-toast` | overlay → parent | Toast on Kavita page (never inside opaque iframe) |
| `mk:open-mr` | → watch | Inject Super Review iframe in Kavita |
| `mk:open-mr-tab` | → watch / page | Open Super Review in a new tab (mixed content) |
| `mk:embed-ready` | embed → watch | MR ready / timeout handling |

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

Bump **both** `manifest.json` and `manifest.firefox.json` `version` fields when shipping a user-visible change.

## Local debug tips

1. Load unpacked `companion/` (Chrome) for fast iteration; reload extension + hard-refresh Kavita after edits.
2. Inspect FABs: the host is `#mk-companion-page-host` → open its **shadow root**.
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

- Prefer small, focused diffs; keep `page-ui.js` and `overlay/` in sync for Super Review / mixed content / FAB UX.
- User-facing copy: FR + EN in `page-ui.js` tables and/or `lib/i18n.js` + `_locales/`.
- Do not commit secrets (tokens, `.env`).
- Do not add markdown docs unless asked — this file and README are the maintained docs.
