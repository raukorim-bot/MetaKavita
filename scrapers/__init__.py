import os
import sys
import types
import importlib.util
import inspect
import logging
import threading
from .base import BaseScraper
from translations import get_ui_translations


def _ensure_custom_package():
    """Namespace package vide pour les sideloads `custom_scrapers.*`."""
    if "custom_scrapers" not in sys.modules:
        pkg = types.ModuleType("custom_scrapers")
        pkg.__path__ = []
        pkg.__package__ = "custom_scrapers"
        sys.modules["custom_scrapers"] = pkg


class _ScraperRegistry:
    def __init__(self):
        self._scrapers = {}
        self._sources = {}  # scraper_id -> basename.py
        self._lock = threading.RLock()

    def load_all(self):
        """Seed core → data/scrapers, puis charge uniquement ce dossier."""
        from services.scraper_manager import (
            seed_core_scrapers,
            data_scrapers_dir,
            list_data_scraper_files,
            is_core_filename,
        )

        with self._lock:
            seed_core_scrapers()
            _ensure_custom_package()
            custom_dir = data_scrapers_dir()
            for filename in list_data_scraper_files():
                file_path = os.path.join(custom_dir, filename)
                stem = filename[:-3]
                # Core files use relative imports (`from .base` / `.utils`).
                # Load them as scrapers.<stem> from the data path so hotfixes apply
                # while package-relative imports still resolve.
                if is_core_filename(filename):
                    module_name = f"scrapers.{stem}"
                else:
                    module_name = f"custom_scrapers.{stem}"
                self._load_module_by_path(module_name, file_path, source_file=filename)

    def reload(self):
        """Vide le registre et recharge data/scrapers (après install/delete)."""
        with self._lock:
            stale = [
                name for name in list(sys.modules)
                if name.startswith("custom_scrapers.")
                or (
                    name.startswith("scrapers.")
                    and name not in (
                        "scrapers",
                        "scrapers.base",
                        "scrapers.utils",
                        "scrapers.wikidata_map",
                    )
                )
            ]
            for name in stale:
                # Only drop modules we loaded from data/scrapers (not base/utils).
                mod = sys.modules.get(name)
                if mod is None:
                    continue
                # Keep package helpers; drop provider modules so file reload works.
                if name in ("scrapers.base", "scrapers.utils", "scrapers.wikidata_map"):
                    continue
                sys.modules.pop(name, None)
            self._scrapers.clear()
            self._sources.clear()
            self.load_all()

    def _load_module_by_path(self, module_name, file_path, source_file=None):
        """Charge un scraper depuis le disque (data/scrapers)."""
        try:
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                if module_name.startswith("scrapers."):
                    module.__package__ = "scrapers"
                elif module_name.startswith("custom_scrapers."):
                    module.__package__ = "custom_scrapers"
                    _ensure_custom_package()
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                self._extract_scrapers(module, source_file=source_file or os.path.basename(file_path))
        except Exception as e:
            logging.error(get_ui_translations().get(
                "log_registry_custom_fail",
                "[Registry] Erreur au chargement du scraper personnalisé ({0}): {1}",
            ).format(file_path, e))

    def _extract_scrapers(self, module, source_file=None):
        """Extrait et enregistre les classes héritant de BaseScraper *définies* dans ce module.

        Le filtre `obj.__module__ == module.__name__` est indispensable : sans lui,
        `inspect.getmembers` remonte AUSSI les classes simplement importées dans le fichier
        (ex: un scraper communautaire qui fait `from scrapers.mangabaka import MangaBakaScraper`
        pour en hériter) et les ré-enregistrerait comme si elles avaient été définies ici,
        dupliquant inutilement l'enregistrement du scraper d'origine à chaque chargement.
        """
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ != module.__name__:
                continue
            if issubclass(obj, BaseScraper) and obj is not BaseScraper:
                instance = obj()
                existing = self._scrapers.get(instance.id)
                if existing is not None and existing.__class__ is not obj:
                    old = f"{existing.__class__.__module__}.{existing.__class__.__name__}"
                    new = f"{obj.__module__}.{obj.__name__}"
                    logging.warning(get_ui_translations().get(
                        "log_registry_replace",
                        "[Registry] Scraper {0} remplacé par {1} (chargé après). Vérifiez qu'il s'agit bien d'une surcharge volontaire.",
                    ).format(f"{instance.id} ({old})", new))
                self._scrapers[instance.id] = instance
                if source_file:
                    self._sources[instance.id] = os.path.basename(source_file)
                    from services.scraper_manager import resolve_origin
                    if resolve_origin(source_file) != "core":
                        logging.info(get_ui_translations().get(
                            "log_registry_custom_loaded",
                            "🔌 Scraper personnalisé chargé : {0} ({1})",
                        ).format(instance.display_name, instance.id))

    def _disabled_ids(self):
        try:
            from config_manager import get_disabled_scraper_ids
            return get_disabled_scraper_ids()
        except Exception:
            return set()

    def _passes_filters(self, scraper, *, include_disabled=False, scope=None):
        if scraper is None:
            return False
        if not include_disabled and scraper.id in self._disabled_ids():
            return False
        if scope:
            scopes = scraper.normalized_scopes() if hasattr(scraper, "normalized_scopes") else {"series"}
            if scope not in scopes:
                return False
        return True

    def get(self, scraper_id: str, *, include_disabled: bool = False) -> BaseScraper:
        scraper = self._scrapers.get(scraper_id)
        if not self._passes_filters(scraper, include_disabled=include_disabled):
            return None
        return scraper

    def get_by_type(self, lib_type: str, *, include_disabled: bool = False, scope: str = "series") -> list:
        # C35 : Comic (Flexible) = union Comic + Manga (dédupliquée par id)
        if lib_type == "ComicFlexible":
            seen = {}
            for s in list(self._scrapers.values()):
                if not self._passes_filters(s, include_disabled=include_disabled, scope=scope):
                    continue
                if "Comic" in s.supported_types or "Manga" in s.supported_types:
                    seen[s.id] = s
            return sorted(seen.values(), key=lambda x: x.display_name)

        scrapers = [
            s for s in self._scrapers.values()
            if lib_type in s.supported_types
            and self._passes_filters(s, include_disabled=include_disabled, scope=scope)
        ]
        return sorted(scrapers, key=lambda x: x.display_name)

    def get_by_scope(self, scope: str, *, include_disabled: bool = False) -> list:
        scrapers = [
            s for s in self._scrapers.values()
            if self._passes_filters(s, include_disabled=include_disabled, scope=scope)
        ]
        return sorted(scrapers, key=lambda x: x.display_name)

    def get_all(self, *, include_disabled: bool = False, scope: str = None) -> list:
        scrapers = [
            s for s in self._scrapers.values()
            if self._passes_filters(s, include_disabled=include_disabled, scope=scope)
        ]
        return sorted(scrapers, key=lambda x: x.display_name)

    def get_source_file(self, scraper_id: str) -> str:
        return self._sources.get(scraper_id) or ""

    def get_all_proxy_domains(self) -> list:
        """Liste blanche domaines (tous scrapers chargés, y compris disabled)."""
        domains = set()
        for s in self._scrapers.values():
            domains.update(getattr(s, 'proxy_domains', []))
        return list(domains)

    def get_proxy_cover_hosts(self) -> list:
        """Hôtes dont l'<img> navigateur doit passer par /api/proxy-image.

        Agrège `proxy_domains` des scrapers avec `requires_proxy=True`
        (y compris disabled), pour Manual Review / previews.
        """
        hosts = set()
        for s in self._scrapers.values():
            if not getattr(s, "requires_proxy", False):
                continue
            for d in getattr(s, "proxy_domains", []) or []:
                d = (d or "").strip().lower()
                if d:
                    hosts.add(d)
        return sorted(hosts)


ScraperRegistry = _ScraperRegistry()
ScraperRegistry.load_all()
