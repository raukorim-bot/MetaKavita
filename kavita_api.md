# 📚 SPÉCIFICATION TECHNIQUE INTERNE : INTÉGRATION API KAVITA (v0.8+)

---

## 🏗️ 1. ARCHITECTURE ET PRINCIPES FONDAMENTAUX

Le dialogue entre un enrichisseur externe (MetaKavita) et le serveur Kavita repose sur **4 principes d'architecture fondamentaux** imposés par le framework .NET / Entity Framework Core de Kavita :

### A. La Séparation Tripartite des Endpoints
Kavita sépare strictement l'entité "Série" en 3 contrôleurs HTTP distincts :
1. **`POST /api/Series/metadata`** : Reçoit les métadonnées littéraires, thématiques, créatives et éditoriales (`SeriesMetadataDto`).
2. **`POST /api/Series/update`** : Reçoit les paramètres généraux de la série et ses IDs de plateformes externes (`UpdateSeriesDto`).
3. **`POST /api/Upload/series`** : Reçoit le flux binaire de l'image de couverture (`UploadSeriesCoverDto`).

> **Règle absolue :** Envoyer une propriété au mauvais endpoint provoque une ignorance silencieuse du champ par le serveur C# de Kavita (qui répond un faux `200 OK` tout en jetant la donnée).

### B. Le Mécanisme de Verrouillage C# (*Lock Guard*)
Le contrôleur C# de Kavita exécuté lors d'une mise à jour évalue chaque champ modifiable selon l'algorithme suivant :
```csharp
if (!dbMetadata.FieldLocked || !requestMetadata.FieldLocked) 
{
    dbMetadata.Field = requestMetadata.Field; // Écriture autorisée
}
dbMetadata.FieldLocked = requestMetadata.FieldLocked; // Mise à jour de l'état du verrou
```

**Conséquence technique :** Si un champ est actuellement verrouillé en BDD (`dbMetadata.FieldLocked == true`) et que la requête entrante envoie également le verrou activé (`requestMetadata.FieldLocked == true`), la condition d'écriture est évaluée à `FALSE`. Kavita **ignore la nouvelle valeur** et conserve l'ancienne donnée.

### C. Le Protocole de Transaction à 2 Passages (*Unlock ➔ Write ➔ Lock*)
Pour garantir l'écriture de nouvelles données sur des séries préalablement verrouillées (ou lors d'un *Force Sync*), l'application doit exécuter une séquence à deux passages HTTP :
* **Passage 1 (Déverrouillage & Écriture) :** Envoi des nouvelles données en forçant la totalité des drapeaux `...Locked` associés à `false`. La condition `!requestMetadata.FieldLocked` passe à `TRUE` : Kavita écrit la nouvelle donnée en BDD et déverrouille le champ.
* **Passage 2 (Scellage de Sécurité) :** Envoi immédiat des mêmes données en repassant les drapeaux `...Locked` à `true`. La BDD étant déverrouillée depuis le passage 1 (`!dbMetadata.FieldLocked == true`), Kavita accepte la commande de verrouillage et scelle le champ contre les futurs scans de fichiers.

### D. Résolution Automatique d'Entités (`id: 0`)
Pour les listes de catégories (`TagDto`) et de personnes (`PersonDto`), fournir `"id": 0` ordonne à l'ORM C# d'effectuer une recherche textuelle par nom/titre en BDD :
* Si l'entité existe (ex: Genre "Action" ou Éditeur "Kodansha"), Kavita lie son `Id` existant.
* Si l'entité n'existe pas, Kavita l'insère automatiquement en base de données.

---

## 📐 2. SPÉCIFICATION DÉTAILLÉE DES ENDPOINTS ET DTOS

---

### 1️⃣ ENDPOINT : `POST /api/Series/metadata`
* **Contrôleur C# :** `SeriesMetadataController`
* **Enveloppe obligatoire :** Le payload JSON doit impérativement être encapsulé sous la clé racine `"seriesMetadata"` :
  `{"seriesMetadata": { ... }}`

#### A. Propriétés Scalaires et Textuelles :

| Clé JSON | Type C# | Clé du Verrou | Type Verrou | Format & Contraintes | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `seriesId` | `int` | *N/A* | *N/A* | Entier > 0 | **Requis.** Identifiant de la série parente. |
| `summary` | `string` | `summaryLocked` | `bool` | HTML / UTF-8 | Synopsis / Résumé traduit de l'œuvre. |
| `releaseYear` | `int` | `releaseYearLocked` | `bool` | Entier YYYY | Année de début de publication (ex: `2005`). |
| `publicationStatus` | `int` | `publicationStatusLocked` | `bool` | Enum `0`-`3` | Statut d'édition (voir section Enums). |
| `ageRating` | `int` | `ageRatingLocked` | `bool` | Enum `-1`–`14` | Classification d'âge (voir section Enums). |
| `language` | `string` | `languageLocked` | `bool` | Code ISO (ex: `"fr"`) | Langue cible de la fiche. |
| `webLinks` | `string` | *N/A* | *N/A* | Chaîne CSV | URLs externes séparées par des virgules (`"url1,url2"`). |

#### B. Listes de Catégories (`TagDto`) :
* **Format d'élément :** `{"id": int, "title": "string"}`

| Clé JSON (Pluriel) | Clé du Verrou (Pluriel) | Type Objet | Description |
| :--- | :--- | :--- | :--- |
| `genres` | `genresLocked` | `TagDto` | Genres littéraires principaux. |
| `tags` | `tagsLocked` | `TagDto` | Mots-clés thématiques (limité aux 15 plus pertinents). |

#### C. Listes de Personnes et Organismes (`PersonDto`) :
* **Format d'élément :** `{"id": int, "name": "string"}`
* **Règle absolue de nommage :** Les clés de tableaux sont toutes au **PLURIEL**, tandis que leurs verrous associés sont strictement au **SINGULIER**.

| Clé JSON (Tableau Pluriel) | Clé du Verrou (Singulier) | Type Objet | Rôle attribué dans Kavita |
| :--- | :--- | :--- | :--- |
| `publishers` | `publisherLocked` | `PersonDto` | Maisons d'édition (VF/VA ou VO). |
| `imprints` | `imprintLocked` | `PersonDto` | Collections ou sous-marques d'édition. |
| `writers` | `writerLocked` | `PersonDto` | Scénaristes / Auteurs de l'histoire originale. |
| `pencillers` | `pencillerLocked` | `PersonDto` | Dessinateurs principaux / Illustrateurs. |
| `colorists` | `coloristLocked` | `PersonDto` | Coloristes. |
| `translators` | `translatorLocked` | `PersonDto` | Traducteurs officiels / Groupes de scantrad. |
| `coverArtists` | `coverArtistLocked` | `PersonDto` | Artistes des couvertures originales. |
| `editors` | `editorLocked` | `PersonDto` | Éditeurs / Responsables éditoriaux (Staff). |
| `letterers` | `lettererLocked` | `PersonDto` | Lettreurs. |
| `inkers` | `inkerLocked` | `PersonDto` | Encreurs. |
| `characters` | `characterLocked` | `PersonDto` | Personnages de l'œuvre. |
| `teams` | `teamLocked` | `PersonDto` | Équipes / Studios. |
| `locations` | `locationLocked` | `PersonDto` | Lieux principaux de l'intrigue. |

---

### 2️⃣ ENDPOINT : `POST /api/Series/update`
* **Contrôleur C# :** `SeriesController`
* **Enveloppe obligatoire :** Objet JSON plat à la racine (type `UpdateSeriesDto`).
* **Usage :** Mise à jour ciblée des paramètres d'affichage et des identifiants natifs.

| Clé JSON | Type C# | Clé du Verrou | Type Verrou | Format & Contraintes | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `id` | `int` | *N/A* | *N/A* | Entier > 0 | **Requis.** Clé primaire (`Series.Id`). |
| `localizedName` | `string` | `localizedNameLocked` | `bool` | Chaîne UTF-8 | Titres alternatifs séparés par `" / "`. |
| `format` | `int` | `formatLocked` | `bool` | Enum `0`-`4` | Sens de lecture / Format (voir section Enums). |
| `name` | `string` | `nameLocked` | `bool` | Chaîne UTF-8 | Titre canonique de la série. |
| `sortName` | `string` | `sortNameLocked` | `bool` | Chaîne UTF-8 | Titre utilisé pour le tri alphabétique. |
| `aniListId` | `int` | *N/A* | *N/A* | Entier ID | Identifiant AniList pour l'UI Kavita. |
| `malId` | `int` | *N/A* | *N/A* | Entier ID | Identifiant MyAnimeList pour l'UI Kavita. |
| `mangaBakaId` | `int` | *N/A* | *N/A* | Entier ID | Identifiant MangaBaka pour l'UI Kavita. |

---

### 3️⃣ ENDPOINT : `POST /api/Upload/series` (COVERS)
* **Contrôleur C# :** `UploadController`
* **Description Officielle Swagger :** `Replaces series cover image AND LOCKS IT with a base64 encoded image`
* **Enveloppe obligatoire :** Objet JSON plat à la racine (type `UploadSeriesCoverDto`).
* **Usage :** Injection du flux binaire de l'image de couverture et verrouillage atomique.

| Clé JSON | Type C# | Obligatoire | Format & Contraintes | Description & Comportement Serveur |
| :--- | :--- | :---: | :--- | :--- |
| `id` | `int` | **Oui** | Entier > 0 | Identifiant unique de la série (`Series.Id`). |
| `url` | `string` | **Oui** | Base64 Pur (`[a-zA-Z0-9+/=]`) | **Chaîne d'octets brute uniquement.** Interdiction absolue du préfixe Data URI (type `data:image/...;base64,`). Kavita décode le binaire et écrit le fichier sur le disque. |
| `fileName` | `string` | **Oui** | Nom de fichier avec extension (`.jpg`, `.png`, `.webp`) | Nom du fichier physique généré sur le stockage serveur (ex: `"series_cover_534.jpg"`). |
| `lockCover` | `bool` | **Oui** | `true` | **Drapeau de verrouillage atomique.** Doit être passé à `true` pour forcer Kavita à sceller immédiatement `coverImageLocked = true` en BDD lors de l'écriture. |

#### Comportement Interne du Serveur Kavita lors de l'Upload :
1. Kavita reçoit le DTO et vérifie si `lockCover` est présent. Si `lockCover` est omit ou vaut `false`, C# initialise la valeur à `false`, rendant la couverture temporaire et vulnérable au prochain scan de fichiers.
2. Kavita décode la chaîne Base64 du champ `url`, génère le fichier physique sur le disque dans le dossier `covers/` en utilisant le suffixe défini par `fileName`.
3. Kavita met à jour le champ `coverImage` dans la table `Series` et passe `coverImageLocked` à `true` si `"lockCover": true` était présent dans la requête.

---

## 🔢 3. MAPPAGE DES TYPES ÉNUMÉRÉS (ENUMS)

### A. Statut de Publication (`publicationStatus`)
* `0` = **Ongoing / Releasing** (En cours de parution)
* `1` = **On Hiatus / Paused** (En pause)
* `2` = **Completed / Finished** (Terminé)
* `3` = **Cancelled / Discontinued** (Abandonné)

### B. Classification d'Âge (`ageRating`)
Enum Kavita réel (`API/Entities/Enums/AgeRating.cs`, aussi exposé par
`GET /api/metadata/age-ratings`). **Ne pas confondre** avec le vocabulaire
interne MetaKavita (`safe` / `suggestive` / `erotica` / `pornographic`) que les
scrapers émettent — la conversion vit uniquement dans
`kavita_constants.AGE_RATING_MAP` (`safe→3`, `suggestive→8`, `erotica→12`,
`pornographic→14`).

* `-1` = **Not Applicable** (restriction de profil uniquement)
* `0` = **Unknown**
* `1` = **Rating Pending**
* `2` = **Early Childhood**
* `3` = **Everyone**
* `4` = **G**
* `5` = **Everyone 10+**
* `6` = **PG**
* `7` = **Kids to Adults**
* `8` = **Teen**
* `9` = **MA15+**
* `10` = **Mature 17+**
* `11` = **M**
* `12` = **R18+**
* `13` = **Adults Only 18+**
* `14` = **X18+**

### C. Sens de Lecture / Format (`format`)
* `0` = **Unknown / Default** (Par défaut)
* `1` = **Manga** (Lecture de Droite à Gauche)
* `2` = **Comic / BD** (Lecture de Gauche à Droite)
* `3` = **Novel / Roman** (Format texte / Light Novel)
* `4` = **Webtoon / Manhwa** (Défilement vertical)

---

## 🧹 4. RÈGLES D'ASSAINISSEMENT DES PAYLOADS ET SÉCURITÉ

1. **Suppression des Métriques Système :** 
   Toute propriété calculée ou temporelle retournée par un appel `GET` (notamment `created`, `lastModified`, `totalCount`, `maxCount`, `pages`, `wordCount`) doit être **impérativement retirée** du dictionnaire JSON avant l'envoi en `POST`, afin d'éviter les exceptions de concurrence d'état dans Entity Framework Core.
2. **Encodage des Liens Web (`webLinks`) :** 
   Ce champ exige une chaîne de caractères CSV unique (`"https://site1.com,https://site2.com"`). L'envoi d'un tableau JSON `["url1", "url2"]` sur ce champ provoque l'échec de la désérialisation C#.
3. **Interpretation des Statuts HTTP Kavita :**
   Kavita renvoie un code `200 OK` même lorsqu'une clé JSON est inconnue ou ignorée. La seule garantie d'écriture est le respect strict des noms de propriétés (ex: `publishers` au pluriel, `publisherLocked` au singulier) et de la séquence de transaction à 2 passages (*Unlock ➔ Write ➔ Lock*).