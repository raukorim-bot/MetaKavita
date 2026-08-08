# MetaKavita Companion

Browser extension for MetaKavita · Extension navigateur pour MetaKavita

---

## Sommaire / Table of Contents

1. [🇺🇸 English](#-english)
2. [🇫🇷 Français](#-français)

---

## 🇺🇸 English

> **Beta / early access** — sideload only. **Not published** on the Chrome Web Store or Firefox Add-ons (AMO). Aimed at early adopters; Companion APIs require MetaKavita **1.6.5+**.

MV3 extension (**Chrome / Edge / Firefox**) that adds a floating MetaKavita menu on Kavita **series** pages: Super Review, Auto, Cover, Config, and a discreet *Buy me a coffee* link.

Server prerequisites (MetaKavita **1.6.5+**): Companion webhook (`seriesId`, `auto`, `super_review`), routes `/companion/embed` and `/companion/embed-token`.

Current extension version: **1.0.24** (see `manifest.json`).

Ready-made zips (no rebuild):
- Chrome / Edge: [metakavita-companion-chrome.zip](https://github.com/raukorim-bot/MetaKavita/raw/dev/companion/dist/metakavita-companion-chrome.zip)
- Firefox: [metakavita-companion-firefox.zip](https://github.com/raukorim-bot/MetaKavita/raw/dev/companion/dist/metakavita-companion-firefox.zip)

### Project status

| Area | Status | Notes |
|------|--------|--------|
| Sideload Chrome / Edge / Firefox | **Dev / usable** | Zips via `node companion/scripts/pack.mjs` — not on stores yet |
| MetaKavita pairing (URL + token) | **Dev** | Popup / Config FAB; host permission via service worker |
| Kavita site activation | **Dev** | Origin remembered; content scripts registered dynamically |
| Series-page FABs (icon arc) | **Dev** | Shadow DOM in Kavita; only `/library/…/series/{id}` |
| In-page Super Review | **Dev** | `/companion/embed` iframe + embed token (same HTTP/HTTPS scheme) |
| Mixed-content Super Review | **Dev** | HTTPS Kavita + HTTP Meta → new tab; auto-close when done |
| Auto (webhook) | **Dev** | `auto` + `force` |
| Cover pick | **Dev** | Page overlay + cover APIs via background |
| Config / i18n FR·EN | **Dev** | |
| Chrome / Firefox stores | **Not published** | Sideload distribution only for now |

**Out of scope on purpose:** no FABs in the Kavita reader; no browser mixed-content bypass.

Technical docs: [DEVELOPER.md](./DEVELOPER.md) (extension) and [MetaKavita DEVELOPER.md § Companion](../DEVELOPER.md#13-metakavita-companion-c33). Also linked from MetaKavita **1.6.5** → **Help** menu.

### Installation

#### Chrome / Edge (recommended: zip)

1. Download [metakavita-companion-chrome.zip](https://github.com/raukorim-bot/MetaKavita/raw/dev/companion/dist/metakavita-companion-chrome.zip)  
   (or rebuild locally: `node companion/scripts/pack.mjs`).
2. Extract the zip to a local folder.
3. Open `chrome://extensions` (or `edge://extensions`).
4. Enable **Developer mode**.
5. **Load unpacked** → select the extracted folder that contains `manifest.json`.

#### Firefox

1. Download [metakavita-companion-firefox.zip](https://github.com/raukorim-bot/MetaKavita/raw/dev/companion/dist/metakavita-companion-firefox.zip)  
   (or rebuild: `node companion/scripts/pack.mjs`).
2. Extract the zip.
3. `about:debugging` → **This Firefox** → **Load Temporary Add-on** → pick `manifest.json` from the extracted folder.

> Firefox temporary add-ons unload when the browser restarts — reload after each restart while testing.

### Pairing

1. Open the extension popup (or the **Config** FAB on a series page).
2. Enter the **MetaKavita URL** (e.g. `http://192.168.x.x:5000` or your public URL) and the **webhook token**.
3. Save — the extension requests host permission for that origin.
4. In Kavita, open a **series page** (`/library/{lib}/series/{id}`): the floating menu appears.

The webhook token is in MetaKavita → Configuration (webhook / Auto-Sync section).

### Features

| Action | Behaviour |
|--------|-----------|
| **Super Review** | Starts a `super_review` sync then opens Manual Review (embed iframe, or new tab if mixed content). |
| **Auto** | Webhook `auto` + `force` — one-shot write even if global Manual Review is on. |
| **Cover** | Cover-picker overlay (MetaKavita APIs via background). |
| **Config** | URL + token + local options. |
| **Buy me a coffee** | Discreet external link. |

#### Mixed content (HTTPS Kavita + HTTP MetaKavita)

Browsers block an HTTP iframe inside an HTTPS page. In that case Companion opens Super Review in a **new tab** (without `noopener`, so it can close itself). When the run finishes (standalone tab only), the tab closes and focus returns to Kavita.

#### Batch & MetaKavita config

- You do **not** need Manual Review / Super Review enabled in MetaKavita config: Companion buttons **override** those toggles for that run only.
- During a **batch**: Super Review / Auto run **after the in-flight job**, then **ahead of** the rest of the queue (current scrape is not interrupted).
- If the series is **already queued** (batch or otherwise), that pending job is **removed** (RAM + durable queue) and **replaced** by the Companion job with the right flags.

### Known limits

- No Kavita reader support (intentional).
- Not on Chrome Web Store / AMO yet (sideload only).
- MetaKavita **1.6.5+** required (Companion APIs).

### Development

See [DEVELOPER.md](./DEVELOPER.md). Pack zips:

```bash
node companion/scripts/pack.mjs
```

---

## 🇫🇷 Français

> **Bêta / early access** — sideload uniquement. **Pas publié** sur le Chrome Web Store ni sur Firefox Add-ons (AMO). Destiné aux early adopters ; l’API Companion nécessite MetaKavita **1.6.5+**.

Extension navigateur (**Chrome / Edge / Firefox**, Manifest V3) qui ajoute un menu flottant MetaKavita sur les **fiches série** Kavita : Super Review, Auto, Cover, Config, et un lien discret *Buy me a coffee*.

Prérequis côté serveur MetaKavita (**1.6.5**+) : webhook Companion (`seriesId`, `auto`, `super_review`), routes `/companion/embed` et `/companion/embed-token`.

Version extension courante : **1.0.24** (voir `manifest.json`).

Zips prêts (sans rebuild) :
- Chrome / Edge : [metakavita-companion-chrome.zip](https://github.com/raukorim-bot/MetaKavita/raw/dev/companion/dist/metakavita-companion-chrome.zip)
- Firefox : [metakavita-companion-firefox.zip](https://github.com/raukorim-bot/MetaKavita/raw/dev/companion/dist/metakavita-companion-firefox.zip)

### État du projet

| Domaine | Statut | Notes |
|--------|--------|--------|
| Sideload Chrome / Edge / Firefox | **Dev / utilisable** | Zips via `node companion/scripts/pack.mjs` — pas encore sur les stores |
| Pairing MetaKavita (URL + jeton) | **Dev** | Popup / Config FAB ; permission host via service worker |
| Activation site Kavita | **Dev** | Origine mémorisée ; content scripts enregistrés dynamiquement |
| FABs page série (arc icônes) | **Dev** | Shadow DOM dans Kavita ; uniquement `/library/…/series/{id}` |
| Super Review in-page | **Dev** | Iframe `/companion/embed` + embed token (même schéma HTTP/HTTPS) |
| Super Review contenu mixte | **Dev** | HTTPS Kavita + HTTP Meta → nouvel onglet ; fermeture auto en fin de parcours |
| Auto (webhook) | **Dev** | `auto` + `force` |
| Cover pick | **Dev** | Overlay page + APIs covers via background |
| Config / i18n FR·EN | **Dev** | |
| Stores Chrome / Firefox | **Non publié** | Distribution sideload uniquement pour l’instant |

**Hors scope volontaire :** pas de FABs dans le reader Kavita ; pas de contournement mixed-content navigateur.

Docs techniques : [DEVELOPER.md](./DEVELOPER.md) (extension) et [DEVELOPER.md MetaKavita § Companion](../DEVELOPER.md#13-metakavita-companion-c33-1). Aussi depuis MetaKavita **1.6.5** → menu **Aide**.

### Installation

#### Chrome / Edge (recommandé : zip)

1. Télécharger [metakavita-companion-chrome.zip](https://github.com/raukorim-bot/MetaKavita/raw/dev/companion/dist/metakavita-companion-chrome.zip)  
   (ou rebuild local : `node companion/scripts/pack.mjs`).
2. Extraire le zip dans un dossier local.
3. Ouvrir `chrome://extensions` (ou `edge://extensions`).
4. Activer **Mode développeur**.
5. **Charger l’extension non empaquetée** → sélectionner le dossier extrait qui contient `manifest.json`.

#### Firefox

1. Télécharger [metakavita-companion-firefox.zip](https://github.com/raukorim-bot/MetaKavita/raw/dev/companion/dist/metakavita-companion-firefox.zip)  
   (ou rebuild : `node companion/scripts/pack.mjs`).
2. Extraire le zip.
3. `about:debugging` → **Ce Firefox** → **Charger un module temporaire** → `manifest.json` du dossier extrait.

> Les modules temporaires Firefox se déchargent au redémarrage du navigateur — les recharger après chaque restart pendant les tests.

### Branchement (pairing)

1. Ouvrir la popup de l’extension (ou le FAB **Config** sur une fiche série).
2. Renseigner l’**URL MetaKavita** (ex. `http://192.168.x.x:5000` ou l’URL publique) et le **jeton webhook**.
3. Enregistrer — l’extension demande la permission d’hôte pour cette origine.
4. Sur Kavita, ouvrir une **fiche série** (`/library/{lib}/series/{id}`) : le menu flottant apparaît.

Le jeton webhook se trouve dans MetaKavita → Configuration (section webhook / Auto-Sync).

### Fonctions

| Action | Comportement |
|--------|----------------|
| **Super Review** | Lance un sync `super_review` puis ouvre Manual Review (iframe embed ou nouvel onglet si mixed content). |
| **Auto** | Webhook `auto` + `force` — écriture one-shot même si Manual Review global est on. |
| **Cover** | Overlay de sélection de couverture (APIs MetaKavita via background). |
| **Config** | URL + jeton + options locales. |
| **Buy me a coffee** | Lien externe discret. |

#### Contenu mixte (HTTPS Kavita + HTTP MetaKavita)

Les navigateurs bloquent l’iframe HTTP dans une page HTTPS. Dans ce cas Companion ouvre Super Review dans un **nouvel onglet** (sans `noopener`, pour pouvoir le fermer). En fin de parcours (standalone tab uniquement), l’onglet se ferme et le focus revient à Kavita.

#### Batch & configuration MetaKavita

- **Pas besoin** d’activer Manual Review / Super Review dans la config MetaKavita : les boutons Companion **passent outre** ces toggles pour ce run uniquement.
- Pendant un **batch** : Super Review / Auto passent **après le job en cours**, puis **avant** le reste de la file (pas d’interruption du scrape courant).
- Si la série est **déjà en file d’attente** (batch ou autre), ce job pending est **retiré** (RAM + file durable) et **remplacé** par le job Companion avec les bons flags.

### Limites connues

- Pas de support reader Kavita (volontaire).
- Pas encore sur Chrome Web Store / AMO (sideload uniquement).
- Serveur MetaKavita **1.6.5+** requis (APIs Companion).

### Développement

Voir [DEVELOPER.md](./DEVELOPER.md). Pack des zips :

```bash
node companion/scripts/pack.mjs
```
