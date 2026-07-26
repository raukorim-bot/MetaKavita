"""
Audit de l'auto-découverte des scrapers (`scrapers/__init__.py::_ScraperRegistry`).

Deux bugs corrigés ici :

1. `_extract_scrapers()` utilisait `inspect.getmembers(module, inspect.isclass)` sans
   filtrer par `obj.__module__`. Or `inspect.getmembers` remonte TOUTES les classes
   accessibles dans l'espace de noms du module, y compris celles simplement IMPORTÉES
   (ex: un scraper communautaire qui fait `from scrapers.mangabaka import MangaBakaScraper`
   pour en hériter, cas d'usage documenté dans CUSTOM_SCRAPERS.md). Sans filtre, la classe
   importée était ré-instanciée et ré-enregistrée comme si elle avait été définie dans ce
   fichier, dupliquant inutilement le chargement du scraper d'origine.

2. `self._scrapers[instance.id] = instance` écrasait silencieusement toute entrée
   existante en cas de collision d'id (officiel <-> communautaire, ou communautaire <->
   communautaire), sans aucune trace dans les logs — rendant un tel écrasement quasi
   impossible à diagnostiquer en cas d'erreur de copier-coller d'un id.

On utilise ici des instances "fraîches" de `_ScraperRegistry` (pas le singleton global
`ScraperRegistry`, déjà peuplé à l'import du package) et des modules Python synthétiques
(`types.ModuleType`) pour isoler le comportement de `_extract_scrapers()` sans dépendre du
système de fichiers ni du réseau.
"""
import logging
import types

from scrapers import _ScraperRegistry
from scrapers.base import BaseScraper


def _make_module(name, classes):
    module = types.ModuleType(name)
    for cls in classes:
        setattr(module, cls.__name__, cls)
    return module


class _FakeOfficialScraper(BaseScraper):
    id = "FAKE_OFFICIAL"
    display_name = "Fake Officiel"
    supported_types = {"Manga"}

    def fetch(self, query, library_type="Manga", is_id=False, existing_metadata=None):
        return None


def test_extract_scrapers_ignores_classes_merely_imported_not_defined_locally():
    registry = _ScraperRegistry()

    class _LocalSubclass(_FakeOfficialScraper):
        id = "FAKE_OFFICIAL_BOOK"
        display_name = "Fake Officiel (Book)"
        supported_types = {"Book"}

    # Simule un fichier communautaire qui fait `from scrapers.fake import _FakeOfficialScraper`
    # (classe importée, __module__ pointe toujours vers le module de test d'origine) puis
    # définit une sous-classe locale (__module__ réassigné pour simuler "défini ici").
    module = _make_module("custom_scrapers.fake_book_variant", [_FakeOfficialScraper, _LocalSubclass])
    _LocalSubclass.__module__ = module.__name__

    registry._extract_scrapers(module)

    assert registry.get("FAKE_OFFICIAL_BOOK") is not None
    assert registry.get("FAKE_OFFICIAL") is None, (
        "La classe simplement importée pour héritage ne doit pas être ré-enregistrée."
    )


def test_extract_scrapers_overriding_existing_id_logs_a_warning(caplog):
    registry = _ScraperRegistry()

    class _Official(BaseScraper):
        id = "SHARED_ID"
        display_name = "Officiel"
        supported_types = {"Manga"}

        def fetch(self, query, library_type="Manga", is_id=False, existing_metadata=None):
            return None

    official_module = _make_module("scrapers.fake_official", [_Official])
    _Official.__module__ = official_module.__name__
    registry._extract_scrapers(official_module)
    assert registry.get("SHARED_ID").display_name == "Officiel"

    class _Community(BaseScraper):
        id = "SHARED_ID"
        display_name = "Communautaire"
        supported_types = {"Book"}

        def fetch(self, query, library_type="Manga", is_id=False, existing_metadata=None):
            return None

    community_module = _make_module("custom_scrapers.fake_community", [_Community])
    _Community.__module__ = community_module.__name__

    with caplog.at_level(logging.WARNING):
        registry._extract_scrapers(community_module)

    assert registry.get("SHARED_ID").display_name == "Communautaire"
    assert any("SHARED_ID" in record.message for record in caplog.records), (
        "Un remplacement d'id doit être loggé pour rester diagnosticable."
    )


def test_extract_scrapers_reloading_the_same_module_does_not_warn(caplog):
    registry = _ScraperRegistry()

    class _Scraper(BaseScraper):
        id = "IDEMPOTENT"
        display_name = "Idempotent"
        supported_types = {"Manga"}

        def fetch(self, query, library_type="Manga", is_id=False, existing_metadata=None):
            return None

    module = _make_module("scrapers.fake_idempotent", [_Scraper])
    _Scraper.__module__ = module.__name__

    with caplog.at_level(logging.WARNING):
        registry._extract_scrapers(module)
        registry._extract_scrapers(module)

    assert not caplog.records
