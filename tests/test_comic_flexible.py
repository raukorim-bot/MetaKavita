"""
C35 — Comic Flexible (ID 5) : cascade Comic puis Manga, union des scrapers covers.
"""
from services import enrichment_engine
from kavita_api import KavitaAPI
from scrapers import _ScraperRegistry
from scrapers.base import BaseScraper
from scrapers.utils import library_type_for_scraper


def _base_config(**overrides):
    cfg = {
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "fake",
        "UI_LANG": "fr",
        "TARGET_LANG": "FR",
        "MAX_GENRES": 5,
        "MAX_TAGS": 15,
        "PROVIDER_1": "MANGA_FAKE",
        "PROVIDER_2": "NONE",
        "PROVIDER_3": "NONE",
        "COMIC_PROVIDER_1": "COMIC_FAKE",
        "COMIC_PROVIDER_2": "NONE",
        "COMIC_PROVIDER_3": "NONE",
        "SMART_COMPLETION": False,
        "SMART_SCORING": False,
        "AUTO_READING_DIR": False,
        "AUTO_COVER": False,
        "RESET_CONTEXT_ON_FORCE": False,
        "TRANSLATION_PROVIDER": "NONE",
        "DEEPL_API_KEY": "",
        "LOCALIZED_TITLE_MODE": "all",
        "LOCALIZED_TITLE_LANGS": "",
        "PUBLISHER_PREFERENCE": "LOCALIZED",
    }
    cfg.update(overrides)
    return cfg


class _ComicFake(BaseScraper):
    id = "COMIC_FAKE"
    display_name = "Comic Fake"
    supported_types = {"Comic"}
    has_direct_id_support = False

    def fetch(self, query, library_type="Comic", is_id=False, existing_metadata=None):
        return None

    def extract_id_from_url(self, url):
        return None


class _MangaFake(BaseScraper):
    id = "MANGA_FAKE"
    display_name = "Manga Fake"
    supported_types = {"Manga"}
    has_direct_id_support = False

    def fetch(self, query, library_type="Manga", is_id=False, existing_metadata=None):
        return None

    def extract_id_from_url(self, url):
        return None


def _patch_kavita_basics(mocker, isolated_db):
    mocker.patch("services.kavita_payload.get_max_genres", side_effect=lambda c=None: 5)
    mocker.patch("services.kavita_payload.get_max_tags", side_effect=lambda c=None: 15)
    mocker.patch.object(enrichment_engine, "get_all_cached_data", side_effect=isolated_db.get_all_cached_data)
    mocker.patch.object(enrichment_engine, "update_status")
    mocker.patch("services.kavita_payload.translate_text", side_effect=lambda text, *a, **k: text)

    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    mocker.patch.object(KavitaAPI, "get_series_metadata", return_value={
        "summary": "", "genres": [], "tags": [], "webLinks": "", "language": "",
    })
    mocker.patch.object(KavitaAPI, "get_library_type_for_series", return_value="ComicFlexible")
    mocker.patch.object(KavitaAPI, "get_series_deep_metadata", return_value={
        "isbn": None, "authors": [], "publisher": None, "year": None,
        "genres": [], "localized_name": None,
    })
    mocker.patch.object(KavitaAPI, "update_series_metadata", return_value=(True, "ok", True))
    mocker.patch.object(KavitaAPI, "update_series_general", return_value=(True, "ok", True))
    mocker.patch.object(KavitaAPI, "update_series_external_ids", return_value=True)


def test_flexible_falls_back_to_manga_when_comic_misses(mocker, isolated_db):
    """Vague Comic sans hit utile → seconde vague Manga appelée."""
    calls = []

    def _fake_fetch(query, providers_list, *args, **kwargs):
        calls.append({"providers": list(providers_list), "library_type": kwargs.get("library_type")})
        if kwargs.get("library_type") == "Manga":
            return (
                {
                    "title": "One Piece",
                    "summary": "Pirate king",
                    "genres": ["Action"],
                    "tags": [],
                    "staff": [],
                    "_provider_used": "MANGA_FAKE",
                },
                ["MANGA_FAKE"],
            )
        return (None, ["COMIC_FAKE"])

    mocker.patch.object(enrichment_engine, "load_config", return_value=_base_config())
    _patch_kavita_basics(mocker, isolated_db)

    comic = _ComicFake()
    manga = _MangaFake()

    def _get(pid):
        return {"COMIC_FAKE": comic, "MANGA_FAKE": manga}.get(pid)

    mocker.patch.object(enrichment_engine.ScraperRegistry, "get", side_effect=_get)
    mocker.patch.object(enrichment_engine.ScraperRegistry, "get_by_type", return_value=[comic])
    mocker.patch("metadata_fetcher.fetch_metadata", side_effect=_fake_fetch)

    ok, msg, used = enrichment_engine.enrich_series(42, "One Piece", force_update=True)

    assert ok is True
    assert len(calls) == 2
    assert calls[0]["library_type"] == "Comic"
    assert calls[0]["providers"] == ["COMIC_FAKE"]
    assert calls[1]["library_type"] == "Manga"
    assert calls[1]["providers"] == ["MANGA_FAKE"]
    assert "MANGA_FAKE" in used


def test_flexible_skips_manga_when_comic_hits(mocker, isolated_db):
    """Vague Comic avec hit utile → Manga non appelé."""
    calls = []

    def _fake_fetch(query, providers_list, *args, **kwargs):
        calls.append({"providers": list(providers_list), "library_type": kwargs.get("library_type")})
        return (
            {
                "title": "Batman",
                "summary": "Dark knight",
                "genres": ["Superhero"],
                "tags": [],
                "staff": [],
                "_provider_used": "COMIC_FAKE",
            },
            ["COMIC_FAKE"],
        )

    mocker.patch.object(enrichment_engine, "load_config", return_value=_base_config())
    _patch_kavita_basics(mocker, isolated_db)

    comic = _ComicFake()
    manga = _MangaFake()

    def _get(pid):
        return {"COMIC_FAKE": comic, "MANGA_FAKE": manga}.get(pid)

    mocker.patch.object(enrichment_engine.ScraperRegistry, "get", side_effect=_get)
    mocker.patch.object(enrichment_engine.ScraperRegistry, "get_by_type", return_value=[comic])
    mocker.patch("metadata_fetcher.fetch_metadata", side_effect=_fake_fetch)

    ok, msg, used = enrichment_engine.enrich_series(43, "Batman", force_update=True)

    assert ok is True
    assert len(calls) == 1
    assert calls[0]["library_type"] == "Comic"
    assert used == ["COMIC_FAKE"]


def test_manual_mode_falls_back_to_manga_on_a_weak_comic_hit(mocker, isolated_db):
    """Bug rapporté : en mode manuel, un hit Comic sous le seuil (donc dans
    `below`, pas rejeté comme en Auto) empêchait la bascule Manga. Elle doit
    désormais se déclencher sur le même critère qu'en Auto : aucun hit AU-DESSUS
    du seuil, peu importe si `below` contient des candidats faibles.
    """
    calls = []

    def _fake_fetch(query, providers_list, *args, **kwargs):
        library_type = kwargs.get("library_type")
        calls.append({"providers": list(providers_list), "library_type": library_type})
        if library_type == "Comic":
            weak_card = {
                "provider": "COMIC_FAKE",
                "title": "Wrong Comic Match",
                "summary": "Probablement pas la bonne série",
                "genres": [],
                "tags": [],
                "staff": [],
                "_match_score": 0.2,
            }
            return {"above": [], "below": [weak_card], "query": query}, ["COMIC_FAKE"]
        strong_card = {
            "provider": "MANGA_FAKE",
            "title": "One Piece",
            "summary": "Pirate king",
            "genres": ["Action"],
            "tags": [],
            "staff": [],
            "_match_score": 0.9,
        }
        return {"above": [strong_card], "below": [], "query": query}, ["MANGA_FAKE"]

    mocker.patch.object(
        enrichment_engine, "load_config",
        return_value=_base_config(MANUAL_REVIEW_MODE=True),
    )
    _patch_kavita_basics(mocker, isolated_db)

    comic = _ComicFake()
    manga = _MangaFake()

    def _get(pid):
        return {"COMIC_FAKE": comic, "MANGA_FAKE": manga}.get(pid)

    mocker.patch.object(enrichment_engine.ScraperRegistry, "get", side_effect=_get)
    mocker.patch.object(enrichment_engine.ScraperRegistry, "get_by_type", return_value=[comic])
    mocker.patch("metadata_fetcher.fetch_metadata", side_effect=_fake_fetch)

    created = {}
    mocker.patch(
        "services.manual_review.create_review_from_candidates",
        side_effect=lambda sid, name, payload: created.update(payload=payload),
    )

    ok, msg, used = enrichment_engine.enrich_series(44, "One Piece", force_update=True)

    assert ok is True
    assert msg == "PENDING_REVIEW"
    assert len(calls) == 2, "la vague Manga doit avoir été appelée"
    assert calls[0]["library_type"] == "Comic"
    assert calls[1]["library_type"] == "Manga"
    # La review proposée à l'utilisateur doit contenir le hit Manga fort, pas
    # le hit Comic faible qu'aurait gardé l'ancien critère `_candidates_empty`.
    assert created["payload"]["above"][0]["provider"] == "MANGA_FAKE"
    assert created["payload"]["below"] == []


def test_manual_mode_keeps_the_weak_comic_hit_when_manga_also_misses(mocker, isolated_db):
    """Si la bascule Manga ne trouve RIEN non plus, l'utilisateur doit encore
    pouvoir choisir manuellement le hit Comic faible plutôt que de tout perdre —
    contrainte propre au mode manuel, qui n'a pas d'équivalent côté Auto."""
    calls = []

    def _fake_fetch(query, providers_list, *args, **kwargs):
        library_type = kwargs.get("library_type")
        calls.append({"providers": list(providers_list), "library_type": library_type})
        if library_type == "Comic":
            weak_card = {
                "provider": "COMIC_FAKE",
                "title": "Wrong Comic Match",
                "summary": "Probablement pas la bonne série",
                "genres": [],
                "tags": [],
                "staff": [],
                "_match_score": 0.2,
            }
            return {"above": [], "below": [weak_card], "query": query}, ["COMIC_FAKE"]
        return {"above": [], "below": [], "query": query}, ["MANGA_FAKE"]

    mocker.patch.object(
        enrichment_engine, "load_config",
        return_value=_base_config(MANUAL_REVIEW_MODE=True),
    )
    _patch_kavita_basics(mocker, isolated_db)

    comic = _ComicFake()
    manga = _MangaFake()

    def _get(pid):
        return {"COMIC_FAKE": comic, "MANGA_FAKE": manga}.get(pid)

    mocker.patch.object(enrichment_engine.ScraperRegistry, "get", side_effect=_get)
    mocker.patch.object(enrichment_engine.ScraperRegistry, "get_by_type", return_value=[comic])
    mocker.patch("metadata_fetcher.fetch_metadata", side_effect=_fake_fetch)

    created = {}
    mocker.patch(
        "services.manual_review.create_review_from_candidates",
        side_effect=lambda sid, name, payload: created.update(payload=payload),
    )

    ok, msg, used = enrichment_engine.enrich_series(45, "Mystery Series", force_update=True)

    assert ok is True
    assert msg == "PENDING_REVIEW"
    assert len(calls) == 2
    assert created["payload"]["below"][0]["provider"] == "COMIC_FAKE"


def test_get_by_type_comic_flexible_unions_comic_and_manga():
    registry = _ScraperRegistry()
    registry._scrapers = {
        "COMIC_FAKE": _ComicFake(),
        "MANGA_FAKE": _MangaFake(),
    }
    ids = {s.id for s in registry.get_by_type("ComicFlexible")}
    assert ids == {"COMIC_FAKE", "MANGA_FAKE"}


def test_library_type_for_scraper_maps_flexible():
    assert library_type_for_scraper(_ComicFake(), "ComicFlexible") == "Comic"
    assert library_type_for_scraper(_MangaFake(), "ComicFlexible") == "Manga"
    assert library_type_for_scraper(_ComicFake(), "Comic") == "Comic"
