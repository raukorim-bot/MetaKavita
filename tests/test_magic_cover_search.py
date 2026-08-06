"""Magic Input → cover search: detect, resolve, orchestrator, HTTP smoke."""

from __future__ import annotations

import pytest

from models import SeriesOverride
from services.cover_search import (
    collect_covers_http,
    cover_dict_from_fetch,
    iter_cover_jobs,
    run_cover_job,
)
from services.magic_input import (
    detect_provider_from_url,
    resolve_magic_cover_query,
)


class _DetectScraper:
    """Lightweight stand-in mirroring core extract_id_from_url patterns."""

    def __init__(self, sid, extract_fn):
        self.id = sid
        self.display_name = sid
        self.extract_id_from_url = extract_fn


def _anilist_extract(url):
    if "anilist.co/manga/" in (url or ""):
        parts = url.split("anilist.co/manga/")[-1].split("/")
        if parts and parts[0].isdigit():
            return parts[0]
    return None


def _mal_extract(url):
    if "myanimelist.net" in (url or "") and "/manga/" in (url or ""):
        parts = url.split("/manga/")[-1].split("/")
        if parts and parts[0].isdigit():
            return parts[0]
    return None


def _mangabaka_extract(url):
    if "mangabaka.org" in (url or "") or "mangabaka.dev" in (url or ""):
        return url.split("?")[0].rstrip("/").split("/")[-1]
    return None


@pytest.fixture
def core_url_scrapers(monkeypatch):
    """Minimal registry for detect_provider_from_url (no full app boot)."""
    scrapers = [
        _DetectScraper("ANILIST", _anilist_extract),
        _DetectScraper("MAL", _mal_extract),
        _DetectScraper("MANGABAKA", _mangabaka_extract),
    ]

    class _Reg:
        _scrapers = {s.id: s for s in scrapers}

        @staticmethod
        def get_all(scope="series"):
            return list(scrapers)

        @staticmethod
        def get(sid):
            return _Reg._scrapers.get(sid)

        @staticmethod
        def get_by_type(library_type):
            return list(scrapers)

    monkeypatch.setattr("services.magic_input.ScraperRegistry", _Reg)
    return _Reg


class TestDetectProviderFromUrl:
    def test_anilist(self, core_url_scrapers):
        assert (
            detect_provider_from_url("https://anilist.co/manga/30002/Berserk")
            == "ANILIST"
        )

    def test_mal(self, core_url_scrapers):
        assert (
            detect_provider_from_url("https://myanimelist.net/manga/2/Berserk")
            == "MAL"
        )

    def test_mangabaka(self, core_url_scrapers):
        assert (
            detect_provider_from_url("https://mangabaka.org/series/12345")
            == "MANGABAKA"
        )
        assert detect_provider_from_url("https://mangabaka.dev/12345") == "MANGABAKA"

    def test_foreign_url_rejected(self, core_url_scrapers):
        assert detect_provider_from_url("https://example.com/manga/2") is None

    def test_non_url(self, core_url_scrapers):
        assert detect_provider_from_url("30002") is None
        assert detect_provider_from_url("") is None


class TestResolveMagicCoverQuery:
    def test_no_magic(self):
        q = resolve_magic_cover_query({}, "Berserk")
        assert q.magic_active is False
        assert q.title_query == "Berserk"
        assert q.id_query is None
        assert q.resolved_provider is None

    def test_alt_title_without_magic(self):
        q = resolve_magic_cover_query(
            {"alternative_title": "ベルセルク"}, "Berserk"
        )
        assert q.title_query == "ベルセルク"
        assert q.magic_active is False

    def test_url_auto(self, core_url_scrapers):
        q = resolve_magic_cover_query(
            {
                "forced_id": "https://anilist.co/manga/30002/Berserk",
                "forced_provider": "AUTO",
            },
            "Berserk",
        )
        assert q.magic_active is True
        assert q.is_url is True
        assert q.resolved_provider == "ANILIST"
        assert q.id_query == "30002"
        assert q.title_query == "Berserk"
        assert q.raw_id_auto is False

    def test_url_forced_provider(self, core_url_scrapers):
        q = resolve_magic_cover_query(
            {
                "forced_id": "https://myanimelist.net/manga/2/Berserk",
                "forced_provider": "MAL",
            },
            "Berserk",
        )
        assert q.resolved_provider == "MAL"
        assert q.id_query == "2"

    def test_raw_id_auto(self):
        q = resolve_magic_cover_query(
            {"forced_id": "30002", "forced_provider": "AUTO"},
            "Berserk",
        )
        assert q.raw_id_auto is True
        assert q.id_query == "30002"
        assert q.resolved_provider is None

    def test_raw_id_forced_provider(self):
        q = resolve_magic_cover_query(
            {"forced_id": "30002", "forced_provider": "ANILIST"},
            "Berserk",
        )
        assert q.resolved_provider == "ANILIST"
        assert q.id_query == "30002"
        assert q.raw_id_auto is False

    def test_unrecognized_url(self, core_url_scrapers):
        q = resolve_magic_cover_query(
            {
                "forced_id": "https://example.com/nope/1",
                "forced_provider": "AUTO",
            },
            "Berserk",
        )
        assert q.magic_active is True
        assert q.resolved_provider is None
        assert q.id_query is None
        assert q.title_query == "Berserk"


class _FakeScraper:
    def __init__(
        self,
        sid,
        *,
        has_id=True,
        requires_proxy=False,
        types=None,
    ):
        self.id = sid
        self.display_name = sid
        self.localized_display_name = sid
        self.has_direct_id_support = has_id
        self.requires_proxy = requires_proxy
        self.supported_types = types or {"Manga"}
        self.fetch_calls = []
        self.cover_calls = []

    def fetch(self, query, library_type="Manga", is_id=False, existing_metadata=None):
        self.fetch_calls.append((query, is_id, library_type))
        if is_id:
            return {
                "title": f"{self.id}-{query}",
                "cover_url": f"https://cdn.example/{self.id}/{query}.jpg",
            }
        return None

    def fetch_covers(self, query, library_type="Manga"):
        self.cover_calls.append((query, library_type))
        return [
            {
                "provider": self.id,
                "title": query,
                "url": f"https://cdn.example/{self.id}/search.jpg",
            }
        ]

    def extract_id_from_url(self, url):
        if "anilist.co/manga/" in (url or ""):
            return "30002"
        return None


def _patch_registry(monkeypatch, scrapers):
    class _Reg:
        _scrapers = {s.id: s for s in scrapers}

        @staticmethod
        def get_by_type(library_type):
            return [
                s
                for s in scrapers
                if library_type in s.supported_types or "Manga" in s.supported_types
            ]

        @staticmethod
        def get_all(scope="series"):
            return list(scrapers)

        @staticmethod
        def get(sid):
            return _Reg._scrapers.get(sid)

    monkeypatch.setattr("services.cover_search.ScraperRegistry", _Reg)
    monkeypatch.setattr("services.magic_input.ScraperRegistry", _Reg)
    return _Reg


class TestIterCoverJobs:
    def test_no_magic_all_by_title(self, monkeypatch):
        a = _FakeScraper("A")
        b = _FakeScraper("B")
        _patch_registry(monkeypatch, [a, b])
        jobs = iter_cover_jobs({}, "Berserk", "Manga")
        assert len(jobs) == 2
        assert all(j.mode == "by_title" for j in jobs)
        assert all(j.query == "Berserk" for j in jobs)

    def test_url_auto_xor_by_id(self, monkeypatch):
        anilist = _FakeScraper("ANILIST")
        other = _FakeScraper("OTHER")
        _patch_registry(monkeypatch, [anilist, other])
        jobs = iter_cover_jobs(
            {
                "forced_id": "https://anilist.co/manga/30002/Berserk",
                "forced_provider": "AUTO",
            },
            "Berserk",
            "Manga",
        )
        by_mode = {j.scraper.id: j for j in jobs}
        assert by_mode["ANILIST"].mode == "by_id"
        assert by_mode["ANILIST"].query == "30002"
        assert by_mode["ANILIST"].priority == 0
        assert by_mode["OTHER"].mode == "by_title"
        assert by_mode["OTHER"].query == "Berserk"

    def test_never_schedules_fetch_covers_with_url(self, monkeypatch):
        a = _FakeScraper("ANILIST")
        b = _FakeScraper("OTHER")
        _patch_registry(monkeypatch, [a, b])
        jobs = iter_cover_jobs(
            {
                "forced_id": "https://anilist.co/manga/30002/Berserk",
                "forced_provider": "AUTO",
            },
            "Berserk",
            "Manga",
        )
        for j in jobs:
            if j.mode == "by_title":
                assert not j.query.startswith("http")

    def test_unrecognized_url_title_only(self, monkeypatch):
        a = _FakeScraper("A")
        _patch_registry(monkeypatch, [a])
        jobs = iter_cover_jobs(
            {
                "forced_id": "https://example.com/x/1",
                "forced_provider": "AUTO",
            },
            "Berserk",
            "Manga",
        )
        assert len(jobs) == 1
        assert jobs[0].mode == "by_title"
        assert jobs[0].query == "Berserk"

    def test_raw_id_forced_provider(self, monkeypatch):
        a = _FakeScraper("ANILIST")
        b = _FakeScraper("OTHER")
        _patch_registry(monkeypatch, [a, b])
        jobs = iter_cover_jobs(
            {"forced_id": "30002", "forced_provider": "ANILIST"},
            "Berserk",
            "Manga",
        )
        by_mode = {j.scraper.id: j for j in jobs}
        assert by_mode["ANILIST"].mode == "by_id"
        assert by_mode["OTHER"].mode == "by_title"


class TestRunCoverJob:
    def test_by_id_uses_fetch(self):
        s = _FakeScraper("ANILIST")
        from services.cover_search import CoverJob

        job = CoverJob(
            scraper=s, mode="by_id", query="30002", library_type="Manga", priority=0
        )
        covers = run_cover_job(job)
        assert len(covers) == 1
        assert covers[0]["url"].endswith("30002.jpg")
        assert covers[0]["display_url"] == covers[0]["url"]
        assert s.fetch_calls and s.fetch_calls[0][1] is True
        assert not s.cover_calls

    def test_by_title_uses_fetch_covers(self):
        s = _FakeScraper("OTHER")
        from services.cover_search import CoverJob

        job = CoverJob(
            scraper=s, mode="by_title", query="Berserk", library_type="Manga", priority=10
        )
        covers = run_cover_job(job)
        assert len(covers) == 1
        assert s.cover_calls == [("Berserk", "Manga")]
        assert not s.fetch_calls

    def test_refuses_url_in_by_title(self):
        s = _FakeScraper("OTHER")
        from services.cover_search import CoverJob

        job = CoverJob(
            scraper=s,
            mode="by_title",
            query="https://anilist.co/manga/1",
            library_type="Manga",
            priority=10,
        )
        assert run_cover_job(job) == []
        assert not s.cover_calls


class TestCollectCoversHttp:
    def test_prefixes_magic_by_id(self, monkeypatch):
        anilist = _FakeScraper("ANILIST")
        other = _FakeScraper("OTHER")
        _patch_registry(monkeypatch, [anilist, other])
        covers = collect_covers_http(
            {
                "forced_id": "https://anilist.co/manga/30002/Berserk",
                "forced_provider": "AUTO",
            },
            "Berserk",
            "Manga",
            max_covers=20,
        )
        assert covers
        assert covers[0]["url"].endswith("30002.jpg")


class TestImportSmoke:
    def test_import_chain(self):
        from services.magic_input import detect_provider_from_url, resolve_magic_cover_query
        from services.cover_search import iter_cover_jobs
        from services.enrichment_engine import enrich_series

        assert callable(detect_provider_from_url)
        assert callable(resolve_magic_cover_query)
        assert callable(iter_cover_jobs)
        assert callable(enrich_series)


class TestHttpRouteMagic:
    def test_covers_route_with_magic_url(
        self, client, isolated_db, mock_kavita_api, monkeypatch
    ):
        anilist = _FakeScraper("ANILIST")
        other = _FakeScraper("OTHER")
        _patch_registry(monkeypatch, [anilist, other])

        isolated_db.save_series_override(
            SeriesOverride(
                series_id=42,
                forced_id="https://anilist.co/manga/30002/Berserk",
                forced_provider="AUTO",
            )
        )
        mocker_patch = monkeypatch.setattr
        mocker_patch(
            "routes.series.KavitaAPI.get_library_type_for_series",
            lambda self, sid: "Manga",
        )

        res = client.get("/api/series/42/covers?series_name=Berserk")
        assert res.status_code == 200
        body = res.get_json()
        assert body["success"] is True
        assert body["covers"]
        assert any("30002" in (c.get("url") or "") for c in body["covers"])
        # OTHER must have searched by title, never by URL
        assert other.cover_calls
        assert all(not q.startswith("http") for q, _ in other.cover_calls)
        assert anilist.fetch_calls
        assert not anilist.cover_calls


class TestCoverDictFromFetch:
    def test_empty_without_cover_url(self):
        s = _FakeScraper("X")

        def _fetch(*a, **k):
            return {"title": "NoCover"}

        s.fetch = _fetch
        assert cover_dict_from_fetch(s, "1", "Manga") == []
