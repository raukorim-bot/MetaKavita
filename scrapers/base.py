from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Set

class BaseScraper(ABC):
    id: str = ""
    display_name: str = ""
    supported_types: Set[str] = set()
    # series = enrichissement série (Providers / cascade actuelle)
    # volume = scrapers conçus pour tomes/albums (pipeline volume à venir)
    scopes: Set[str] = {"series"}
    rate_limit: float = 1.0
    # Délai d'une requête sortante quand le point d'appel n'en impose pas.
    http_timeout: float = 20.0
    proxy_domains: List[str] = []
    has_direct_id_support: bool = False
    requires_proxy: bool = False
    proxy_referer: str = ""
    needs_api_key: bool = False
    # Official image scrapers set True — single source of truth for core discovery
    # (seed/sync image → data/scrapers). Community/custom leave the default False.
    is_core: bool = False

    # Version du scraper, en `major.minor.patch`. C'est elle qui arbitre le sync
    # core : `data/scrapers/` est alimenté par deux sources concurrentes — l'image
    # et le catalogue GitHub — et sans version la seule comparaison possible était
    # l'égalité de sha256, qui ne dit pas laquelle des deux copies est la plus
    # récente. Un scraper core qui gagne une capacité (un `fetch_volume_index`,
    # par exemple) doit donc monter sa version : c'est le seul signal qui autorise
    # l'image à remplacer la copie déjà installée, et qui empêche un catalogue en
    # retard de la faire régresser. Le générateur du catalogue communautaire lit
    # cet attribut de classe et le publie dans `store/catalog.json`.
    version: str = "1.0.0"

    translations: Dict[str, Dict[str, str]] = {}

    # Déclaratif, PUREMENT informatif : indique si ce scraper attache un score réel
    # (via `attach_match_score()`, voir scrapers/utils.py) calculé par `score_candidate()`
    # aux candidats qu'il retourne, plutôt que de laisser `fetch_metadata()` retomber sur
    # un score neutre (`MATCH_ACCEPT_THRESHOLD`) faute de mieux. Les 9 scrapers officiels
    # basés sur une recherche le mettent à `True`. Un scraper communautaire n'a AUCUNE
    # obligation de le faire ni de le déclarer : ne pas le déclarer (valeur par défaut
    # `False`) ne dégrade ni ne bloque rien, `fetch_metadata()` reste sûr dans tous les cas
    # (voir la garde `_safe_match_score()` dans metadata_fetcher.py, qui protège contre
    # TOUTE valeur malformée, pas seulement une clé absente). Ce drapeau sert uniquement à
    # la documentation/diagnostic (voir CUSTOM_SCRAPERS.md) et au test de non-régression
    # `tests/test_scoring_threshold.py`, qui vérifie que les scrapers officiels ne
    # régressent pas silencieusement vers un score neutre.
    uses_unified_scoring: bool = False


    def _http_get(self, client: Any, url: str, **kwargs) -> Any:
        """GET soumis au `rate_limit` du fournisseur, timeout compris.

        `throttle_provider()` n'était appelé qu'une fois, par l'appelant, AVANT
        `fetch()` : les six à vingt-cinq requêtes émises À L'INTÉRIEUR d'un
        `fetch()` échappaient donc au compteur et partaient en rafale. C'est
        exactement le profil de trafic qui fait bannir une IP ou déclencher un
        403 Cloudflare sur les sites sans API — après quoi l'utilisateur voit
        « aucun résultat » chez tous ses fournisseurs français sans savoir qu'il
        est bloqué. La cadence doit donc être portée par la requête, pas par
        l'appel de plus haut niveau, qui reste en place pour les scrapers
        communautaires qui n'utilisent pas ce point de passage.

        `client` est la session (ou le module `requests`) du scraper plutôt
        qu'un client construit ici : chaque fournisseur a ses propres en-têtes,
        son `impersonate`, et les tests remplacent ce module.
        """
        # Import local : `scrapers/base.py` est aussi la base des scrapers
        # communautaires, qui doivent pouvoir être chargés hors application.
        from services.provider_throttle import throttle_provider

        throttle_provider(self)
        kwargs.setdefault("timeout", self.http_timeout)
        return client.get(url, **kwargs)

    def _http_post(self, client: Any, url: str, **kwargs) -> Any:
        """Équivalent de `_http_get` pour les API interrogées en POST (GraphQL)."""
        from services.provider_throttle import throttle_provider

        throttle_provider(self)
        kwargs.setdefault("timeout", self.http_timeout)
        return client.post(url, **kwargs)

    def get_ui_lang(self) -> str:
        """Récupère la langue d'interface configurée par l'utilisateur."""
        try:
            from config_manager import load_config
            return load_config().get("UI_LANG", "fr")
        except Exception:
            return "fr"

    def t(self, key: str, lang: Optional[str] = None, default: str = "") -> str:
        """Helper i18n local au scraper avec fallback de langue et de clé."""
        target_lang = (lang or self.get_ui_lang()).lower()[:2]
        lang_dict = self.translations.get(target_lang, self.translations.get("fr", {}))
        return lang_dict.get(key, default or key)

    @property
    def localized_display_name(self) -> str:
        """Nom affiché selon UI_LANG (clé scraper translations.display_name)."""
        target_lang = self.get_ui_lang().lower()[:2]
        lang_dict = self.translations.get(target_lang) or self.translations.get("fr") or {}
        name = lang_dict.get("display_name")
        return name if name else self.display_name

    @abstractmethod
    def fetch(self, query: str, library_type: str = "Manga", is_id: bool = False, existing_metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Doit retourner un dictionnaire standardisé de métadonnées, ou None."""
        pass

    def fetch_volume_index(
        self,
        query: str,
        library_type: str = "Comic",
        series_id: Optional[str] = None,
        existing_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Index des tomes/albums d'une série : `{numéro: payload}`. Défaut : None.

        Un seul appel réseau pour toute la série quand le fournisseur le permet
        — ComicVine ramène cent albums d'un coup, résumés et couvertures
        compris — ce qui est la condition de viabilité de l'enrichissement par
        tome : un appel par tome coûterait deux heures sur une bibliothèque de
        mille unités. `fetch_volume` ne sert qu'aux fournisseurs incapables de
        lister, interrogés unité par unité.

        Chaque payload peut porter `title`, `summary`, `release_date`, `isbn`
        et `cover_url`. Les clés absentes ne sont pas écrites.
        """
        return None

    def fetch_volume(
        self,
        query: str,
        library_type: str = "Manga",
        volume_number: Optional[Any] = None,
        series_id: Optional[str] = None,
        existing_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Un tome précis, pour les fournisseurs qui ne savent pas lister.

        Défaut : non implémenté → None. Préférez `fetch_volume_index` quand la
        source expose la liste des albums d'une série.
        """
        return None

    def fetch_covers(self, query: str, library_type: str = "Manga") -> List[Dict[str, str]]:
        """Optionnel: Retourne une liste de couvertures pour la recherche manuelle."""
        return []

    def extract_id_from_url(self, url: str) -> Optional[str]:
        """Extrait l'ID depuis une URL directe si supporté par le scraper."""
        return None

    def normalized_scopes(self) -> Set[str]:
        raw = getattr(self, "scopes", None) or {"series"}
        allowed = {"series", "volume"}
        out = {str(s).strip().lower() for s in raw if str(s).strip().lower() in allowed}
        return out or {"series"}
