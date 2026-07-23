import os
import importlib
import inspect
import logging
from .base import BaseScraper
from .utils import clean_title

class _ScraperRegistry:
    def __init__(self):
        self._scrapers = {}

    def load_all(self):
        current_dir = os.path.dirname(__file__)
        for filename in os.listdir(current_dir):
            if filename.endswith(".py") and filename not in ["__init__.py", "base.py", "utils.py"]:
                module_name = f"scrapers.{filename[:-3]}"
                try:
                    module = importlib.import_module(module_name)
                    for name, obj in inspect.getmembers(module, inspect.isclass):
                        if issubclass(obj, BaseScraper) and obj is not BaseScraper:
                            instance = obj()
                            self._scrapers[instance.id] = instance
                except Exception as e:
                    logging.error(f"[Registry] Erreur au chargement du scraper {filename}: {e}")

    def get(self, scraper_id: str) -> BaseScraper:
        return self._scrapers.get(scraper_id)

    def get_by_type(self, lib_type: str) -> list:
        scrapers = [s for s in self._scrapers.values() if lib_type in s.supported_types]
        return sorted(scrapers, key=lambda x: x.display_name)

    def get_all(self) -> list:
        scrapers = list(self._scrapers.values())
        return sorted(scrapers, key=lambda x: x.display_name)

    def get_all_proxy_domains(self) -> list:
        """Récupère dynamiquement la liste blanche de tous les domaines autorisés."""
        domains = set()
        for s in self._scrapers.values():
            domains.update(getattr(s, 'proxy_domains', []))
        return list(domains)

ScraperRegistry = _ScraperRegistry()
ScraperRegistry.load_all()