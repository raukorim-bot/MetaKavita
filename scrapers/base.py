from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Set

class BaseScraper(ABC):
    id: str = ""
    display_name: str = ""
    supported_types: Set[str] = set()
    rate_limit: float = 1.0
    proxy_domains: List[str] = []
    has_direct_id_support: bool = False

    @abstractmethod
    def fetch(self, query: str, library_type: str = "Manga", is_id: bool = False) -> Optional[Dict[str, Any]]:
        """Doit retourner un dictionnaire standardisé de métadonnées, ou None."""
        pass

    def fetch_covers(self, query: str, library_type: str = "Manga") -> List[Dict[str, str]]:
        """
        Optionnel: Retourne une liste de couvertures pour la recherche manuelle.
        Format: [{"provider": str, "title": str, "url": str}]
        """
        return []
        
    def extract_id_from_url(self, url: str) -> Optional[str]:
        """
        Extrait l'ID depuis une URL. 
        Désactivé par défaut (renvoie None). 
        À surcharger UNIQUEMENT dans les scrapers enfants qui supportent techniquement la recherche par URL.
        """
        return None