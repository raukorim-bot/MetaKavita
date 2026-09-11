# MetaKavita Companion

[English](../en/companion.md) · [Français](README.md)

← [Documentation](README.md)

Chrome + Firefox MV3 (extension **1.1.0**, MetaKavita **1.6.5**+ ; la pastille d'état demande **1.7.3**+). **Bêta / early access** — sideload uniquement ; **pas** sur le Chrome Web Store ni Firefox AMO.

Menu flottant sur les **fiches série** Kavita (pas le reader). La plume ouvre une constellation à deux couronnes, et porte une **pastille d'état**.

### Deux modes

**Simplifiée** (par défaut sur une installation neuve) : cinq boutons, en français courant — *Compléter cette série*, *Changer la couverture*, *Compléter sans me demander*, Config, café. **Experte** (conservée sur une installation déjà appairée) : les sept, sous leurs noms MetaKavita — Super Review, Auto, Cover, Atelier des tomes, Ouvrir dans MetaKavita, Config, café.

La différence n'est pas que le nombre de boutons. En mode simplifié, **Auto demande avant d'écrire** : il remplace vos métadonnées par ce que MetaKavita trouve, sans vous les montrer. La confirmation propose une troisième voie, *Voir avant d'écrire*, qui bascule sur Super Review. En mode expert, il part au clic — c'est tout son intérêt.

Le mode se change dans **Config → Interface**.

### La pastille

| Couleur | Ce que ça veut dire |
|---|---|
| 🟢 | traitée — enrichie, ou cherchée et non trouvée |
| 🟡 | en cours, en file, ou en attente de Manual Review |
| 🔵 | connue de MetaKavita, pas encore enrichie |
| 🔴 | ignorée |
| ⚫ | jamais vue par MetaKavita |

Sur une instance antérieure à 1.7.3, il n'y a simplement pas de pastille.

![Menu Companion sur une fiche série Kavita](../../assets/docs-companion-fab.png)

Super Review via `/companion/embed` si les schémas d'URL matchent. Un Kavita en HTTPS avec un MetaKavita en HTTP ne peut pas l'embarquer (contenu mixte) : la review s'ouvre dans une petite **fenêtre dédiée** centrée sur Kavita et se ferme à la fin. Les aperçus de couverture qui transitent par MetaKavita sont récupérés par l'extension.

Les one-shots Companion **passent outre** les toggles Review / Super, passent devant la file batch (après le job en cours) et **remplacent** tout job pending pour la même série.

## Install (sideload)

**Chrome / Edge :** télécharger [`metakavita-companion-chrome.zip`](https://github.com/raukorim-bot/MetaKavita/raw/main/companion/dist/metakavita-companion-chrome.zip) → extraire → `chrome://extensions` → Mode développeur → Charger non empaquetée.

**Firefox :** télécharger [`metakavita-companion-firefox.zip`](https://github.com/raukorim-bot/MetaKavita/raw/main/companion/dist/metakavita-companion-firefox.zip) → extraire → `about:debugging` → Charger un module temporaire → `manifest.json`.

**Config** (ou la popup de l'extension) ouvre **Réglages Companion** : URL MetaKavita, jeton webhook (dans MetaKavita → [Configuration](configuration.md) / Auto-Sync), **Afficher les boutons d'action**, **Rafraîchir la couverture après confirm (anti-cache)**, **Interface** (Simplifiée / Experte), langue (**Auto (navigateur)** / FR / EN). Puis **Enregistrer**, **Tester la connexion** — qui affiche au passage la version de votre instance — et **Activer sur ce site Kavita**.

« Activer sur ce site Kavita » n'apparaît que dans la **popup** de la barre d'outils : ouverte en page d'options, elle lirait son propre onglet.

![Réglages Companion](../../assets/docs-companion-config.png)

Guide : [`companion/README.md`](../../companion/README.md) (aussi menu Aide). Pack : `node companion/scripts/pack.mjs`.

Les deux archives sont aussi proposées par l'**encart sous la barre du haut**. Sa croix le masque pour ce navigateur ; **Aide → Télécharger le Companion** le fait revenir.

Les flags webhook de l'extension sont dans [Automation](automation.md). Le Companion **Auto** suit le même mapping Auto que le dashboard quand il est allumé ; **Super Review** ne le suit pas.
