# MetaKavita Companion

> **Bêta / early access** — sideload uniquement. **Pas publié** sur le Chrome Web Store ni sur Firefox Add-ons (AMO). Destiné aux early adopters ; l’API Companion nécessite MetaKavita **1.6.5+**.

Extension navigateur (**Chrome / Edge / Firefox**, Manifest V3) qui ajoute un menu flottant MetaKavita sur les **fiches série** Kavita : Super Review, Auto, Cover, Config, et un lien discret *Buy me a coffee*.

Prérequis côté serveur MetaKavita (**1.6.5**+) : webhook Companion (`seriesId`, `auto`, `super_review`), routes `/companion/embed` et `/companion/embed-token`.

Version extension courante : **1.0.22** (voir `manifest.json`).

Zips prêts (sans rebuild) :
- Chrome / Edge : [metakavita-companion-chrome.zip](https://github.com/raukorim-bot/MetaKavita/raw/dev/companion/dist/metakavita-companion-chrome.zip)
- Firefox : [metakavita-companion-firefox.zip](https://github.com/raukorim-bot/MetaKavita/raw/dev/companion/dist/metakavita-companion-firefox.zip)

---

## État du projet

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
| Anime-Planet covers | **Reporté** | Problème CDN / scraper — hors Companion |

**Hors scope volontaire :** pas de FABs dans le reader Kavita ; pas de contournement mixed-content navigateur.

Docs techniques : [DEVELOPER.md](./DEVELOPER.md). Lien aussi depuis MetaKavita **1.6.5** → menu **Aide**.

---

## Installation

### Chrome / Edge (recommandé : zip)

1. Télécharger [metakavita-companion-chrome.zip](https://github.com/raukorim-bot/MetaKavita/raw/dev/companion/dist/metakavita-companion-chrome.zip)  
   (ou rebuild local : `node companion/scripts/pack.mjs`).
2. Extraire le zip dans un dossier local.
3. Ouvrir `chrome://extensions` (ou `edge://extensions`).
4. Activer **Mode développeur**.
5. **Charger l’extension non empaquetée** → sélectionner le dossier extrait (celui qui contient `manifest.json`).

### Firefox

1. Télécharger [metakavita-companion-firefox.zip](https://github.com/raukorim-bot/MetaKavita/raw/dev/companion/dist/metakavita-companion-firefox.zip)  
   (ou rebuild : `node companion/scripts/pack.mjs`).
2. Extraire le zip.
3. `about:debugging` → **Ce Firefox** → **Charger un module temporaire** → `manifest.json` du dossier extrait.

> Firefox temporary add-ons are unloaded when the browser restarts — reload after each restart while testing.

---

## Configuration (pairing)

1. Ouvrir la popup de l’extension (ou le FAB **Config** sur une fiche série).
2. Renseigner l’**URL MetaKavita** (ex. `http://192.168.x.x:5000` ou l’URL publique) et le **jeton webhook**.
3. Enregistrer — l’extension demande la permission d’hôte pour cette origine.
4. Sur Kavita, ouvrir une **fiche série** (`/library/{lib}/series/{id}`) : le menu flottant apparaît.

Le jeton webhook se trouve dans MetaKavita → Configuration (section webhook / Auto-Sync).

---

## Fonctions

| Action | Comportement |
|--------|----------------|
| **Super Review** | Lance un sync `super_review` puis ouvre Manual Review (iframe embed ou nouvel onglet si mixed content). |
| **Auto** | Webhook `auto` + `force` — écriture one-shot même si Manual Review global est on. |
| **Cover** | Overlay de sélection de couverture (APIs MetaKavita via background). |
| **Config** | URL + jeton + options locales. |
| **Buy me a coffee** | Lien externe discret. |

### Mixed content (HTTPS Kavita + HTTP MetaKavita)

Les navigateurs bloquent l’iframe HTTP dans une page HTTPS. Dans ce cas Companion ouvre Super Review dans un **nouvel onglet** (sans `noopener`, pour pouvoir le fermer). En fin de parcours (standalone tab uniquement), l’onglet se ferme et le focus revient à Kavita.

### Batch & configuration MetaKavita

- **Pas besoin** d’activer Manual Review / Super Review dans la config MetaKavita : les boutons Companion **passent outre** ces toggles pour ce run uniquement.
- Pendant un **batch** : Super Review / Auto passent **après le job en cours**, puis **avant** le reste de la file (pas d’interruption du scrape courant).
- Si la série est **déjà en file d’attente** (batch ou autre), ce job pending est **retiré** (RAM + file durable) et **remplacé** par le job Companion avec les bons flags.

---

## Limites connues

- Pas de support reader Kavita (volontaire).
- Pas encore sur Chrome Web Store / AMO (sideload uniquement).
- Serveur MetaKavita **1.6.5+** requis (APIs Companion).

---

## Développement

Voir [DEVELOPER.md](./DEVELOPER.md). Pack des zips :

```bash
node companion/scripts/pack.mjs
```
