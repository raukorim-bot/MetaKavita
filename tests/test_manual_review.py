"""
Tests mode manuel C29 : merge_candidates, return_candidates, pending CRUD,
create_review / choice_and_merge / skip, apply_manual_review (is_top1 / field_edits).
"""
from types import SimpleNamespace

import pytest

import metadata_fetcher
from models import SeriesOverride
from services import manual_review as mr
from services import enrichment_engine
from scrapers.utils import MATCH_SCORE_KEY


@pytest.fixture(autouse=True)
def _silence_emits(monkeypatch):
    monkeypatch.setattr(mr, "_safe_emit", lambda *a, **k: None)
    monkeypatch.setattr(mr, "emit_pending_count", lambda: 0)
    # Évite les appels réseau pendant create_review (trad. anticipée des résumés)
    monkeypatch.setattr(
        "translator.translate_text",
        lambda text, *a, **k: text,
    )


def _make_scraper(scraper_id, fetch_fn, supported_types=None, rate_limit=0.0):
    return SimpleNamespace(
        id=scraper_id,
        supported_types=supported_types or {"Manga"},
        rate_limit=rate_limit,
        extract_id_from_url=lambda url: None,
        fetch=fetch_fn,
    )


def _install_fake_registry(monkeypatch, scrapers_by_id):
    fake_registry = SimpleNamespace(get=lambda scraper_id: scrapers_by_id.get(scraper_id))
    monkeypatch.setattr(metadata_fetcher, "ScraperRegistry", fake_registry)


def test_build_candidate_card_keeps_full_summary_and_meta():
    long_summary = "A" * 400
    card = metadata_fetcher.build_candidate_card(
        "MAL",
        {
            MATCH_SCORE_KEY: 0.91,
            "title": "One Piece",
            "summary": long_summary,
            "cover_url": "https://cdn.example/op.jpg",
            "year": 1997,
            "status": "Ongoing",
            "publisher": "Shueisha",
            "genres": ["Action", "Adventure"],
            "tags": ["Pirates"],
            "staff": ["Eiichiro Oda"],
            "writers": ["Extra Writer"],
            "format": "Manga",
            "age_rating": "Teen",
            "localized_name": "One Piece",
        },
        below_threshold=False,
    )
    assert card["summary"] == long_summary
    assert card["summary_excerpt"] == long_summary[:280]
    assert card["year"] == 1997
    assert card["status"] == "Ongoing"
    assert card["publisher"] == "Shueisha"
    assert card["genres"] == ["Action", "Adventure"]
    assert "Eiichiro Oda" in card["staff"]
    assert "Extra Writer" in card["staff"]
    assert card["localized_name"] == "One Piece"


def test_build_candidate_card_parses_anilist_staff_edges():
    card = metadata_fetcher.build_candidate_card(
        "ANILIST",
        {
            MATCH_SCORE_KEY: 0.9,
            "title": "One Piece",
            "staff": [
                {"role": "Story", "node": {"name": {"full": "Eiichiro Oda"}}},
                {"role": "Art", "node": {"name": {"full": "Eiichiro Oda"}}},
                {"role": "Story", "node": {"name": {"full": "Assistant"}}},
            ],
        },
    )
    assert any("Eiichiro Oda" in s for s in card["staff"])
    assert any("Story" in s for s in card["staff"])
    assert any("Assistant" in s for s in card["staff"])


def test_build_candidate_card_derives_localized_from_titles():
    card = metadata_fetcher.build_candidate_card(
        "ANILIST",
        {
            MATCH_SCORE_KEY: 0.9,
            "title": "One Piece",
            "titles": [
                {"lang": "ja-ro", "value": "One Piece"},
                {"lang": "en", "value": "One Piece"},
                {"lang": "ja", "value": "ワンピース"},
            ],
            "alternative_titles": ["One Piece", "ワンピース"],
        },
    )
    assert "ワンピース" in card["localized_name"]
    assert "One Piece" in card["localized_name"]


def test_candidate_card_for_ui_derives_localized_from_nested_data():
    legacy = {
        "provider": "ANILIST",
        "score": 0.88,
        "title": "OP",
        "localized_name": "",
        "data": {
            "title": "OP",
            "titles": [
                {"lang": "en", "value": "One Piece"},
                {"lang": "ja", "value": "ワンピース"},
            ],
        },
    }
    ui = metadata_fetcher.candidate_card_for_ui(legacy)
    assert "One Piece" in ui["localized_name"]
    assert "ワンピース" in ui["localized_name"]


def test_candidate_card_for_ui_reads_nested_data_for_legacy_queue_rows():
    legacy = {
        "provider": "ANILIST",
        "score": 0.88,
        "title": "Legacy",
        "summary_excerpt": "short only",
        "data": {
            "summary": "Full nested summary for informed pick.",
            "year": 2012,
            "status": "Completed",
            "genres": ["Drama"],
            "staff": [{"name": "Author X"}],
            "publisher": "Kadokawa",
        },
    }
    ui = metadata_fetcher.candidate_card_for_ui(legacy)
    assert ui["summary"] == "Full nested summary for informed pick."
    assert ui["year"] == 2012
    assert ui["status"] == "Completed"
    assert ui["genres"] == ["Drama"]
    assert ui["staff"] == ["Author X"]
    assert ui["publisher"] == "Kadokawa"
    assert "data" not in ui


def test_translate_candidate_summaries_before_pick(monkeypatch):
    calls = []

    def fake_translate(text, *a, **k):
        calls.append(text)
        return f"FR:{text}"

    monkeypatch.setattr("translator.translate_text", fake_translate)
    monkeypatch.setattr(
        "config_manager.load_config",
        lambda: {"TARGET_LANG": "FR", "TRANSLATION_PROVIDER": "GOOGLE"},
    )

    payload = {
        "above": [
            {
                "provider": "A",
                "score": 0.9,
                "summary": "Hello world",
                "data": {"summary": "Hello world", "title": "T"},
            },
            {
                "provider": "B",
                "score": 0.8,
                "summary": "Hello world",
                "data": {"summary": "Hello world"},
            },
        ],
        "below": [
            {
                "provider": "C",
                "score": 0.4,
                "summary": "Other",
                "data": {"summary": "Other"},
            },
        ],
        "query": "q",
    }
    out, n = mr.translate_candidate_summaries(payload)
    assert n == 2  # dédup "Hello world"
    assert calls == ["Hello world", "Other"]
    assert out["above"][0]["summary"] == "FR:Hello world"
    assert out["above"][0]["data"]["summary"] == "FR:Hello world"
    assert out["above"][0]["data"][mr.SUMMARY_TRANSLATED_KEY] is True
    assert out["above"][1]["summary"] == "FR:Hello world"
    assert out["below"][0]["summary"] == "FR:Other"

    out2, n2 = mr.translate_candidate_summaries(out)
    assert n2 == 0
    assert len(calls) == 2


def test_create_review_translates_summaries(isolated_db, monkeypatch):
    monkeypatch.setattr(
        "translator.translate_text",
        lambda text, *a, **k: f"TR[{text}]",
    )
    payload = {
        "above": [
            {
                "provider": "MAL",
                "score": 0.9,
                "title": "X",
                "summary": "English blurb",
                "data": {"summary": "English blurb", "title": "X"},
            },
        ],
        "below": [],
        "query": "x",
    }
    rid = mr.create_review_from_candidates(42, "Series X", payload)
    row = isolated_db.get_pending_review(rid)
    cands = __import__("json").loads(row["candidates_json"])
    assert cands["above"][0]["summary"] == "TR[English blurb]"
    assert cands["above"][0]["data"]["_summary_translated"] is True


def test_create_review_persists_the_library_id_for_the_kavita_verification_link(isolated_db):
    """`library_id` alimente le lien « Voir dans Kavita » du pick UI
    (manual_review.js::updateKavitaLink) — doit survivre le park en base."""
    payload = {"above": [], "below": [], "query": "x"}

    rid = mr.create_review_from_candidates(43, "Series Y", payload, library_id=9)

    row = isolated_db.get_pending_review(rid)
    assert row["library_id"] == 9


def test_create_review_without_a_resolved_library_id_leaves_it_null(isolated_db):
    """Série jamais résolue par get_library_type_for_series : le lien doit
    simplement être omis côté UI plutôt que planter."""
    payload = {"above": [], "below": [], "query": "x"}

    rid = mr.create_review_from_candidates(44, "Series Z", payload)

    row = isolated_db.get_pending_review(rid)
    assert row["library_id"] is None


def test_build_kavita_payload_skips_retranslate_when_flagged(mocker):
    from services.kavita_payload import build_kavita_payload

    spy = mocker.patch(
        "services.kavita_payload.translate_text",
        side_effect=lambda text, *a, **k: f"AGAIN:{text}",
    )
    provider = {
        "summary": "Déjà traduit",
        "_summary_translated": True,
        "year": 2020,
    }
    built = build_kavita_payload(
        provider,
        {"summary": ""},
        ["summary", "year"],
        {"TARGET_LANG": "FR"},
        {},
        True,
        1,
    )
    assert built["metadata"]["summary"] == "Déjà traduit"
    assert built["preview_fields"]["summary"] == "Déjà traduit"
    spy.assert_not_called()


def test_expand_providers_for_super_review_prefers_slots_then_all_usable(monkeypatch):
    from services import enrichment_engine as ee
    from types import SimpleNamespace

    scrapers = [
        SimpleNamespace(id="ANILIST", needs_api_key=False, display_name="AniList"),
        SimpleNamespace(id="MAL", needs_api_key=True, display_name="MAL"),
        SimpleNamespace(id="MANGADEX", needs_api_key=False, display_name="MangaDex"),
        SimpleNamespace(id="HARDCOVER", needs_api_key=True, display_name="Hardcover"),
    ]

    class FakeRegistry:
        def get_by_type(self, lib_type):
            return list(scrapers)

        def get(self, scraper_id):
            return next((s for s in scrapers if s.id == scraper_id), None)

        _scrapers = {s.id: s for s in scrapers}

    monkeypatch.setattr(ee, "ScraperRegistry", FakeRegistry())
    config = {"MAL_API_KEY": "present", "HARDCOVER_API_KEY": ""}
    ordered = ee.expand_providers_for_super_review(
        config, "Manga", preferred_ids=["MANGADEX", "MAL"]
    )
    # Prefer slots first; HARDCOVER skipped (no key); ANILIST appended
    assert ordered[0] == "MANGADEX"
    assert ordered[1] == "MAL"
    assert "ANILIST" in ordered
    assert "HARDCOVER" not in ordered
    assert len(ordered) == 3


def test_resolve_manual_review_flags_super_ignores_forced_id():
    from services.enrichment_engine import resolve_manual_review_flags

    cfg = {"MANUAL_REVIEW_MODE": True, "MANUAL_REVIEW_SUPER": True}
    manual, super_on = resolve_manual_review_flags(cfg, is_forced_id=True)
    assert manual is True
    assert super_on is True

    cfg_classic = {"MANUAL_REVIEW_MODE": True, "MANUAL_REVIEW_SUPER": False}
    manual2, super2 = resolve_manual_review_flags(cfg_classic, is_forced_id=True)
    assert manual2 is False
    assert super2 is False

    manual3, super3 = resolve_manual_review_flags(cfg_classic, is_forced_id=False)
    assert manual3 is True
    assert super3 is False


def test_apply_provider_overrides_super_expands_despite_forced_provider(monkeypatch):
    from services import enrichment_engine as ee
    from types import SimpleNamespace

    scrapers = [
        SimpleNamespace(id="ANILIST", needs_api_key=False, display_name="AniList"),
        SimpleNamespace(id="MAL", needs_api_key=False, display_name="MAL"),
        SimpleNamespace(id="KITSU", needs_api_key=False, display_name="Kitsu"),
    ]

    class FakeRegistry:
        def get_by_type(self, lib_type):
            return list(scrapers)

        def get(self, scraper_id):
            return next((s for s in scrapers if s.id == scraper_id), None)

        _scrapers = {s.id: s for s in scrapers}

    monkeypatch.setattr(ee, "ScraperRegistry", FakeRegistry())
    config = {}
    # Hors Super : exclusif
    assert ee.apply_provider_overrides(
        ["ANILIST", "MAL"],
        config=config,
        provider_family="Manga",
        forced_provider="MAL",
        super_review=False,
    ) == ["MAL"]
    # Super : tous, MAL en tête
    ordered = ee.apply_provider_overrides(
        ["ANILIST"],
        config=config,
        provider_family="Manga",
        forced_provider="MAL",
        super_review=True,
    )
    assert ordered[0] == "MAL"
    assert set(ordered) == {"ANILIST", "MAL", "KITSU"}


def test_merge_candidates_base_then_fusion():
    ordered = [
        ("A", {"title": "Base", "summary": "S", "year": 2020}),
        ("B", {"title": "Other", "genres": ["Action"], "summary": "Ignored"}),
    ]
    merged = metadata_fetcher.merge_candidates(ordered, smart_fusion=True)
    assert merged["_provider_used"] == "A"
    assert merged["title"] == "Base"
    assert merged["summary"] == "S"
    assert merged["genres"] == ["Action"]
    assert "B" in merged.get("_fusion_providers", [])


def test_merge_candidates_no_fusion_keeps_base_only():
    ordered = [
        ("A", {"title": "Base", "summary": "S"}),
        ("B", {"genres": ["Action"]}),
    ]
    merged = metadata_fetcher.merge_candidates(ordered, smart_fusion=False)
    assert merged["title"] == "Base"
    assert "genres" not in merged
    assert not merged.get("_fusion_providers")


def test_fetch_return_candidates_partitions_above_below(monkeypatch):
    monkeypatch.setattr(metadata_fetcher, "LAST_REQUEST_TIMES", {})
    monkeypatch.setattr(metadata_fetcher, "_THROTTLE_LOCKS", {})
    monkeypatch.setattr(metadata_fetcher, "load_config", lambda: {
        "UI_LANG": "fr",
        "SMART_SCORING": True,
        "SMART_COMPLETION": False,
        "MATCH_THRESHOLD_CUSTOM": True,
        "MATCH_ACCEPT_THRESHOLD": 0.70,
    })
    monkeypatch.setattr(metadata_fetcher, "get_match_accept_threshold", lambda config=None: 0.70)

    def high(query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "High", "summary": "H", "_match_score": 0.92}

    def low(query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "Low", "summary": "L", "_match_score": 0.40}

    scrapers = {
        "HIGH": _make_scraper("HIGH", high),
        "LOW": _make_scraper("LOW", low),
    }
    _install_fake_registry(monkeypatch, scrapers)

    payload, used = metadata_fetcher.fetch_metadata(
        query="Q",
        providers_list=["HIGH", "LOW"],
        smart_fusion=False,
        library_type="Manga",
        existing_metadata={},
        smart_scoring=True,
        return_candidates=True,
    )

    assert isinstance(payload, dict)
    assert [c["provider"] for c in payload["above"]] == ["HIGH"]
    assert [c["provider"] for c in payload["below"]] == ["LOW"]
    assert "HIGH" in used and "LOW" in used
    assert "data" in payload["above"][0]


def test_fetch_return_candidates_below_only_when_all_under_threshold(monkeypatch):
    monkeypatch.setattr(metadata_fetcher, "LAST_REQUEST_TIMES", {})
    monkeypatch.setattr(metadata_fetcher, "_THROTTLE_LOCKS", {})
    monkeypatch.setattr(metadata_fetcher, "load_config", lambda: {
        "UI_LANG": "fr",
        "SMART_SCORING": True,
        "SMART_COMPLETION": False,
        "MATCH_THRESHOLD_CUSTOM": True,
        "MATCH_ACCEPT_THRESHOLD": 0.70,
    })
    monkeypatch.setattr(metadata_fetcher, "get_match_accept_threshold", lambda config=None: 0.70)

    def low_a(query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "A", "summary": "a", "_match_score": 0.55}

    def low_b(query, library_type="Manga", is_id=False, existing_metadata=None):
        return {"title": "B", "summary": "b", "_match_score": 0.30}

    scrapers = {
        "A": _make_scraper("A", low_a),
        "B": _make_scraper("B", low_b),
    }
    _install_fake_registry(monkeypatch, scrapers)

    payload, used = metadata_fetcher.fetch_metadata(
        query="Q",
        providers_list=["A", "B"],
        smart_fusion=False,
        library_type="Manga",
        existing_metadata={},
        smart_scoring=True,
        return_candidates=True,
    )

    assert payload["above"] == []
    assert [c["provider"] for c in payload["below"]] == ["A", "B"]
    assert set(used) >= {"A", "B"}


def test_fetch_return_candidates_empty_both_bands(monkeypatch):
    monkeypatch.setattr(metadata_fetcher, "LAST_REQUEST_TIMES", {})
    monkeypatch.setattr(metadata_fetcher, "_THROTTLE_LOCKS", {})
    monkeypatch.setattr(metadata_fetcher, "load_config", lambda: {
        "UI_LANG": "fr",
        "SMART_SCORING": True,
        "SMART_COMPLETION": False,
        "MATCH_THRESHOLD_CUSTOM": True,
        "MATCH_ACCEPT_THRESHOLD": 0.70,
    })
    monkeypatch.setattr(metadata_fetcher, "get_match_accept_threshold", lambda config=None: 0.70)

    def miss(query, library_type="Manga", is_id=False, existing_metadata=None):
        return None

    scrapers = {"MISS": _make_scraper("MISS", miss)}
    _install_fake_registry(monkeypatch, scrapers)

    payload, used = metadata_fetcher.fetch_metadata(
        query="Q",
        providers_list=["MISS"],
        smart_fusion=False,
        library_type="Manga",
        existing_metadata={},
        smart_scoring=True,
        return_candidates=True,
    )

    assert payload["above"] == []
    assert payload["below"] == []
    assert used == []
    assert isinstance(payload, dict)


def test_record_manual_review_telemetry_bumps_fusion_weak_super(isolated_db):
    isolated_db.record_manual_review_telemetry(
        0.77, is_top1=False, field_edits=0, fused=True, weak_pick=True, super_review=True
    )
    life = isolated_db.get_lifetime_stats()
    assert life["manual_reviews"] == 1
    assert life["manual_fusions"] == 1
    assert life["manual_weak_picks"] == 1
    assert life["manual_super_confirms"] == 1

    isolated_db.record_manual_research_telemetry()
    isolated_db.record_manual_purge_telemetry(4)
    life = isolated_db.get_lifetime_stats()
    assert life["manual_researches"] == 1
    assert life["manual_purges"] == 4


def test_get_lifetime_stats_includes_manual_keys_after_telemetry(isolated_db):
    isolated_db.record_manual_review_telemetry(0.88, is_top1=True, field_edits=1)
    # Skip telemetry is inlined in close_pending_review(skip_telemetry=True)
    isolated_db.park_pending_review(
        "skip-telem-keys",
        42,
        "SkipTelem",
        {"above": [], "below": [], "query": "q"},
    )
    isolated_db.close_pending_review("skip-telem-keys", skip_telemetry=True)
    life = isolated_db.get_lifetime_stats()
    for key in (
        "manual_reviews",
        "manual_skips",
        "manual_top1_accepts",
        "manual_score_sum",
        "manual_field_edits",
        "manual_fusions",
        "manual_weak_picks",
        "manual_researches",
        "manual_purges",
        "manual_super_confirms",
    ):
        assert key in life
    assert life["manual_reviews"] == 1
    assert life["manual_skips"] == 1
    assert life["manual_top1_accepts"] == 1
    assert life["manual_score_sum"] == pytest.approx(0.88)
    assert life["manual_field_edits"] == 1
    assert life["manual_fusions"] == 0
    assert life["manual_weak_picks"] == 0
    assert life["manual_researches"] == 0
    assert life["manual_purges"] == 0
    assert life["manual_super_confirms"] == 0

def test_record_manual_review_telemetry_avg_via_score_sum(isolated_db):
    isolated_db.record_manual_review_telemetry(0.90, is_top1=True, field_edits=0)
    isolated_db.record_manual_review_telemetry(0.70, is_top1=False, field_edits=2)
    life = isolated_db.get_lifetime_stats()
    assert life["manual_reviews"] == 2
    assert life["manual_score_sum"] == pytest.approx(1.60)
    assert life["manual_top1_accepts"] == 1
    assert life["manual_field_edits"] == 2
    avg = life["manual_score_sum"] / life["manual_reviews"]
    assert avg == pytest.approx(0.80)

    from services.stats_service import compute_playful_stats
    playful = compute_playful_stats(
        {1: {"status": "PENDING_REVIEW"}},
        {},
        life,
    )
    assert playful["manual_avg_score"] == pytest.approx(0.80)
    assert playful["manual_top1_rate"] == pytest.approx(0.5)
    assert playful["pending_review"] == 1
    assert playful["manual_reviews"] == 2
    assert playful["manual_skips"] == 0
    assert playful["manual_field_edits"] == 2


def test_pending_crud_and_create_review(isolated_db):
    payload = {
        "above": [{"provider": "ANILIST", "score": 0.9, "title": "T", "data": {"summary": "x"}}],
        "below": [],
        "query": "T",
    }
    rid = mr.create_review_from_candidates(42, "One Piece", payload)
    row = isolated_db.get_pending_review(rid)
    assert row is not None
    assert row["series_id"] == 42
    assert row["state"] == "awaiting_pick"
    assert isolated_db.get_all_cached_data()[42]["status"] == "PENDING_REVIEW"
    assert isolated_db.count_pending_reviews() == 1

    listed = isolated_db.list_pending_reviews()
    assert len(listed) == 1
    assert listed[0]["review_id"] == rid


def test_purge_all_pending_reviews(isolated_db):
    payload = {"above": [{"provider": "ANILIST", "score": 0.9, "title": "T", "data": {}}], "below": [], "query": "T"}
    mr.create_review_from_candidates(10, "A", payload)
    mr.create_review_from_candidates(11, "B", payload)
    assert isolated_db.count_pending_reviews() == 2
    assert isolated_db.get_all_cached_data()[10]["status"] == "PENDING_REVIEW"

    result = mr.purge_all_reviews(reset_status="PENDING")
    assert result["deleted"] == 2
    assert sorted(result["series_ids"]) == [10, 11]
    assert isolated_db.count_pending_reviews() == 0
    assert isolated_db.get_all_cached_data()[10]["status"] == "PENDING"
    assert isolated_db.get_all_cached_data()[11]["status"] == "PENDING"
    # purge ≠ skip telemetry
    life = isolated_db.get_lifetime_stats()
    assert int(life.get("manual_skips") or 0) == 0


def test_choice_and_merge_sets_awaiting_confirm(isolated_db):
    payload = {
        "above": [
            {"provider": "A", "score": 0.95, "title": "A", "data": {"summary": "base", "year": 2021}},
            {"provider": "B", "score": 0.80, "title": "B", "data": {"genres": ["Action"]}},
        ],
        "below": [],
        "query": "x",
    }
    rid = mr.create_review_from_candidates(7, "Series", payload)
    master = mr.choice_and_merge(rid, "A", include_providers=["B"], smart_fusion=True)
    assert master["summary"] == "base"
    assert master["genres"] == ["Action"]
    assert master["_provider_used"] == "A"
    row = isolated_db.get_pending_review(rid)
    assert row["state"] == "awaiting_confirm"
    assert row["base_provider"] == "A"
    assert float(row["chosen_score"]) == pytest.approx(0.95)


def test_skip_pending_records_telemetry(isolated_db):
    payload = {"above": [{"provider": "A", "score": 0.5, "title": "t", "data": {"summary": "s"}}], "below": [], "query": "q"}
    rid = mr.create_review_from_candidates(9, "SkipMe", payload)
    assert mr.skip_pending_review(rid) is True
    assert isolated_db.get_pending_review(rid) is None
    assert isolated_db.get_all_cached_data()[9]["status"] == "PENDING"
    life = isolated_db.get_lifetime_stats()
    assert life["manual_skips"] == 1


def test_save_series_override_deletes_pending(isolated_db):
    payload = {"above": [{"provider": "A", "score": 0.9, "title": "t", "data": {"summary": "s"}}], "below": [], "query": "q"}
    rid = mr.create_review_from_candidates(55, "Override", payload)
    assert isolated_db.get_pending_review(rid)
    isolated_db.save_series_override(SeriesOverride(series_id=55, forced_id="123"))
    assert isolated_db.get_pending_review(rid) is None
    assert isolated_db.count_pending_reviews() == 0


def test_apply_manual_review_records_top1_and_edits(isolated_db, mocker):
    payload = {
        "above": [
            {"provider": "TOP", "score": 0.91, "title": "Top", "data": {"summary": "orig", "year": 2020, "title": "Top"}},
            {"provider": "ALT", "score": 0.75, "title": "Alt", "data": {"summary": "alt", "year": 2019}},
        ],
        "below": [],
        "query": "q",
    }
    rid = mr.create_review_from_candidates(100, "ApplyMe", payload)

    mocker.patch.object(enrichment_engine, "load_config", return_value={
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "k",
        "UI_LANG": "fr",
        "SMART_COMPLETION": False,
        "TARGET_LANG": "FR",
        "AUTO_COVER": False,
        "AUTO_READING_DIR": False,
    })
    mocker.patch("services.kavita_payload.translate_text", side_effect=lambda text, *a, **k: text)
    mocker.patch("services.kavita_payload._broadcast_enrichment_stats", lambda *a, **k: None)
    mocker.patch.object(enrichment_engine, "_broadcast_enrichment_stats", lambda *a, **k: None)

    from kavita_api import KavitaAPI
    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    mocker.patch.object(KavitaAPI, "get_series_metadata", return_value={"seriesId": 100, "summary": ""})
    mocker.patch.object(KavitaAPI, "update_series_metadata", return_value=(True, "ok", True))
    mocker.patch.object(KavitaAPI, "update_series_general", return_value=(True, "ok", True))
    mocker.patch.object(KavitaAPI, "update_series_external_ids", return_value=True)
    mocker.patch.object(KavitaAPI, "upload_series_cover", return_value=(True, "ok"))

    ok, msg, detail = enrichment_engine.apply_manual_review(
        rid,
        base_provider="TOP",
        include_providers=None,
        edited_preview={"summary": "edited summary", "year": 2021},
        field_edits=2,
    )
    assert ok is True, msg
    assert detail["is_top1"] is True
    life = isolated_db.get_lifetime_stats()
    assert life["manual_reviews"] == 1
    assert life["manual_top1_accepts"] == 1
    assert life["manual_field_edits"] == 2
    assert isolated_db.get_pending_review(rid) is None
    assert isolated_db.get_all_cached_data()[100]["status"] == "COMPLETED"


def test_apply_manual_review_non_top1(isolated_db, mocker):
    payload = {
        "above": [
            {"provider": "TOP", "score": 0.91, "title": "Top", "data": {"summary": "top", "year": 2020}},
            {"provider": "ALT", "score": 0.75, "title": "Alt", "data": {"summary": "alt", "year": 2019}},
        ],
        "below": [],
        "query": "q",
    }
    rid = mr.create_review_from_candidates(101, "AltPick", payload)

    mocker.patch.object(enrichment_engine, "load_config", return_value={
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "k",
        "UI_LANG": "fr",
        "SMART_COMPLETION": False,
        "TARGET_LANG": "FR",
        "AUTO_COVER": False,
        "AUTO_READING_DIR": False,
    })
    mocker.patch("services.kavita_payload.translate_text", side_effect=lambda text, *a, **k: text)
    mocker.patch("services.kavita_payload._broadcast_enrichment_stats", lambda *a, **k: None)
    mocker.patch.object(enrichment_engine, "_broadcast_enrichment_stats", lambda *a, **k: None)

    from kavita_api import KavitaAPI
    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    mocker.patch.object(KavitaAPI, "get_series_metadata", return_value={"seriesId": 101, "summary": ""})
    mocker.patch.object(KavitaAPI, "update_series_metadata", return_value=(True, "ok", True))
    mocker.patch.object(KavitaAPI, "update_series_general", return_value=(True, "ok", True))
    mocker.patch.object(KavitaAPI, "update_series_external_ids", return_value=True)

    ok, msg, detail = enrichment_engine.apply_manual_review(
        rid, base_provider="ALT", field_edits=0
    )
    assert ok is True, msg
    assert detail["is_top1"] is False
    life = isolated_db.get_lifetime_stats()
    assert life["manual_reviews"] == 1
    assert life["manual_top1_accepts"] == 0


def test_preview_manual_fusion_independent_of_smart_completion(isolated_db, mocker):
    """Cases Source cochées ⇒ fusion même si SMART_COMPLETION=False."""
    payload = {
        "above": [
            {
                "provider": "TOP",
                "score": 0.91,
                "title": "Top",
                "data": {"summary": "base only", "title": "Top"},
            },
            {
                "provider": "ALT",
                "score": 0.75,
                "title": "Alt",
                "data": {"genres": ["Action"], "publisher": "Kadokawa"},
            },
        ],
        "below": [],
        "query": "q",
    }
    rid = mr.create_review_from_candidates(200, "FusionPreview", payload)

    mocker.patch.object(enrichment_engine, "load_config", return_value={
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "k",
        "UI_LANG": "fr",
        "SMART_COMPLETION": False,
        "TARGET_LANG": "FR",
        "AUTO_COVER": False,
        "AUTO_READING_DIR": False,
    })
    mocker.patch("services.kavita_payload.translate_text", side_effect=lambda text, *a, **k: text)

    from kavita_api import KavitaAPI
    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    mocker.patch.object(KavitaAPI, "get_series_metadata", return_value={"seriesId": 200, "summary": ""})

    ok, preview, _built = enrichment_engine.preview_manual_review(
        rid, "TOP", include_providers=["ALT"]
    )
    assert ok is True
    assert "base only" in (preview.get("summary") or "")
    assert "Action" in (preview.get("genres") or [])
    assert preview.get("publisher") == "Kadokawa"
    assert preview.get("_provider_used") == "TOP"
    assert "ALT" in (preview.get("_fusion_providers") or [])


def test_preview_manual_no_includes_ignores_other_candidates(isolated_db, mocker):
    """Sans case Source, master seul — même si SMART_COMPLETION=True en config."""
    payload = {
        "above": [
            {
                "provider": "TOP",
                "score": 0.91,
                "title": "Top",
                "data": {"summary": "base only", "title": "Top"},
            },
            {
                "provider": "ALT",
                "score": 0.75,
                "title": "Alt",
                "data": {"genres": ["Action"], "publisher": "Kadokawa"},
            },
        ],
        "below": [],
        "query": "q",
    }
    rid = mr.create_review_from_candidates(201, "NoFusion", payload)

    mocker.patch.object(enrichment_engine, "load_config", return_value={
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "k",
        "UI_LANG": "fr",
        "SMART_COMPLETION": True,
        "TARGET_LANG": "FR",
        "AUTO_COVER": False,
        "AUTO_READING_DIR": False,
    })
    mocker.patch("services.kavita_payload.translate_text", side_effect=lambda text, *a, **k: text)

    from kavita_api import KavitaAPI
    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    mocker.patch.object(KavitaAPI, "get_series_metadata", return_value={"seriesId": 201, "summary": ""})

    ok, preview, _built = enrichment_engine.preview_manual_review(
        rid, "TOP", include_providers=[]
    )
    assert ok is True
    genres = preview.get("genres") or []
    assert "Action" not in genres
    assert not (preview.get("publisher") or "")
    assert preview.get("_provider_used") == "TOP"
    assert preview.get("_fusion_providers") == []


def test_apply_manual_fusion_fills_holes_with_smart_completion_off(isolated_db, mocker):
    payload = {
        "above": [
            {
                "provider": "TOP",
                "score": 0.91,
                "title": "Top",
                "data": {"summary": "base", "title": "Top"},
            },
            {
                "provider": "ALT",
                "score": 0.70,
                "title": "Alt",
                "data": {"genres": ["Adventure"], "year": 2011},
            },
        ],
        "below": [],
        "query": "q",
    }
    rid = mr.create_review_from_candidates(202, "ApplyFusion", payload)

    mocker.patch.object(enrichment_engine, "load_config", return_value={
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "k",
        "UI_LANG": "fr",
        "SMART_COMPLETION": False,
        "TARGET_LANG": "FR",
        "AUTO_COVER": False,
        "AUTO_READING_DIR": False,
    })
    mocker.patch("services.kavita_payload.translate_text", side_effect=lambda text, *a, **k: text)
    mocker.patch("services.kavita_payload._broadcast_enrichment_stats", lambda *a, **k: None)
    mocker.patch.object(enrichment_engine, "_broadcast_enrichment_stats", lambda *a, **k: None)

    from kavita_api import KavitaAPI
    captured = {}

    def _capture_meta(meta):
        captured["meta"] = meta
        return True, "ok", True

    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    mocker.patch.object(KavitaAPI, "get_series_metadata", return_value={"seriesId": 202, "summary": ""})
    mocker.patch.object(KavitaAPI, "update_series_metadata", side_effect=_capture_meta)
    mocker.patch.object(KavitaAPI, "update_series_general", return_value=(True, "ok", True))
    mocker.patch.object(KavitaAPI, "update_series_external_ids", return_value=True)

    ok, msg, detail = enrichment_engine.apply_manual_review(
        rid,
        base_provider="TOP",
        include_providers=["ALT"],
        field_edits=0,
    )
    assert ok is True, msg
    assert "ALT" in (detail.get("used_providers") or [])
    meta = captured.get("meta") or {}
    genre_titles = [
        (g.get("title") if isinstance(g, dict) else str(g))
        for g in (meta.get("genres") or [])
    ]
    assert any("Adventure" in str(t) for t in genre_titles)
    assert meta.get("releaseYear") == 2011


def test_build_kavita_payload_no_external_ids_side_effect(mocker):
    from services.kavita_payload import build_kavita_payload

    mocker.patch("services.kavita_payload.translate_text", side_effect=lambda text, *a, **k: text)
    provider = {
        "summary": "Hello",
        "year": 2022,
        "anilist_id": 99,
        "mal_id": 11,
        "cover_url": "http://cover",
        MATCH_SCORE_KEY: 0.9,
        "_provider_used": "X",
    }
    meta = {"summary": "", "webLinks": ""}
    built = build_kavita_payload(
        provider,
        meta,
        ["summary", "year", "weblinks", "cover"],
        {"TARGET_LANG": "FR", "AUTO_READING_DIR": False},
        {},
        True,
        1,
    )
    assert built["external_ids"]["anilist"] == 99
    assert built["external_ids"]["mal"] == 11
    assert "anilist.co/manga/99" in (built["metadata"].get("webLinks") or "")
    assert built["preview_fields"]["year"] == 2022
    assert MATCH_SCORE_KEY not in built["_provider_data"]


def test_research_manual_review_replaces_candidates(isolated_db, mocker):
    payload = {
        "above": [
            {
                "provider": "OLD",
                "score": 0.7,
                "title": "Old Hit",
                "summary": "old",
                "data": {"summary": "old", "title": "Old Hit"},
            }
        ],
        "below": [],
        "query": "Ghost in the shell - La saga",
    }
    rid = mr.create_review_from_candidates(77, "Ghost in the shell - La saga", payload)
    assert isolated_db.get_pending_review(rid)

    new_payload = {
        "above": [
            {
                "provider": "MAL",
                "score": 0.95,
                "title": "Ghost in the Shell",
                "summary": "cyberpunk",
                "data": {"summary": "cyberpunk", "title": "Ghost in the Shell"},
            }
        ],
        "below": [],
        "query": "Ghost in the Shell",
    }
    mocker.patch.object(
        enrichment_engine,
        "_scrape_manual_candidates",
        return_value=(new_payload, ["MAL"]),
    )
    mocker.patch.object(enrichment_engine, "load_config", return_value={
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "k",
        "UI_LANG": "fr",
        "TARGET_LANG": "FR",
        "MANUAL_REVIEW_SUPER": False,
    })
    from kavita_api import KavitaAPI
    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)

    ok, msg, detail = enrichment_engine.research_manual_review(rid, "Ghost in the Shell")
    assert ok is True, msg
    assert detail["query"] == "Ghost in the Shell"
    assert detail["above"][0]["provider"] == "MAL"
    assert detail["above"][0]["title"] == "Ghost in the Shell"

    row = isolated_db.get_pending_review(rid)
    assert row is not None
    assert row["state"] == "awaiting_pick"
    cands = __import__("json").loads(row["candidates_json"])
    assert cands["above"][0]["provider"] == "MAL"
    assert cands["query"] == "Ghost in the Shell"

    cached = isolated_db.get_all_cached_data()[77]
    assert cached["alternative_title"] == "Ghost in the Shell"
    assert cached["status"] == "PENDING_REVIEW"
    assert isolated_db.count_pending_reviews() == 1


def test_save_series_override_can_keep_pending(isolated_db):
    payload = {"above": [{"provider": "A", "score": 0.9, "title": "t", "data": {"summary": "s"}}], "below": [], "query": "q"}
    rid = mr.create_review_from_candidates(88, "KeepMe", payload)
    isolated_db.save_series_override(
        SeriesOverride(series_id=88, alternative_title="New Title"),
        purge_pending=False,
        status="PENDING_REVIEW",
    )
    assert isolated_db.get_pending_review(rid) is not None
    assert isolated_db.get_all_cached_data()[88]["alternative_title"] == "New Title"
    assert isolated_db.get_all_cached_data()[88]["status"] == "PENDING_REVIEW"


def test_park_idempotent_replaces_same_series(isolated_db):
    """Une seule pending_reviews par series_id (UNIQUE + remplace)."""
    payload = {
        "above": [{"provider": "A", "score": 0.9, "title": "T1", "data": {"summary": "a"}}],
        "below": [],
        "query": "T1",
    }
    rid1 = mr.create_review_from_candidates(33, "Dup", payload)
    payload2 = {
        "above": [{"provider": "B", "score": 0.8, "title": "T2", "data": {"summary": "b"}}],
        "below": [],
        "query": "T2",
    }
    rid2 = mr.create_review_from_candidates(33, "Dup", payload2)
    assert rid1 != rid2
    assert isolated_db.count_pending_reviews() == 1
    assert isolated_db.get_pending_review(rid1) is None
    row = isolated_db.get_pending_review(rid2)
    assert row is not None
    assert row["series_id"] == 33
    cands = __import__("json").loads(row["candidates_json"])
    assert cands["above"][0]["provider"] == "B"
    assert isolated_db.get_all_cached_data()[33]["status"] == "PENDING_REVIEW"


def test_clean_orphaned_cache_purges_pending_reviews(isolated_db):
    payload = {"above": [{"provider": "A", "score": 0.9, "title": "t", "data": {}}], "below": [], "query": "q"}
    mr.create_review_from_candidates(501, "Gone", payload)
    mr.create_review_from_candidates(502, "Keep", payload)
    assert isolated_db.count_pending_reviews() == 2
    n = isolated_db.clean_orphaned_cache({502})
    assert n >= 1
    assert isolated_db.count_pending_reviews() == 1
    assert isolated_db.list_pending_reviews()[0]["series_id"] == 502


def test_enrich_series_early_skip_preserves_pending_review(isolated_db, mocker):
    """Résumé Kavita présent + force_update=False ne clobber pas PENDING_REVIEW."""
    payload = {
        "above": [{"provider": "A", "score": 0.9, "title": "T", "data": {"summary": "s"}}],
        "below": [],
        "query": "T",
    }
    rid = mr.create_review_from_candidates(777, "Parked", payload)
    assert isolated_db.get_all_cached_data()[777]["status"] == "PENDING_REVIEW"

    mocker.patch.object(enrichment_engine, "load_config", return_value={
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "k",
        "UI_LANG": "fr",
        "MANUAL_REVIEW_MODE": True,
    })
    from kavita_api import KavitaAPI
    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    mocker.patch.object(
        KavitaAPI, "get_series_metadata", return_value={"seriesId": 777, "summary": "already there"}
    )

    ok, msg, used = enrichment_engine.enrich_series(777, "Parked", force_update=False)
    assert ok is True
    assert msg == "PENDING_REVIEW"
    assert isolated_db.get_pending_review(rid) is not None
    assert isolated_db.get_all_cached_data()[777]["status"] == "PENDING_REVIEW"


def test_enrich_series_early_skip_purges_orphan_review(isolated_db, mocker):
    """COMPLETED path purge toute review orpheline quand résumé déjà présent."""
    payload = {
        "above": [{"provider": "A", "score": 0.9, "title": "T", "data": {"summary": "s"}}],
        "below": [],
        "query": "T",
    }
    rid = mr.create_review_from_candidates(778, "Orphan", payload)
    # Simule un statut déjà désynchronisé (COMPLETED + review encore là)
    isolated_db.update_status(778, "COMPLETED")

    mocker.patch.object(enrichment_engine, "load_config", return_value={
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "k",
        "UI_LANG": "fr",
        "MANUAL_REVIEW_MODE": False,
    })
    from kavita_api import KavitaAPI
    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    mocker.patch.object(
        KavitaAPI, "get_series_metadata", return_value={"seriesId": 778, "summary": "already"}
    )

    ok, msg, used = enrichment_engine.enrich_series(778, "Orphan", force_update=False)
    assert ok is True
    assert msg == "Déjà à jour."
    assert isolated_db.get_pending_review(rid) is None
    assert isolated_db.count_pending_reviews() == 0


def test_create_confirm_from_auto_parks_awaiting_confirm(isolated_db):
    preview = {
        "title": "One Piece",
        "summary": "Pirates",
        "year": 1997,
        "genres": "Adventure",
        "tags": "",
        "publisher": "Shueisha",
        "staff": "Oda",
        "cover_url": "",
        "localized_name": "",
        "status": "",
        "age_rating": "",
        "format": "",
    }
    provider_data = {
        "title": "One Piece",
        "summary": "Pirates",
        "year": 1997,
        "genres": ["Adventure"],
        "publisher": "Shueisha",
        "staff": [{"name": "Oda", "role": "Story"}],
    }
    rid = mr.create_confirm_from_auto(
        9001,
        "One Piece",
        provider_data,
        preview,
        actual_provider="MAL",
        fusion_providers=["AniList"],
        chosen_score=0.88,
        query="One Piece",
        force_update=False,
    )
    row = isolated_db.get_pending_review(rid)
    assert row is not None
    assert row["state"] == "awaiting_confirm"
    assert row["base_provider"] == "MAL"
    assert isolated_db.get_all_cached_data()[9001]["status"] == "PENDING_REVIEW"
    cands = __import__("json").loads(row["candidates_json"])
    assert cands["flow"] == "auto_confirm"
    assert cands["force_update"] is False
    assert len(cands["above"]) == 1
    assert cands["above"][0]["provider"] == "MAL"
    prev = __import__("json").loads(row["preview_json"])
    assert prev["title"] == "One Piece"
    assert prev["_flow"] == "auto_confirm"


def test_purge_auto_confirm_leaves_manual_reviews(isolated_db):
    manual_payload = {
        "above": [{"provider": "A", "score": 0.9, "title": "M", "data": {"summary": "s"}}],
        "below": [],
        "query": "M",
    }
    rid_manual = mr.create_review_from_candidates(10, "Manual", manual_payload)
    rid_auto = mr.create_confirm_from_auto(
        11,
        "Auto",
        {"title": "Auto", "summary": "s"},
        {"title": "Auto", "summary": "s"},
        actual_provider="MAL",
        force_update=True,
    )
    assert isolated_db.count_pending_reviews() == 2
    result = mr.purge_auto_confirm_reviews(reset_status="PENDING")
    assert result["deleted"] == 1
    assert isolated_db.get_pending_review(rid_auto) is None
    assert isolated_db.get_pending_review(rid_manual) is not None
    assert isolated_db.get_all_cached_data()[11]["status"] == "PENDING"
    assert isolated_db.get_all_cached_data()[10]["status"] == "PENDING_REVIEW"


def test_apply_auto_confirm_skips_manual_telemetry(isolated_db, mocker):
    preview = {"title": "T", "summary": "S", "year": "", "genres": "", "tags": "",
               "publisher": "", "staff": "", "cover_url": "", "localized_name": "",
               "status": "", "age_rating": "", "format": ""}
    rid = mr.create_confirm_from_auto(
        9200,
        "ApplyAuto",
        {"title": "T", "summary": "S"},
        preview,
        actual_provider="MAL",
        chosen_score=0.8,
        force_update=True,
    )
    mocker.patch.object(enrichment_engine, "load_config", return_value={
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "k",
        "UI_LANG": "fr",
        "AUTO_COVER": False,
        "AUTO_READING_DIR": False,
    })
    from kavita_api import KavitaAPI
    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    mocker.patch.object(KavitaAPI, "get_series_metadata", return_value={"seriesId": 9200})
    mocker.patch(
        "services.enrichment_engine.apply_kavita_payload",
        return_value=(True, "ok", ["MAL"]),
    )
    tel = mocker.patch("services.enrichment_engine.record_manual_review_telemetry")

    ok, msg, detail = enrichment_engine.apply_manual_review(
        rid, "MAL", edited_preview={"summary": "Edited"}, field_edits=1
    )
    assert ok is True
    assert detail.get("flow") == "auto_confirm"
    tel.assert_not_called()
    assert isolated_db.get_pending_review(rid) is None


def test_apply_manual_review_force_cover_upload_without_auto_cover(isolated_db, mocker):
    """cover_picked / cover_url édité → upload même si AUTO_COVER est off."""
    payload = {
        "above": [
            {
                "provider": "TOP",
                "score": 0.9,
                "title": "CoverMe",
                "data": {
                    "summary": "s",
                    "title": "CoverMe",
                    "cover_url": "https://cdn.example/old.jpg",
                },
            },
        ],
        "below": [],
        "query": "CoverMe",
    }
    rid = mr.create_review_from_candidates(9300, "CoverMe", payload)

    mocker.patch.object(enrichment_engine, "load_config", return_value={
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "k",
        "UI_LANG": "fr",
        "SMART_COMPLETION": False,
        "TARGET_LANG": "FR",
        "AUTO_COVER": False,
        "AUTO_READING_DIR": False,
    })
    mocker.patch("services.kavita_payload.translate_text", side_effect=lambda text, *a, **k: text)
    mocker.patch("services.kavita_payload._broadcast_enrichment_stats", lambda *a, **k: None)
    mocker.patch.object(enrichment_engine, "_broadcast_enrichment_stats", lambda *a, **k: None)

    from kavita_api import KavitaAPI
    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    mocker.patch.object(KavitaAPI, "get_series_metadata", return_value={"seriesId": 9300, "summary": ""})
    mocker.patch.object(KavitaAPI, "update_series_metadata", return_value=(True, "ok", True))
    mocker.patch.object(KavitaAPI, "update_series_general", return_value=(True, "ok", True))
    mocker.patch.object(KavitaAPI, "update_series_external_ids", return_value=True)
    upload = mocker.patch.object(KavitaAPI, "upload_series_cover", return_value=(True, "ok"))

    ok, msg, detail = enrichment_engine.apply_manual_review(
        rid,
        base_provider="TOP",
        edited_preview={"cover_url": "https://cdn.example/picked.jpg"},
        field_edits=1,
        force_cover_upload=True,
    )
    assert ok is True, msg
    upload.assert_called_once()
    assert upload.call_args[0][1] == "https://cdn.example/picked.jpg"
    assert isolated_db.get_pending_review(rid) is None


def test_apply_manual_review_no_cover_upload_without_auto_or_pick(isolated_db, mocker):
    """Sans AUTO_COVER ni cover_picked : pas d'upload même si le provider a une cover."""
    payload = {
        "above": [
            {
                "provider": "TOP",
                "score": 0.9,
                "title": "NoUpload",
                "data": {
                    "summary": "s",
                    "title": "NoUpload",
                    "cover_url": "https://cdn.example/prov.jpg",
                },
            },
        ],
        "below": [],
        "query": "NoUpload",
    }
    rid = mr.create_review_from_candidates(9301, "NoUpload", payload)

    mocker.patch.object(enrichment_engine, "load_config", return_value={
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "k",
        "UI_LANG": "fr",
        "SMART_COMPLETION": False,
        "TARGET_LANG": "FR",
        "AUTO_COVER": False,
        "AUTO_READING_DIR": False,
    })
    mocker.patch("services.kavita_payload.translate_text", side_effect=lambda text, *a, **k: text)
    mocker.patch("services.kavita_payload._broadcast_enrichment_stats", lambda *a, **k: None)
    mocker.patch.object(enrichment_engine, "_broadcast_enrichment_stats", lambda *a, **k: None)

    from kavita_api import KavitaAPI
    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    mocker.patch.object(KavitaAPI, "get_series_metadata", return_value={"seriesId": 9301, "summary": ""})
    mocker.patch.object(KavitaAPI, "update_series_metadata", return_value=(True, "ok", True))
    mocker.patch.object(KavitaAPI, "update_series_general", return_value=(True, "ok", True))
    mocker.patch.object(KavitaAPI, "update_series_external_ids", return_value=True)
    upload = mocker.patch.object(KavitaAPI, "upload_series_cover", return_value=(True, "ok"))

    ok, msg, detail = enrichment_engine.apply_manual_review(
        rid,
        base_provider="TOP",
        edited_preview=None,
        field_edits=0,
        force_cover_upload=False,
    )
    assert ok is True, msg
    upload.assert_not_called()
