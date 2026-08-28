"""C88 E1 — query override Magic Input, sans HTTP."""
from __future__ import annotations

from scrapers.utils import MATCH_SCORE_KEY
from services.field_mapping_fetch import (
    blob_accepted_for_auto,
    override_fetch_args,
    title_from_hit,
)


def test_title_from_hit_prefers_title():
    assert title_from_hit({"title": "Berserk", "localized_name": "ベルセルク"}) == "Berserk"
    assert title_from_hit({"localized_name": "ベルセルク"}) == "ベルセルク"
    assert title_from_hit({}) == ""
    assert title_from_hit(None) == ""


def test_magic_mal_to_anilist_uses_title_not_mal_id():
    hit = {
        "title": "Berserk",
        "mal_id": 2,
        "url": "https://myanimelist.net/manga/2/Berserk",
        MATCH_SCORE_KEY: 0.95,
        "summary": "x",
    }
    query, is_id = override_fetch_args(
        is_forced_id=True,
        magic_query="2",
        hit_blob=hit,
        target_provider="ANILIST",
    )
    assert is_id is False
    assert query == "Berserk"


def test_override_same_provider_uses_own_id():
    hit = {"title": "Berserk", "mal_id": 2, "summary": "x"}
    query, is_id = override_fetch_args(
        is_forced_id=True,
        magic_query="2",
        hit_blob=hit,
        target_provider="MAL",
    )
    assert is_id is True
    assert query == "2"


def test_not_forced_id_uses_series_title():
    query, is_id = override_fetch_args(
        is_forced_id=False,
        magic_query="Series Name",
        hit_blob={"title": "Hit Title"},
        target_provider="ANILIST",
    )
    assert (query, is_id) == ("Series Name", False)


def test_blob_accepted_requires_useful_and_score():
    config = {"MATCH_THRESHOLD_CUSTOM": False}
    weak = {"summary": "s", MATCH_SCORE_KEY: 0.1}
    strong = {"summary": "s", MATCH_SCORE_KEY: 0.95}
    empty = {"title": "t", MATCH_SCORE_KEY: 0.99}
    assert blob_accepted_for_auto(weak, config) is False
    assert blob_accepted_for_auto(strong, config) is True
    assert blob_accepted_for_auto(empty, config) is False


def _plan(**kwargs):
    from services.field_mapping import MappingPlan, skip_keys_for_overrides

    overrides = kwargs.get("overrides") or {}
    default = kwargs.get("default", "CASCADE")
    noop = kwargs.get("mapping_noop")
    if noop is None:
        noop = default == "CASCADE" and not overrides
    return MappingPlan(
        library_type="Manga",
        wave=None,
        fetch_library_type="Manga",
        default=default,
        overrides=overrides,
        skip_keys=skip_keys_for_overrides(overrides),
        override_providers=tuple(dict.fromkeys(overrides.values())),
        mapping_noop=noop,
    )


def test_run_mapping_wave_tie_does_not_call_overrides(monkeypatch):
    from services import field_mapping_fetch as fm

    calls = []

    def fake_fetch_metadata(query, providers, smart_fusion=False, **kw):
        return (
            {
                "summary": "s",
                "_provider_used": "MAL",
                "_score_tie": True,
                "_tie_review_payload": {"above": [{"provider": "MAL"}], "below": []},
            },
            ["MAL", "ANILIST"],
        )

    def fake_call_scraper(pid, query, **kw):
        calls.append(pid)
        return pid, {"summary": "ov", MATCH_SCORE_KEY: 0.99}

    monkeypatch.setattr(fm, "fetch_metadata", fake_fetch_metadata)
    monkeypatch.setattr(fm, "call_scraper", fake_call_scraper)
    plan = _plan(overrides={"cover": "ANILIST"}, mapping_noop=False)
    result = fm.run_mapping_wave(
        plan, "Series", providers_list=["MAL", "ANILIST"], smart_fusion=True
    )
    assert result.score_tie is True
    assert calls == []
    assert result.data["_score_tie"] is True


def test_run_mapping_wave_noop_skips_skip_keys(monkeypatch):
    from services import field_mapping_fetch as fm

    seen = {}

    def fake_fetch_metadata(query, providers, smart_fusion=False, **kw):
        seen["skip_keys"] = kw.get("skip_keys", "MISSING")
        return {"summary": "s", "_provider_used": "MAL"}, ["MAL"]

    monkeypatch.setattr(fm, "fetch_metadata", fake_fetch_metadata)
    plan = _plan(mapping_noop=True)
    result = fm.run_mapping_wave(plan, "Series", providers_list=["MAL"], skip_keys={"summary"})
    assert seen["skip_keys"] == "MISSING"
    assert result.mapping_noop is True
    assert result.useful is True


def test_fetch_default_fixed_provider_retries_fallback_query(monkeypatch):
    from services import field_mapping_fetch as fm

    calls = []

    def fake_call_scraper(pid, query, **kw):
        calls.append({"query": query, "is_id": kw.get("is_id")})
        if kw.get("is_id"):
            return pid, None
        return pid, {"summary": "from title", MATCH_SCORE_KEY: 0.99, "title": query}

    monkeypatch.setattr(fm, "call_scraper", fake_call_scraper)
    plan = _plan(default="ANILIST", mapping_noop=False)
    result = fm.fetch_default(
        plan,
        "999999",
        {"is_forced_id": True, "fallback_query": "One Piece", "library_type": "Manga"},
    )
    assert result.data["title"] == "One Piece"
    assert any(c["is_id"] is True and c["query"] == "999999" for c in calls)
    assert any(c["is_id"] is False and c["query"] == "One Piece" for c in calls)


def test_empty_override_not_claimed_in_field_sources(monkeypatch):
    from services import field_mapping_fetch as fm

    def fake_fetch_metadata(query, providers, smart_fusion=False, **kw):
        return (
            {
                "summary": "s",
                "cover_url": "http://ani.jpg",
                "_provider_used": "ANILIST",
                MATCH_SCORE_KEY: 0.99,
            },
            ["ANILIST"],
        )

    def fake_call_scraper(pid, query, **kw):
        return pid, {"summary": "mal", MATCH_SCORE_KEY: 0.99}

    monkeypatch.setattr(fm, "fetch_metadata", fake_fetch_metadata)
    monkeypatch.setattr(fm, "call_scraper", fake_call_scraper)
    plan = _plan(overrides={"cover": "MAL"}, mapping_noop=False)
    result = fm.run_mapping_wave(
        plan, "Series", providers_list=["ANILIST", "MAL"], smart_fusion=True,
        config={"MATCH_THRESHOLD_CUSTOM": False},
    )
    assert result.data["cover_url"] == "http://ani.jpg"
    assert "cover" not in (result.data.get("_field_sources") or {})


def test_cascade_winner_override_reuses_blob_cover(monkeypatch):
    from services import field_mapping_fetch as fm

    def fake_fetch_metadata(query, providers, smart_fusion=False, **kw):
        assert "cover_url" in (kw.get("skip_keys") or [])
        return (
            {
                "summary": "s",
                "cover_url": "http://anilist/c.jpg",
                "_provider_used": "ANILIST",
                MATCH_SCORE_KEY: 0.99,
            },
            ["ANILIST"],
        )

    calls = []

    def fake_call_scraper(pid, query, **kw):
        calls.append(pid)
        return pid, {"summary": "no", "cover_url": "http://other.jpg", MATCH_SCORE_KEY: 0.99}

    monkeypatch.setattr(fm, "fetch_metadata", fake_fetch_metadata)
    monkeypatch.setattr(fm, "call_scraper", fake_call_scraper)
    plan = _plan(overrides={"cover": "ANILIST"}, mapping_noop=False)
    result = fm.run_mapping_wave(
        plan, "Series", providers_list=["ANILIST", "MAL"], smart_fusion=True,
        config={"MATCH_THRESHOLD_CUSTOM": False},
    )
    assert calls == []
    assert result.data["cover_url"] == "http://anilist/c.jpg"
    assert result.data["_field_sources"]["cover"] == "ANILIST"


def test_mapping_reuses_cascade_loser_blob(monkeypatch):
    """MAL déjà fetché dans la cascade : pas de second HTTP pour l'override cover."""
    from services import field_mapping_fetch as fm

    mal = {
        "summary": "mal",
        "cover_url": "http://mal/c.jpg",
        MATCH_SCORE_KEY: 0.99,
        "_provider_used": "MAL",
    }
    ani = {
        "summary": "ani",
        "cover_url": "http://ani/c.jpg",
        MATCH_SCORE_KEY: 0.99,
        "_provider_used": "ANILIST",
    }

    def fake_fetch_metadata(query, providers, smart_fusion=False, **kw):
        return (
            {
                **ani,
                "_cascade_blobs": {"ANILIST": ani, "MAL": mal},
            },
            ["ANILIST", "MAL"],
        )

    calls = []

    def fake_call_scraper(pid, query, **kw):
        calls.append(pid)
        return pid, {"summary": "no", "cover_url": "http://other.jpg", MATCH_SCORE_KEY: 0.99}

    monkeypatch.setattr(fm, "fetch_metadata", fake_fetch_metadata)
    monkeypatch.setattr(fm, "call_scraper", fake_call_scraper)
    plan = _plan(overrides={"cover": "MAL"}, mapping_noop=False)
    result = fm.run_mapping_wave(
        plan, "Series", providers_list=["ANILIST", "MAL"], smart_fusion=True,
        config={"MATCH_THRESHOLD_CUSTOM": False},
    )
    assert calls == []
    assert result.data["cover_url"] == "http://mal/c.jpg"
    assert result.data["_field_sources"]["cover"] == "MAL"
    assert "_cascade_blobs" not in (result.data or {})


def test_forced_id_does_not_reuse_cascade_blob_fetched_as_foreign_id(monkeypatch):
    """ID MAL collé : AniList dans la cascade a été appelé en is_id — on refetch au titre."""
    from services import field_mapping_fetch as fm

    mal = {
        "title": "Berserk",
        "summary": "mal",
        "cover_url": "http://mal/c.jpg",
        "mal_id": 2,
        "url": "https://myanimelist.net/manga/2/Berserk",
        MATCH_SCORE_KEY: 0.95,
        "_provider_used": "MAL",
    }
    wrong_ani = {
        "title": "Unrelated",
        "summary": "wrong",
        "cover_url": "http://anilist/wrong.jpg",
        MATCH_SCORE_KEY: 0.99,
        "_provider_used": "ANILIST",
    }

    def fake_fetch_metadata(query, providers, smart_fusion=False, **kw):
        return (
            {
                **mal,
                "_cascade_blobs": {
                    "MAL": {"blob": mal, "query": "2", "is_id": True},
                    "ANILIST": {"blob": wrong_ani, "query": "2", "is_id": True},
                },
            },
            ["MAL", "ANILIST"],
        )

    calls = []

    def fake_call_scraper(pid, query, **kw):
        calls.append({"pid": pid, "query": query, "is_id": kw.get("is_id")})
        return pid, {
            "title": "Berserk",
            "summary": "ani",
            "cover_url": "http://anilist/berserk.jpg",
            MATCH_SCORE_KEY: 0.99,
        }

    monkeypatch.setattr(fm, "fetch_metadata", fake_fetch_metadata)
    monkeypatch.setattr(fm, "call_scraper", fake_call_scraper)
    plan = _plan(overrides={"cover": "ANILIST"}, mapping_noop=False)
    result = fm.run_mapping_wave(
        plan,
        "2",
        providers_list=["MAL", "ANILIST"],
        smart_fusion=True,
        is_forced_id=True,
        config={"MATCH_THRESHOLD_CUSTOM": False},
    )
    assert calls == [{"pid": "ANILIST", "query": "Berserk", "is_id": False}]
    assert result.data["cover_url"] == "http://anilist/berserk.jpg"
    assert result.data["_field_sources"]["cover"] == "ANILIST"


def test_mapping_reuses_when_override_args_match_cascade(monkeypatch):
    from services import field_mapping_fetch as fm

    mal = {
        "summary": "mal",
        "cover_url": "http://mal/c.jpg",
        MATCH_SCORE_KEY: 0.99,
        "_provider_used": "MAL",
    }
    ani = {
        "summary": "ani",
        "cover_url": "http://ani/c.jpg",
        MATCH_SCORE_KEY: 0.99,
        "_provider_used": "ANILIST",
    }

    def fake_fetch_metadata(query, providers, smart_fusion=False, **kw):
        return (
            {
                **ani,
                "_cascade_blobs": {
                    "ANILIST": {"blob": ani, "query": "Series", "is_id": False},
                    "MAL": {"blob": mal, "query": "Series", "is_id": False},
                },
            },
            ["ANILIST", "MAL"],
        )

    calls = []

    def fake_call_scraper(pid, query, **kw):
        calls.append(pid)
        return pid, {"summary": "no", MATCH_SCORE_KEY: 0.99}

    monkeypatch.setattr(fm, "fetch_metadata", fake_fetch_metadata)
    monkeypatch.setattr(fm, "call_scraper", fake_call_scraper)
    plan = _plan(overrides={"cover": "MAL"}, mapping_noop=False)
    result = fm.run_mapping_wave(
        plan, "Series", providers_list=["ANILIST", "MAL"], smart_fusion=True,
        config={"MATCH_THRESHOLD_CUSTOM": False},
    )
    assert calls == []
    assert result.data["cover_url"] == "http://mal/c.jpg"


def test_mapping_remaining_overrides_run_in_parallel(monkeypatch):
    from services import field_mapping_fetch as fm
    import threading
    import time

    def fake_fetch_metadata(query, providers, smart_fusion=False, **kw):
        return (
            {
                "summary": "s",
                "_provider_used": "ANILIST",
                MATCH_SCORE_KEY: 0.99,
            },
            ["ANILIST"],
        )

    lock = threading.Lock()
    starts = {}

    def fake_call_scraper(pid, query, **kw):
        with lock:
            starts[pid] = time.time()
        time.sleep(0.25)
        return pid, {
            "summary": pid,
            "cover_url": f"http://{pid}.jpg",
            "staff": [{"name": pid}],
            MATCH_SCORE_KEY: 0.99,
        }

    monkeypatch.setattr(fm, "fetch_metadata", fake_fetch_metadata)
    monkeypatch.setattr(fm, "call_scraper", fake_call_scraper)
    plan = _plan(overrides={"cover": "MAL", "staff": "MANGABAKA"}, mapping_noop=False)
    t0 = time.time()
    result = fm.run_mapping_wave(
        plan, "Series", providers_list=["ANILIST"], smart_fusion=True,
        config={"MATCH_THRESHOLD_CUSTOM": False},
    )
    elapsed = time.time() - t0
    assert elapsed < 0.45, f"overrides still sequential ({elapsed:.2f}s)"
    assert abs(starts["MAL"] - starts["MANGABAKA"]) < 0.12
    assert result.data["_field_sources"]["cover"] == "MAL"
