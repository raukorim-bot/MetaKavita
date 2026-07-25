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
> 2. Tu dois conserver l'import : `from scrapers.base import BaseScraper` et `from scrapers.utils import clean_title, score_candidate`.
> 
> Voici le squelette obligatoire que tu dois remplir :
> 
> ```python
> import logging
> from bs4 import BeautifulSoup
> from curl_cffi import requests # Ou 'import requests' classique
> from typing import Dict, Any, List, Optional
> from scrapers.base import BaseScraper
> from scrapers.utils import clean_title, score_candidate
> 
> class MyNewScraper(BaseScraper):
>     id = "MON_SITE_ID" # En majuscules, sans espaces
>     display_name = "Nom de mon site"
>     supported_types = {"Manga"} # Peut être "Manga", "Comic", ou "Book"
>     rate_limit = 1.5 # Secondes d'attente entre deux requêtes pour ne pas se faire bannir
>     proxy_domains = ["monsite.com", "images.monsite.com"] # Domaines autorisés pour les images
>     has_direct_id_support = False
>     needs_api_key = False # Mettre True si une clé API est requise
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
>         # ÉTAPE 4 : Retourne le candidat ayant le meilleur score (SI score >= 0.50)
>         
>         # FORMAT OBLIGATOIRE DU DICTIONNAIRE DE RETOUR :
>         '''
>         {
>             'title': 'str_titre_original',     # OBLIGATOIRE (utilisé pour le scoring)
>             'alternative_titles': ['titre1', 'titre2'],
>             'summary': 'str_resume',
>             'cover_url': 'str_url_image',
>             'genres': ['Action', 'Fantasy'],   # 5 max recommandés
>             'tags': ['Magie', 'Démons'],       # 15 max
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

### 4. La matrice de Scoring (`score_candidate`)
Ne retournez jamais le premier résultat d'une recherche aveuglément ! 
Importez `from scrapers.utils import score_candidate` et passez chaque résultat dans cette fonction. Elle comparera le titre, les auteurs et l'ISBN trouvés avec la base de Kavita pour éliminer les homonymes et les Spin-offs. Ne retournez le candidat que si son score est supérieur ou égal à `0.50` (50% de pertinence).

### 5. La sécurité des images (`proxy_domains`)
Kavita requiert un lien direct pour télécharger la couverture. Si le site a des protections Cloudflare sur ses images, renseignez le domaine dans la liste `proxy_domains = ["monsite.com"]`. MetaKavita fera transiter l'image par son proxy interne (`/api/proxy-image`) pour contourner les blocages.

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