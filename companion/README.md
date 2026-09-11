# MetaKavita Companion

Browser extension for MetaKavita · Extension navigateur pour MetaKavita

---

## Sommaire / Table of Contents

1. [🇺🇸 English](#-english)
2. [🇫🇷 Français](#-français)

---

## 🇺🇸 English

> **Beta / early access** — sideload only. **Not published** on the Chrome Web Store or Firefox Add-ons (AMO). Aimed at early adopters; Companion APIs require MetaKavita **1.6.5+**.

MV3 extension (**Chrome / Edge / Firefox**) that adds a floating MetaKavita menu on Kavita **series** pages, with a status dot telling you where MetaKavita stands on the series you are looking at.

It comes in two flavours. **Simplified** offers what you do day to day, in plain words, and asks before anything overwrites your metadata. **Expert** puts all seven actions one click away, under their MetaKavita names, and never asks. A fresh install starts simplified; an install that is already paired stays expert.

Server prerequisites (MetaKavita **1.6.5+**): Companion webhook (`seriesId`, `auto`, `super_review`), routes `/companion/embed` and `/companion/embed-token`.

Current extension version: **1.0.29** (see `manifest.json`).

Ready-made zips (no rebuild):
- Chrome / Edge: [metakavita-companion-chrome.zip](https://github.com/raukorim-bot/MetaKavita/raw/main/companion/dist/metakavita-companion-chrome.zip)
- Firefox: [metakavita-companion-firefox.zip](https://github.com/raukorim-bot/MetaKavita/raw/main/companion/dist/metakavita-companion-firefox.zip)

### Project status

| Area | Status | Notes |
|------|--------|--------|
| Sideload Chrome / Edge / Firefox | **Dev / usable** | Zips via `node companion/scripts/pack.mjs` — not on stores yet |
| MetaKavita pairing (URL + token) | **Dev** | Popup / Config FAB; host permission via service worker |
| Kavita site activation | **Dev** | Origin remembered; content scripts registered dynamically |
| Series-page FABs (icon arc) | **Dev** | Shadow DOM in Kavita; only `/library/…/series/{id}` |
| In-page Super Review | **Dev** | `/companion/embed` iframe + embed token (same HTTP/HTTPS scheme) |
| Mixed-content Super Review | **Dev** | HTTPS Kavita + HTTP Meta → dedicated popup window (tab fallback); auto-close when done |
| Auto (webhook) | **Dev** | `auto` + `force` |
| Cover pick | **Dev** | Page overlay + cover APIs via background |
| Mixed-content cover previews | **Dev** | HTTPS Kavita + HTTP Meta → service worker fetch, inline `data:` image |
| Config / i18n FR·EN | **Dev** | |
| Chrome / Firefox stores | **Not published** | Sideload distribution only for now |

**Out of scope on purpose:** no FABs in the Kavita reader; no browser mixed-content bypass.

Technical docs: [DEVELOPER.md](./DEVELOPER.md) (extension) and [MetaKavita DEVELOPER.md § Companion](../DEVELOPER.md#13-metakavita-companion-c33). Also linked from MetaKavita **1.6.5** → **Help** menu.

### Installation

#### Chrome / Edge (recommended: zip)

1. Download [metakavita-companion-chrome.zip](https://github.com/raukorim-bot/MetaKavita/raw/main/companion/dist/metakavita-companion-chrome.zip)  
   (or rebuild locally: `node companion/scripts/pack.mjs`).
2. Extract the zip to a local folder.
3. Open `chrome://extensions` (or `edge://extensions`).
4. Enable **Developer mode**.
5. **Load unpacked** → select the extracted folder that contains `manifest.json`.

#### Firefox

1. Download [metakavita-companion-firefox.zip](https://github.com/raukorim-bot/MetaKavita/raw/main/companion/dist/metakavita-companion-firefox.zip)  
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
| Action | Behaviour | Simplified | Expert |
|--------|-----------|:---:|:---:|
| **Super Review** — *Complete this series* | Starts a `super_review` sync then opens Manual Review. Shows the candidates before anything is written. | ● | ● |
| **Cover** — *Change the cover* | Cover-picker overlay. The searched name comes from Kavita, not from the page. | ● | ● |
| **Auto** — *Complete without asking me* | Webhook `auto` + `force` — writes straight away, even if global Manual Review is on. | ○ asks first | ● |
| **Workshop** | Opens the volume Workshop for this series. Hidden when volume enrichment is off. | — | ● |
| **Open in MetaKavita** | The series sheet on the dashboard. | — | ● |
| **Config** | URL + token + local options. | ● | ● |
| **Buy me a coffee** | Discreet external link. | ● | ● |

### The status dot

The floating logo carries a dot, so you know without opening anything:

| Colour | Meaning |
|---|---|
| 🟢 | handled — enriched, or searched and not found |
| 🟡 | being processed, queued, or waiting in Manual Review |
| 🔵 | known to MetaKavita, not enriched yet |
| 🔴 | ignored |
| ⚫ | never seen by MetaKavita |

It needs MetaKavita **1.7.3+**. On an older instance there is simply no dot — nothing else changes.

#### Mixed content (HTTPS Kavita + HTTP MetaKavita)

Browsers block an HTTP iframe inside an HTTPS page, and no extension trick lifts that: the mixed-content check looks at the **top** frame, so hosting the iframe in an extension frame injected into Kavita is blocked exactly the same way. Only a top-level document escapes it.

So Companion opens Super Review in a **dedicated popup window** — chromeless, centered over Kavita, opened from the click itself (before any `await`) so the popup blocker leaves it alone. It keeps its `opener`, which is what lets the review focus Kavita and close its own window when it finishes. If the popup is blocked anyway, Companion falls back to a plain new tab.

Cover previews hit the same wall: covers that need the MetaKavita proxy (MangaDex, Anime-Planet…) are `http://…/api/proxy-image` thumbnails, blocked as mixed content. The service worker fetches them instead (it is not subject to the block) and returns an inline `data:` image to the page, so previews render on an HTTPS Kavita. The bridge only accepts URLs on the configured MetaKavita origin, only image responses, and caps at 8 MB.

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

Extension navigateur (**Chrome / Edge / Firefox**, Manifest V3) qui ajoute un menu flottant MetaKavita sur les **fiches série** Kavita, avec une pastille d'état qui dit où MetaKavita en est sur la série que vous regardez.

Elle existe en deux versions. **Simplifiée** : ce qu'on fait tous les jours, en français courant, et on vous demande avant d'écraser vos métadonnées. **Experte** : les sept actions à un clic, sous leurs noms MetaKavita, et on ne vous demande rien. Une installation neuve démarre en simplifiée ; une installation déjà appairée reste experte.

Prérequis côté serveur MetaKavita (**1.6.5**+) : webhook Companion (`seriesId`, `auto`, `super_review`), routes `/companion/embed` et `/companion/embed-token`.

Version extension courante : **1.0.29** (voir `manifest.json`).

Zips prêts (sans rebuild) :
- Chrome / Edge : [metakavita-companion-chrome.zip](https://github.com/raukorim-bot/MetaKavita/raw/main/companion/dist/metakavita-companion-chrome.zip)
- Firefox : [metakavita-companion-firefox.zip](https://github.com/raukorim-bot/MetaKavita/raw/main/companion/dist/metakavita-companion-firefox.zip)

### État du projet

| Domaine | Statut | Notes |
|--------|--------|--------|
| Sideload Chrome / Edge / Firefox | **Dev / utilisable** | Zips via `node companion/scripts/pack.mjs` — pas encore sur les stores |
| Pairing MetaKavita (URL + jeton) | **Dev** | Popup / Config FAB ; permission host via service worker |
| Activation site Kavita | **Dev** | Origine mémorisée ; content scripts enregistrés dynamiquement |
| FABs page série (arc icônes) | **Dev** | Shadow DOM dans Kavita ; uniquement `/library/…/series/{id}` |
| Super Review in-page | **Dev** | Iframe `/companion/embed` + embed token (même schéma HTTP/HTTPS) |
| Super Review contenu mixte | **Dev** | HTTPS Kavita + HTTP Meta → fenêtre dédiée (repli onglet) ; fermeture auto en fin de parcours |
| Auto (webhook) | **Dev** | `auto` + `force` |
| Cover pick | **Dev** | Overlay page + APIs covers via background |
| Previews cover contenu mixte | **Dev** | HTTPS Kavita + HTTP Meta → fetch service worker, image `data:` inline |
| Config / i18n FR·EN | **Dev** | |
| Stores Chrome / Firefox | **Non publié** | Distribution sideload uniquement pour l’instant |

**Hors scope volontaire :** pas de FABs dans le reader Kavita ; pas de contournement mixed-content navigateur.

Docs techniques : [DEVELOPER.md](./DEVELOPER.md) (extension) et [DEVELOPER.md MetaKavita § Companion](../DEVELOPER.md#13-metakavita-companion-c33-1). Aussi depuis MetaKavita **1.6.5** → menu **Aide**.

### Installation

#### Chrome / Edge (recommandé : zip)

1. Télécharger [metakavita-companion-chrome.zip](https://github.com/raukorim-bot/MetaKavita/raw/main/companion/dist/metakavita-companion-chrome.zip)  
   (ou rebuild local : `node companion/scripts/pack.mjs`).
2. Extraire le zip dans un dossier local.
3. Ouvrir `chrome://extensions` (ou `edge://extensions`).
4. Activer **Mode développeur**.
5. **Charger l’extension non empaquetée** → sélectionner le dossier extrait qui contient `manifest.json`.

#### Firefox

1. Télécharger [metakavita-companion-firefox.zip](https://github.com/raukorim-bot/MetaKavita/raw/main/companion/dist/metakavita-companion-firefox.zip)  
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
| Action | Comportement | Simplifiée | Experte |
|--------|----------------|:---:|:---:|
| **Super Review** — *Compléter cette série* | Lance un sync `super_review` puis ouvre Manual Review. Montre les candidats avant d'écrire quoi que ce soit. | ● | ● |
| **Cover** — *Changer la couverture* | Overlay de sélection. Le nom cherché vient de Kavita, pas de la page. | ● | ● |
| **Auto** — *Compléter sans me demander* | Webhook `auto` + `force` — écrit directement, même si Manual Review global est on. | ○ demande d'abord | ● |
| **Atelier** | Ouvre l'atelier des tomes de cette série. Masqué si l'enrichissement des tomes est coupé. | — | ● |
| **Ouvrir dans MetaKavita** | La fiche série du tableau de bord. | — | ● |
| **Config** | URL + jeton + options locales. | ● | ● |
| **Buy me a coffee** | Lien externe discret. | ● | ● |

### La pastille d'état

Le logo flottant porte une pastille, pour savoir sans rien ouvrir :

| Couleur | Ce que ça veut dire |
|---|---|
| 🟢 | traitée — enrichie, ou cherchée et non trouvée |
| 🟡 | en cours, en file, ou en attente de Manual Review |
| 🔵 | connue de MetaKavita, pas encore enrichie |
| 🔴 | ignorée |
| ⚫ | jamais vue par MetaKavita |

Elle demande MetaKavita **1.7.3+**. Sur une instance plus ancienne, il n'y a simplement pas de pastille — rien d'autre ne change.

#### Contenu mixte (HTTPS Kavita + HTTP MetaKavita)

Les navigateurs bloquent l’iframe HTTP dans une page HTTPS, et aucune astuce d’extension n’y échappe : le contrôle mixed-content regarde la frame **top**, donc héberger l’iframe dans une frame d’extension injectée dans Kavita est bloqué à l’identique. Seul un document top-level y échappe.

Companion ouvre donc Super Review dans une **fenêtre dédiée** — sans barre d’adresse, centrée sur Kavita, ouverte depuis le clic lui-même (avant tout `await`) pour que le bloqueur de popups la laisse passer. Elle conserve son `opener`, ce qui permet à la review de redonner le focus à Kavita et de fermer sa propre fenêtre en fin de parcours. Si la popup est bloquée malgré tout, Companion retombe sur un simple onglet.

Les previews de couvertures se heurtent au même mur : les covers qui passent par le proxy MetaKavita (MangaDex, Anime-Planet…) sont des miniatures `http://…/api/proxy-image`, bloquées comme contenu mixte. C’est donc le service worker qui les récupère (il n’est pas soumis au blocage) et qui renvoie une image `data:` inline à la page — les previews s’affichent même sur un Kavita HTTPS. Le pont n’accepte que des URLs de l’origine MetaKavita configurée, uniquement des réponses image, et plafonne à 8 Mo.

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
