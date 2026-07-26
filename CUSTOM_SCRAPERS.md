# 🛠️ MetaKavita : Scrapers Personnalisés & Vibecoding

MetaKavita intègre un système d'**Auto-Découverte**. Vous n'avez pas besoin de modifier le code source de l'application pour ajouter un nouveau site de métadonnées. Il vous suffit de glisser un fichier Python (`.py`) dans le dossier `data/scrapers/` et de redémarrer MetaKavita. Le système se chargera de l'intégrer automatiquement à l'interface, de générer les champs de clés API si besoin, et de sécuriser les requêtes réseau.

Voici le guide complet pour créer et importer vos propres sources de données.

---

## 🤖 Méthode 1 : Le "Vibecoding" (Génération par IA)

Vous ne savez pas coder ? Aucun problème. Vous pouvez demander à une IA (ChatGPT, Claude, Mistral) d'écrire le scraper pour vous en lui fournissant le contrat strict de MetaKavita.

**Copiez-collez ce prompt exact à votre IA :**

> "Agis en tant que Développeur Python Expert. Je construis un scraper de métadonnées pour l'application MetaKavita. L'application utilise un Registre par Auto-Découverte. Tu dois créer une classe Python qui hérite de `BaseScraper` pour scrapper le site **[INSERER LE NOM DU SITE ICI]**.
> 
> Voici les contraintes absolues :
> 1. Les seules librairies externes autorisées sont `requests`, `curl_cffi` et `bs4` (BeautifulSoup). N'utilise JAMAIS Selenium ou Playwright.
> 2. Tu dois conserver les imports : `from scrapers.base import BaseScraper`, `from scrapers.utils import clean_title, score_candidate, get_match_accept_threshold, attach_match_score`, et `from config_manager import get_max_tags, get_max_genres`.
> 
> Voici le squelette obligatoire que tu dois remplir :
> 
> ```python
> import logging
> from bs4 import BeautifulSoup
> from curl_cffi import requests # Ou 'import requests' classique
> from typing import Dict, Any, List, Optional
> from scrapers.base import BaseScraper
> from scrapers.utils import clean_title, score_candidate, get_match_accept_threshold, attach_match_score
> from config_manager import get_max_tags, get_max_genres
> 
> class MyNewScraper(BaseScraper):
>     id = "MON_SITE_ID" # En majuscules, sans espaces
>     display_name = "Nom de mon site"
>     supported_types = {"Manga"} # Peut être "Manga", "Comic", ou "Book"
>     rate_limit = 1.5 # Secondes d'attente entre deux requêtes pour ne pas se faire bannir
>     proxy_domains = ["monsite.com", "images.monsite.com"] # Domaines autorisés pour les images
>     has_direct_id_support = False
>     needs_api_key = False # Mettre True si une clé API est requise
>     uses_unified_scoring = True  # Déclare la participation au Smart Scoring (voir §4)
> 
>     def extract_id_from_url(self, url: str) -> Optional[str]:
>         # Optionnel : Logique pour extraire l'ID si l'utilisateur colle une URL directe
>         return None
> 
>     def fetch(self, query: str, library_type: str = "Manga", is_id: bool = False, existing_metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
>         clean = clean_title(query, library_type=library_type)
>         
>         # ÉTAPE 1 : Fais ta requête HTTP (API ou HTML)
>         # ÉTAPE 2 : Construit un dictionnaire candidat au format exact Kavita
>         # ÉTAPE 3 : Évalue le candidat avec score_candidate(candidate, clean, existing_metadata)
>         # ÉTAPE 4 : Retourne attach_match_score(best_match, best_score) SI score >= get_match_accept_threshold()
>         #           (pour une résolution par ID direct : attach_match_score(candidate, 1.0))
>         
>         # FORMAT OBLIGATOIRE DU DICTIONNAIRE DE RETOUR :
>         '''
>         {
>             'title': 'str_titre_original',     # OBLIGATOIRE (utilisé pour le scoring)
>             'alternative_titles': ['titre1', 'titre2'],
>             'summary': 'str_resume',
>             'cover_url': 'str_url_image',
>             'genres': genres_list[:get_max_genres()] if genres_list else ['Manga'],  # JAMAIS [:5] en dur — voir §7
>             'tags': tags_list[:get_max_tags()], # JAMAIS [:15] en dur — voir §6
>             'year': 2024,                      # int
>             'status': 'RELEASING',             # 'RELEASING', 'FINISHED', 'HIATUS' ou 'CANCELLED'
>             'staff': [{'role': 'Story', 'node': {'name': {'full': 'Prénom Nom'}}}, {'role': 'Art', 'node': {'name': {'full': 'Prénom Nom'}}}],
>             'publisher': 'str_nom_editeur',
>             'age_rating': 'safe',              # 'safe', 'suggestive', ou 'pornographic'
>             'format': 'manga',                 # 'manga', 'webtoon', 'comic' ou 'book'
>             'url': 'str_url_de_la_page_source',
>             'isbn': 'str_chiffres_uniquement'  # Optionnel, mais vital pour les romans
>         }
>         '''
>         pass
> 
>     def fetch_covers(self, query: str, library_type: str = "Manga") -> List[Dict[str, str]]:
>         # DOIT retourner une liste de max 5 dicts : [{"provider": self.display_name, "title": "Titre", "url": "URL Image"}]
>         return []
> ```"

---

## 👨‍💻 Méthode 2 : Développement Manuel (Règles strictes)

Si vous codez votre propre scraper, MetaKavita rejettera votre fichier si ces règles ne sont pas respectées.

### 1. La classe `BaseScraper`
Votre classe **doit** hériter de `BaseScraper`. C'est ce qui indique à l'Auto-Découverte que votre fichier est un scraper valide.

### 2. Le paramètre `needs_api_key`
Si le site que vous ciblez requiert une clé API (comme ComicVine ou Google Books), définissez `needs_api_key = True`. 
**Magie de MetaKavita :** L'interface web générera automatiquement un champ de mot de passe sécurisé pour l'utilisateur, et vous pourrez récupérer la clé dans votre code via `load_config().get("VOTRE_ID_API_KEY")`.

### 3. Le Throttling (`rate_limit`)
MetaKavita gère intelligemment la vitesse pour éviter que votre IP ne soit bannie.
Définissez `rate_limit = 2.0` (ex: 2 secondes). Le moteur attendra automatiquement 2 secondes *uniquement* si l'API vient d'être appelée. Ne mettez pas de `time.sleep()` manuels dans votre code !

### 4. La matrice de Scoring (`score_candidate`) & Smart Scoring
Ne retournez jamais le premier résultat d'une recherche aveuglément ! 
Importez `from scrapers.utils import score_candidate, get_match_accept_threshold, attach_match_score` et passez chaque résultat dans `score_candidate()`. Elle comparera le titre, les auteurs et l'ISBN trouvés avec la base de Kavita pour éliminer les homonymes et les Spin-offs. Ne retournez le candidat que si son score est supérieur ou égal à `get_match_accept_threshold()` (défaut `0.60`, configurable via le **Baromètre de fiabilité** dans la sidebar), **en l'attachant via `attach_match_score(candidate, score)`**.

Le moteur (`metadata_fetcher.py`) compare ensuite les scores de plusieurs providers entre eux (Smart Scoring) : le meilleur score gagne, l'égalité est départagée par l'ordre de fallback configuré. Sans `attach_match_score()`, votre scraper reste utilisable, mais il est traité comme « juste accepté » (score neutre = seuil effectif) et perdra presque toujours face à un scraper officiel mieux scoré.

Pour déclarer explicitement que votre scraper participe au Smart Scoring, ajoutez sur la classe :
```python
uses_unified_scoring = True
```
Ce drapeau (défini à `False` par défaut sur `BaseScraper`) est **informatif** : il ne bloque pas le chargement. Le pipeline est déjà protégé contre un `_match_score` absent ou mal formé (`None`, chaîne, booléen, NaN…) via `_safe_match_score()` — un scraper communautaire mal écrit ne peut donc plus faire planter l'enrichissement. Le drapeau sert surtout à documenter l'intention et à faciliter le diagnostic.

⚠️ N'écrivez pas `0.60` (ou toute autre valeur) en dur dans votre scraper : utilisez `get_match_accept_threshold()`. La constante `MATCH_ACCEPT_THRESHOLD = 0.60` reste le défaut documenté (rétrocompat), mais le seuil effectif peut être modifié par l'utilisateur (sidebar). Un scraper avec son propre seuil codé en dur ne suivra ni le défaut ni le baromètre.

⚠️ N'écrivez jamais `_match_score` à la main dans le dict retourné : passez toujours par `attach_match_score()`. Pour une résolution par ID/URL (`is_id=True`), utilisez `attach_match_score(candidate, 1.0)`.

**Checklist Smart Scoring (scraper communautaire) :**
1. `from scrapers.utils import score_candidate, get_match_accept_threshold, attach_match_score`
2. `uses_unified_scoring = True` sur la classe
3. Pour chaque candidat accepté : `return attach_match_score(candidate, score)` si `score >= get_match_accept_threshold()` (ou `1.0` si `is_id=True`)
4. Ne jamais renvoyer un `_match_score` brut / non numérique — même si `_safe_match_score()` le tolère côté moteur

### 5. La sécurité des images (`proxy_domains`)
Kavita requiert un lien direct pour télécharger la couverture. Si le site a des protections Cloudflare sur ses images, renseignez le domaine dans la liste `proxy_domains = ["monsite.com"]`. MetaKavita fera transiter l'image par son proxy interne (`/api/proxy-image`) pour contourner les blocages.

### 6. Le plafond de tags (`MAX_TAGS` / `get_max_tags`)
Ne tronquez **jamais** la liste de tags avec un littéral `[:15]` (ou toute autre constante). Le plafond est configurable par l’utilisateur via env Docker / `config.json` (`MAX_TAGS`, défaut **15**, borné 1–100) — **pas d’UI**. Importez le helper et tronquez ainsi :

```python
from config_manager import get_max_tags

# ...
'tags': tags_list[:get_max_tags()],
```

Le moteur d’enrichissement (`services/enrichment_engine.py`) applique aussi `get_max_tags(config)` au moment d’écrire vers Kavita. Tronquer côté scraper reste recommandé pour rester cohérent avec les scrapers officiels et éviter d’envoyer des listes inutiles au pipeline.

⚠️ Un scraper avec `tags[:15]` en dur ignorera le réglage de l’utilisateur (ex: `MAX_TAGS=30`) et ne profitera pas d’un futur changement de défaut.

### 7. Le plafond de genres (`MAX_GENRES` / `get_max_genres`)
Même logique que les tags : ne tronquez **jamais** avec un littéral `[:5]`. Le plafond est configurable (`MAX_GENRES`, défaut **5**, borné 1–50) — **pas d’UI** :

```python
from config_manager import get_max_genres

# ...
'genres': genres[:get_max_genres()] if genres else ["Manga"],
```

Le moteur d’enrichissement (`services/enrichment_engine.py`) applique aussi `get_max_genres(config)` au moment d’écrire vers Kavita (filet de sécurité, miroir de `get_max_tags`). Tronquer côté scraper reste recommandé pour rester cohérent avec les scrapers officiels.

⚠️ Un scraper avec `genres[:5]` en dur ignorera le réglage de l’utilisateur (ex: `MAX_GENRES=10`) et ne profitera pas d’un futur changement de défaut.

---

## 🧬 Dupliquer / étendre un scraper officiel existant

Vous n'êtes pas obligé de partir de zéro. Si un scraper officiel (`scrapers/*.py`) couvre déjà
90% de ce dont vous avez besoin, la manière la plus robuste de l'adapter est d'en **hériter**
plutôt que de copier-coller son code :

```python
# data/scrapers/mangabaka_book.py
from scrapers.mangabaka import MangaBakaScraper

class MangaBakaBookScraper(MangaBakaScraper):
    id = "MANGABAKA_BOOK"          # Un id DIFFÉRENT de "MANGABAKA" (voir ci-dessous)
    display_name = "MangaBaka (Light Novels / Books)"
    supported_types = {"Book"}
```

> Note : depuis v1.6.0, l'officiel MangaBaka expose déjà `{"Manga", "Book"}`. Cet exemple
> n'est plus requis pour activer les LN — il illustre seulement le pattern d'héritage.
> Si le fichier reste monté, vous verrez deux entrées Book (`MANGABAKA` + `MANGABAKA_BOOK`).

Sans toucher au fichier officiel ni dupliquer sa logique HTTP : toute correction future du
scraper parent en profite automatiquement.

### Id différent vs. id identique : deux comportements distincts

- **Id différent** (recommandé, cas ci-dessus) : votre variante s'ajoute à côté de l'officiel.
  Les deux sont sélectionnables indépendamment dans les listes de fournisseurs.
- **Id identique** (surcharge volontaire) : si votre fichier redéfinit `id = "MANGABAKA"`,
  le Registre **remplace** l'enregistrement officiel par le vôtre (les scrapers de
  `data/scrapers/` sont toujours chargés *après* ceux de `scrapers/`). C'est utile si vous
  voulez corriger ou modifier le comportement d'un scraper officiel sans attendre une mise à
  jour de MetaKavita. Ce remplacement est loggé au démarrage (`⚠️ [Registry] L'id de scraper
  '...' est remplacé par ...`) pour rester diagnosticable — vérifiez toujours ce message si un
  scraper ne se comporte pas comme attendu après l'ajout d'un fichier personnalisé.

⚠️ N'oubliez pas d'importer la classe parente avec son chemin complet
(`from scrapers.mangabaka import MangaBakaScraper`) : seules les classes **définies** dans
votre fichier sont enregistrées par le Registre, la classe importée pour héritage ne l'est pas.

---

## 🚀 Installation & Activation

Une fois votre fichier `mon_site.py` terminé :
1. Allez dans le dossier racine de votre serveur où est installé MetaKavita.
2. Ouvrez le dossier `data/` (le volume monté par Docker contenant votre `config.json`).
3. Créez un dossier `scrapers` s'il n'existe pas, et glissez-y votre fichier `mon_site.py`.
   * *Chemin complet :* `.../data/scrapers/mon_site.py`
4. Redémarrez votre conteneur Docker :
   ```bash
   docker restart metakavita
   ```

1. Allez sur l'interface web de MetaKavita, cliquez sur ⚙️ Config : votre nouveau scraper est désormais disponible dans les listes de fournisseurs !