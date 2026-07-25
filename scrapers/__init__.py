import os
import sys
import importlib
import importlib.util
import inspect
import logging
from .base import BaseScraper
from .utils import clean_title

class _ScraperRegistry:
    def __init__(self):
        self._scrapers = {}

    def load_all(self):
        # 1. Charger les scrapers officiels (Inclus dans l'image Docker)
        current_dir = os.path.dirname(__file__)
        for filename in os.listdir(current_dir):
            if filename.endswith(".py") and filename not in ["__init__.py", "base.py", "utils.py"]:
                module_name = f"scrapers.{filename[:-3]}"
                self._load_module_by_name(module_name)

        # 2. Création et chargement des scrapers personnalisés dans data/scrapers
        custom_dir = os.path.abspath(os.path.join(os.getcwd(), "data", "scrapers"))
        
        # On crée le dossier data/scrapers s'il n'existe pas encore
        if not os.path.exists(custom_dir):
            try:
                os.makedirs(custom_dir)
            except Exception as e:
                logging.error(f"[Registry] Impossible de créer le dossier {custom_dir}: {e}")
        else:
            # On scanne les fichiers Python déposés par l'utilisateur
            for filename in os.listdir(custom_dir):
                if filename.endswith(".py") and not filename.startswith("__"):
                    file_path = os.path.join(custom_dir, filename)
                    module_name = f"custom_scrapers.{filename[:-3]}"
                    self._load_module_by_path(module_name, file_path)

    def _load_module_by_name(self, module_name):
        """Charge un scraper interne de manière classique."""
        try:
            module = importlib.import_module(module_name)
            self._extract_scrapers(module)
        except Exception as e:
            logging.error(f"[Registry] Erreur au chargement du scraper officiel {module_name}: {e}")

    def _load_module_by_path(self, module_name, file_path):
        """Charge un scraper externe déposé par un utilisateur depuis le disque."""
        try:
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                self._extract_scrapers(module)
        except Exception as e:
            logging.error(f"[Registry] Erreur au chargement du scraper personnalisé ({file_path}): {e}")

    def _extract_scrapers(self, module):
        """Extrait et enregistre toutes les classes héritant de BaseScraper dans un fichier."""
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, BaseScraper) and obj is not BaseScraper:
                instance = obj()
                self._scrapers[instance.id] = instance
                # Petit log optionnel pour confirmer l'enregistrement d'un scraper custom
                if "custom_scrapers" in module.__name__:
                    logging.info(f"🔌 Scraper personnalisé chargé : {instance.display_name} ({instance.id})")

    def get(self, scraper_id: str) -> BaseScraper:
        return self._scrapers.get(scraper_id)

    def get_by_type(self, lib_type: str) -> list:
        scrapers = [s for s in self._scrapers.values() if lib_type in s.supported_types]
        return sorted(scrapers, key=lambda x: x.display_name)

    def get_all(self) -> list:
        scrapers = list(self._scrapers.values())
        return sorted(scrapers, key=lambda x: x.display_name)

    def get_all_proxy_domains(self) -> list:
        """Récupère dynamiquement la liste blanche de tous les domaines autorisés (Officiels + Custom)."""
        domains = set()
        for s in self._scrapers.values():
            domains.update(getattr(s, 'proxy_domains', []))
        return list(domains)

ScraperRegistry = _ScraperRegistry()
ScraperRegistry.load_all()