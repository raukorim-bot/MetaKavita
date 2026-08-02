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
    proxy_domains: List[str] = []
    has_direct_id_support: bool = False
    requires_proxy: bool = False
    proxy_referer: str = ""
    needs_api_key: bool = False
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

    def fetch_volume(
        self,
        query: str,
        library_type: str = "Manga",
        volume_number: Optional[Any] = None,
        series_id: Optional[str] = None,
        existing_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Hook volumes (tomes/albums). Défaut : non implémenté → None.

        Les scrapers `scopes={"volume"}` surchargent cette méthode. Le pipeline
        d'écriture Kavita volume n'est pas encore branché ; le contrat permet
        déjà l'install / enable via Manage + Magasin.
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
