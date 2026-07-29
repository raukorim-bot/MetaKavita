"""
Non-régression : plafonds MAX_GENRES / MAX_TAGS appliqués dans les scrapers
et dans enrichment_engine (filet avant écriture Kavita).

Pas d'appels réseau : on exerce uniquement les parseurs / builders internes
(`_build_candidate`, `_parse_*`) et un enrich_series mocké.
"""
from kavita_api import KavitaAPI
from scrapers.anilist import AnilistScraper
from scrapers.googlebooks import GoogleBooksScraper
from scrapers.hardcover import HardcoverScraper
from scrapers.mangabaka import MangaBakaScraper
from scrapers.mangaupdates import MangaUpdatesScraper
from scrapers.openlibrary import OpenLibraryScraper
from scrapers.shikimori import ShikimoriScraper
from services import enrichment_engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cap_genres(monkeypatch, module_path: str, n: int):
    monkeypatch.setattr(f"{module_path}.get_max_genres", lambda config=None: n)


def _cap_tags(monkeypatch, module_path: str, n: int):
    monkeypatch.setattr(f"{module_path}.get_max_tags", lambda config=None: n)


# ---------------------------------------------------------------------------
# AniList
# ---------------------------------------------------------------------------

def test_anilist_truncates_genres_and_tags(monkeypatch):
    _cap_genres(monkeypatch, "scrapers.anilist", 3)
    _cap_tags(monkeypatch, "scrapers.anilist", 4)
    scraper = AnilistScraper()
    data = {
        "title": {"romaji": "Test Manga"},
        "description": "summary",
        "coverImage": {"extraLarge": "https://example.com/c.jpg"},
        "genres": [f"Genre{i}" for i in range(10)],
        "tags": [{"name": f"Tag{i}"} for i in range(12)],
        "startDate": {"year": 2020},
        "status": "RELEASING",
        "staff": {"edges": []},
        "characters": {"edges": []},
        "isAdult": False,
        "countryOfOrigin": "JP",
        "id": 1,
        "idMal": 2,
        "externalLinks": [],
    }
    candidate = scraper._build_candidate(data)
    assert candidate["genres"] == ["Genre0", "Genre1", "Genre2"]
    assert candidate["tags"] == ["Tag0", "Tag1", "Tag2", "Tag3"]


# ---------------------------------------------------------------------------
# MangaBaka
# ---------------------------------------------------------------------------

def test_mangabaka_truncates_genres_and_tags(monkeypatch):
    _cap_genres(monkeypatch, "scrapers.mangabaka", 2)
    _cap_tags(monkeypatch, "scrapers.mangabaka", 3)
    scraper = MangaBakaScraper()
    candidate = scraper._build_candidate({
        "id": 1,
        "name": "Test",
        "tags": [
            {"name": f"Genre{i}", "is_genre": True} for i in range(6)
        ] + [
            {"name": f"Tag{i}", "is_genre": False} for i in range(8)
        ],
    }, pub_pref="LOCALIZED")
    assert len(candidate["genres"]) == 2
    assert candidate["genres"] == ["Genre0", "Genre1"]
    assert len(candidate["tags"]) == 3
    assert candidate["tags"] == ["Tag0", "Tag1", "Tag2"]


# ---------------------------------------------------------------------------
# Google Books
# ---------------------------------------------------------------------------

def test_googlebooks_truncates_genres_and_tags(monkeypatch):
    _cap_genres(monkeypatch, "scrapers.googlebooks", 2)
    _cap_tags(monkeypatch, "scrapers.googlebooks", 4)
    scraper = GoogleBooksScraper()
    candidate = scraper._build_candidate({
        "title": "A Book",
        "categories": [f"Cat {i}" for i in range(8)],
        "authors": ["Author"],
        "description": "desc",
        "publishedDate": "2019-01-01",
        "imageLinks": {},
    })
    assert candidate["genres"] == ["Cat 0", "Cat 1"]
    # tags = Books + GoogleBooks + categories (sliced)
    assert len(candidate["tags"]) == 4
    assert candidate["tags"][:2] == ["Books", "GoogleBooks"]


# ---------------------------------------------------------------------------
# MangaUpdates — plus de categories[:10] en dur
# ---------------------------------------------------------------------------

def test_mangaupdates_categories_not_hardcapped_at_10(monkeypatch):
    """Avec MAX_TAGS élevé, toutes les categories doivent pouvoir passer (ex-[:10])."""
    _cap_genres(monkeypatch, "scrapers.mangaupdates", 5)
    _cap_tags(monkeypatch, "scrapers.mangaupdates", 25)
    scraper = MangaUpdatesScraper()
    record = {
        "series_id": 42,
        "title": "MU Series",
        "description": "desc",
        "genres": [{"genre": "Action"}, {"genre": "Drama"}],
        "categories": [{"category": f"Cat{i}"} for i in range(15)],
        "authors": [],
        "publishers": [],
        "completed": True,
    }
    candidate = scraper._parse_series_record(record, pub_pref="LOCALIZED")
    assert candidate is not None
    assert candidate["genres"] == ["Action", "Drama"]
    # MangaUpdates + 2 genres + 15 categories = 18
    assert len(candidate["tags"]) == 18
    assert "Cat14" in candidate["tags"]
    assert "Cat9" in candidate["tags"]


def test_mangaupdates_still_respects_max_tags(monkeypatch):
    _cap_genres(monkeypatch, "scrapers.mangaupdates", 5)
    _cap_tags(monkeypatch, "scrapers.mangaupdates", 6)
    scraper = MangaUpdatesScraper()
    record = {
        "series_id": 1,
        "title": "MU",
        "description": "",
        "genres": [{"genre": "Action"}],
        "categories": [{"category": f"Cat{i}"} for i in range(20)],
        "authors": [],
        "publishers": [],
    }
    candidate = scraper._parse_series_record(record, pub_pref="LOCALIZED")
    assert len(candidate["tags"]) == 6


def test_mangaupdates_truncates_genres(monkeypatch):
    _cap_genres(monkeypatch, "scrapers.mangaupdates", 2)
    _cap_tags(monkeypatch, "scrapers.mangaupdates", 50)
    scraper = MangaUpdatesScraper()
    record = {
        "series_id": 1,
        "title": "MU",
        "description": "",
        "genres": [{"genre": f"G{i}"} for i in range(8)],
        "categories": [],
        "authors": [],
        "publishers": [],
    }
    candidate = scraper._parse_series_record(record, pub_pref="LOCALIZED")
    assert candidate["genres"] == ["G0", "G1"]


# ---------------------------------------------------------------------------
# OpenLibrary — boucle build ne doit plus hardcoder 5
# ---------------------------------------------------------------------------

def test_openlibrary_build_loop_respects_max_genres_above_five(monkeypatch):
    _cap_genres(monkeypatch, "scrapers.openlibrary", 7)
    _cap_tags(monkeypatch, "scrapers.openlibrary", 30)
    scraper = OpenLibraryScraper()
    subjects = [f"Subject {i}" for i in range(12)]
    candidate = scraper._parse_work_record(
        {"title": "OL Work", "key": "/works/OL1W"},
        {"title": "OL Work", "subject": subjects},
        {},
    )
    assert candidate is not None
    assert len(candidate["genres"]) == 7
    assert candidate["genres"][0] == "Subject 0"
    assert candidate["genres"][-1] == "Subject 6"


def test_openlibrary_truncates_tags(monkeypatch):
    _cap_genres(monkeypatch, "scrapers.openlibrary", 5)
    _cap_tags(monkeypatch, "scrapers.openlibrary", 5)
    scraper = OpenLibraryScraper()
    subjects = [f"Topic {i}" for i in range(10)]
    candidate = scraper._parse_work_record(
        {"title": "OL", "key": "/works/OL2W"},
        {"title": "OL", "subject": subjects},
        {},
    )
    # tags commence par OpenLibrary, Book puis subjects
    assert len(candidate["tags"]) == 5


# ---------------------------------------------------------------------------
# Hardcover
# ---------------------------------------------------------------------------

def test_hardcover_truncates_genres(monkeypatch):
    _cap_genres(monkeypatch, "scrapers.hardcover", 2)
    scraper = HardcoverScraper()
    candidate = scraper._build_candidate({
        "title": "HC Book",
        "description": "d",
        "genres": [f"G{i}" for i in range(9)],
        "author_names": ["A"],
    })
    assert candidate is not None
    assert candidate["genres"] == ["G0", "G1"]
    assert candidate["tags"] == ["Hardcover"]


# ---------------------------------------------------------------------------
# Shikimori (mock HTTP roles)
# ---------------------------------------------------------------------------

def test_shikimori_truncates_genres_and_tags(monkeypatch, mocker):
    _cap_genres(monkeypatch, "scrapers.shikimori", 2)
    _cap_tags(monkeypatch, "scrapers.shikimori", 3)
    mocker.patch("scrapers.shikimori.requests.get", side_effect=Exception("no network"))
    scraper = ShikimoriScraper()
    candidate = scraper._parse_shikimori_record({
        "id": 99,
        "name": "Shi",
        "description": "desc",
        "genres": [{"name": f"G{i}"} for i in range(6)],
        "status": "released",
        "kind": "manga",
    }, headers={"User-Agent": "test"})
    assert candidate is not None
    assert candidate["genres"] == ["G0", "G1"]
    # tags = Shikimori + genres (avant slice genres) puis [:max_tags]
    assert len(candidate["tags"]) == 3
    assert candidate["tags"][0] == "Shikimori"


# ---------------------------------------------------------------------------
# enrichment_engine → kavita_payload — filet get_max_genres / get_max_tags
# ---------------------------------------------------------------------------

def test_enrichment_engine_caps_genres_and_tags_before_kavita(mocker, isolated_db):
    """Le filet moteur doit tronquer même si le scraper renvoie trop d'items.

    `isolated_db` est indispensable ici : ce test est le seul du fichier à
    traverser `enrich_series()` en entier, et le chemin de succès appelle
    `record_enrichment_telemetry()` — qui n'est pas mocké et ouvre directement
    `db_manager.DB_FILE`. Sans la fixture, chaque exécution de la suite écrit
    donc dans le vrai `data/cache.db` du dépôt : compteurs `series_enriched` /
    `matches_won` incrémentés, et un provider fictif `FAKE` ajouté au podium des
    statistiques C7. La fixture suffit à tout isoler car `db_manager` relit sa
    globale `DB_FILE` à chaque appel (voir tests/conftest.py).
    """
    captured = {}

    mocker.patch.object(enrichment_engine, "load_config", return_value={
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "fake",
        "UI_LANG": "fr",
        "TARGET_LANG": "FR",
        "MAX_GENRES": 3,
        "MAX_TAGS": 4,
        "PROVIDER_1": "FAKE",
        "PROVIDER_2": "NONE",
        "PROVIDER_3": "NONE",
        "SMART_COMPLETION": False,
        "SMART_SCORING": False,
        "AUTO_READING_DIR": False,
        "AUTO_COVER": False,
        "RESET_CONTEXT_ON_FORCE": False,
        "TRANSLATION_PROVIDER": "NONE",
        "DEEPL_API_KEY": "",
    })
    # Plafonds appliqués dans services.kavita_payload (plus dans enrichment_engine).
    mocker.patch("services.kavita_payload.get_max_genres", side_effect=lambda config=None: 3)
    mocker.patch("services.kavita_payload.get_max_tags", side_effect=lambda config=None: 4)
    mocker.patch.object(enrichment_engine, "get_all_cached_data", return_value={})
    mocker.patch.object(enrichment_engine, "update_status")
    mocker.patch("services.kavita_payload.translate_text", side_effect=lambda text, *a, **k: text)

    class FakeScraper:
        id = "FAKE"
        display_name = "Fake"
        supported_types = {"Manga"}
        has_direct_id_support = False

        def extract_id_from_url(self, url):
            return None

    fake = FakeScraper()
    mocker.patch.object(enrichment_engine.ScraperRegistry, "get", return_value=fake)
    mocker.patch.object(enrichment_engine.ScraperRegistry, "get_by_type", return_value=[fake])

    oversized = {
        "title": "T",
        "summary": "S",
        "genres": [f"G{i}" for i in range(10)],
        "tags": [f"T{i}" for i in range(12)],
        "staff": [],
        "characters": [],
        "_provider_used": "FAKE",
    }
    mocker.patch(
        "metadata_fetcher.fetch_metadata",
        return_value=(oversized, ["FAKE"]),
    )

    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    mocker.patch.object(KavitaAPI, "get_series_metadata", return_value={
        "summary": "",
        "genres": [],
        "tags": [],
        "webLinks": "",
        "language": "",
    })
    mocker.patch.object(KavitaAPI, "get_library_type_for_series", return_value="Manga")
    mocker.patch.object(KavitaAPI, "get_series_deep_metadata", return_value={
        "isbn": None,
        "authors": [],
        "publisher": None,
        "year": None,
        "genres": [],
        "localized_name": None,
    })

    def _capture_metadata(metadata):
        captured["metadata"] = metadata
        return True, "ok"

    mocker.patch.object(KavitaAPI, "update_series_metadata", side_effect=_capture_metadata)
    mocker.patch.object(KavitaAPI, "update_series_general", return_value=(True, "ok"))
    mocker.patch.object(KavitaAPI, "update_series_external_ids", return_value=True)

    ok, msg, used = enrichment_engine.enrich_series(9001, "Cap Test", force_update=True)
    assert ok is True
    assert "metadata" in captured
    genres = [g["title"] for g in captured["metadata"]["genres"]]
    tags = [t["title"] for t in captured["metadata"]["tags"]]
    assert genres == ["G0", "G1", "G2"]
    assert tags == ["T0", "T1", "T2", "T3"]


def test_helpers_defaults_still_stable():
    """Garde-fou : défauts documentés pour power-users."""
    from config_manager import get_max_genres, get_max_tags
    assert get_max_genres({}) == 5
    assert get_max_tags({}) == 15
