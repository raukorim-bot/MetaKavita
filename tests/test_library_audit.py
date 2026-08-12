"""Library hygiene — volume report, duplicates, ISBN regression, CSV."""

from __future__ import annotations

from kavita_api import KavitaAPI
from services.library_audit import (
    build_volume_report,
    cluster_duplicate_series,
    duplicates_to_csv,
    missing_volume_numbers,
    series_has_external_id,
    volume_report_to_csv,
)
from services.library_audit.volume_report import compute_volume_gaps


def test_quick_scan_reuses_a_known_expected_but_retries_the_unknown(monkeypatch):
    """L'analyse rapide existe pour éviter les appels providers, pas pour figer
    l'inventaire : une série dont le catalogue n'a rien donné (`N/?`) doit être
    retentée, sinon aucune analyse rapide ne pourra jamais la sortir de
    l'inconnu, et une série dont le compte local a bougé doit l'être aussi —
    de nouveaux tomes chez soi, c'est souvent de nouveaux tomes parus."""
    from services.library_audit import hygiene_scan as hs

    cache = {
        1: {"catalog": {"status": "ok", "expected": 12}, "stats": {"primary_count": 12}},
        2: {"catalog": {"status": "unknown"}, "stats": {"primary_count": 3}},
        3: {"catalog": {"status": "ok", "expected": 12}, "stats": {}},
    }
    monkeypatch.setattr(hs, "get_volume_report_cache", lambda sid: cache.get(sid))

    assert hs._reusable_catalog(1) == ({"status": "ok", "expected": 12}, 12)
    assert hs._reusable_catalog(2) is None, "catalogue sans attendu : on retente"
    assert hs._reusable_catalog(3) is None, "cache d'avant C66 : compte local inconnu"
    assert hs._reusable_catalog(99) is None


def test_health_bar_does_not_call_an_overshoot_series_incomplete():
    """`overshoot` = plus d'unités que l'attendu : il ne manque rien, c'est le
    catalogue qui est en retard. Le compter parmi les incomplètes faisait mentir
    le libellé du segment."""
    from services.library_audit.hygiene_scan import summarize_states

    buckets = summarize_states(
        {"complete": 4, "uptodate": 2, "neutral": 1, "overshoot": 3,
         "near": 5, "partial": 2, "poor": 1, "unknown": 7}
    )
    assert buckets == {"healthy": 10, "incomplete": 8, "unknown_expected": 7}


def test_compute_volume_gaps_basic():
    assert compute_volume_gaps([1, 2, 4, 5]) == [3]
    assert compute_volume_gaps([1]) == []
    assert compute_volume_gaps([100000, 1, 2]) == []


def test_missing_volume_numbers_catalog():
    assert missing_volume_numbers([1, 2], 5) == [3, 4, 5]
    assert missing_volume_numbers([1, 2, 3], 3) == []


def test_volume_report_oneshot_no_gaps():
    volumes = [
        {
            "id": 1,
            "name": "One-Shot",
            "number": 100000,
            "chapters": [{"id": 10, "title": "OS", "number": 1, "summary": "hi"}],
        }
    ]
    report = build_volume_report(42, volumes, series_name="Cool One-Shot")
    assert report["is_oneshot"] is True
    assert report["structure"] == "oneshot"
    assert report["gaps"] == []
    assert report["badge"] == "OS"


def test_volume_report_multi_gaps_and_meta():
    volumes = [
        {
            "id": 1,
            "name": "Vol 1",
            "number": 1,
            "isbn": "9780000000001",
            "chapters": [{"id": 1, "number": 1, "summary": "a"}],
        },
        {
            "id": 2,
            "name": "Vol 2",
            "number": 2,
            "chapters": [{"id": 2, "number": 1}],  # no summary
        },
        {
            "id": 4,
            "name": "Vol 4",
            "number": 4,
            "chapters": [{"id": 4, "number": 1, "summary": "d"}],
        },
    ]
    report = build_volume_report(7, volumes, series_name="Multi")
    assert report["structure"] == "multi_volume"
    assert report["gaps"] == [3]
    assert report["missing_volumes"] == []  # no scraped expected
    assert report["stats"]["missing_summary"] >= 1
    assert report["badge"] == "3/?"  # unknown catalog — never summary/total


def test_volume_report_1_of_20_not_oneshot():
    volumes = [
        {"id": 1, "number": 1, "chapters": [{"id": 1, "number": 1, "summary": "a"}]},
    ]
    report = build_volume_report(
        9,
        volumes,
        series_name="Incomplete OS Hint One-Shot",
        catalog={"expected": 20, "provider": "ANILIST", "status": "ok"},
    )
    assert report["is_oneshot"] is False
    assert report["badge"].startswith("1/20")
    assert report["missing_volumes"] == list(range(2, 21))


def test_volume_report_expected_1_is_oneshot():
    volumes = [
        {"id": 1, "number": 1, "chapters": [{"id": 1, "number": 1, "summary": "a"}]},
    ]
    report = build_volume_report(
        10,
        volumes,
        series_name="Solo",
        catalog={"expected": 1, "provider": "ANILIST", "status": "ok"},
    )
    assert report["is_oneshot"] is True
    assert report["badge"] == "OS"
    assert report["missing_volumes"] == []


def test_volume_report_unknown_keeps_local_gaps():
    volumes = [
        {"id": 1, "number": 1, "chapters": [{"id": 1, "number": 1, "summary": "a"}]},
        {"id": 3, "number": 3, "chapters": [{"id": 3, "number": 1, "summary": "c"}]},
    ]
    report = build_volume_report(
        11,
        volumes,
        series_name="Multi",
        catalog={"status": "unknown", "provider": "ANILIST"},
    )
    assert report["gaps"] == [2]
    assert report["missing_volumes"] == []
    assert "/" not in report["badge"] or report["badge"].endswith("/?")


def test_volume_report_with_catalog_expected():
    volumes = [
        {"id": 1, "number": 1, "chapters": [{"id": 1, "number": 1, "summary": "a"}]},
        {"id": 2, "number": 2, "chapters": [{"id": 2, "number": 1, "summary": "b"}]},
    ]
    report = build_volume_report(
        8,
        volumes,
        series_name="Multi",
        catalog={"expected": 5, "provider": "ANILIST", "unit": "volumes"},
    )
    assert report["stats"]["kavita_count"] == 2
    assert report["catalog"]["expected"] == 5
    assert report["catalog"]["status"] == "ok"
    assert report["missing_volumes"] == [3, 4, 5]
    assert report["badge"].startswith("2/5")


def test_volume_report_csv_headers():
    report = build_volume_report(
        1,
        [{"id": 1, "number": 1, "chapters": [{"id": 1, "number": 1, "summary": "x"}]}],
        series_name="S",
        catalog={"expected": 3, "provider": "ANILIST", "status": "ok"},
    )
    csv = volume_report_to_csv(report)
    header = csv.splitlines()[0]
    assert "catalog_expected" in header
    assert "catalog_status" in header
    assert "missing_volumes" in header


def test_exports_state_the_unit_for_a_chapter_series():
    """Les exports datent d'avant l'inventaire en chapitres : une série comptée en
    chapitres sortait avec `kavita_count` à 0 et un attendu vide, sans dire nulle
    part que les numéros manquants étaient des chapitres."""
    from services.library_audit.export_csv import volume_report_to_txt

    volumes = [
        {
            "id": 1,
            "number": -100000,
            "chapters": [{"id": i, "number": i} for i in range(1, 9)],
        }
    ]
    report = build_volume_report(
        3, volumes, series_name="7th garden",
        catalog={"status": "ok", "expected": 8, "expected_chapters": 32,
                 "provider": "MAL", "publication_status": "RELEASING"},
    )
    rows = volume_report_to_csv(report).splitlines()
    header = rows[0].split(",")
    assert {"unit", "primary_count", "primary_expected", "primary_missing"} <= set(header)
    data = rows[1].split(",")
    assert data[header.index("unit")] == "chapters"
    assert data[header.index("primary_count")] == "8"
    assert data[header.index("primary_expected")] == "32"

    txt = volume_report_to_txt(report)
    assert "Possédés: 8 chapters" in txt
    assert "Manquants (chapters):" in txt


def test_duplicates_same_anilist_and_title():
    series = [
        {"id": 1, "name": "Attack on Titan", "libraryId": 5, "aniListId": 53390},
        {"id": 2, "name": "Attack on Titan", "libraryId": 5, "aniListId": 53390},
        {"id": 3, "name": "Totally Different", "libraryId": 5, "aniListId": 999},
    ]
    groups = cluster_duplicate_series(series, library_id=5)
    assert len(groups) == 1
    assert set(groups[0]["series_ids"]) == {1, 2}
    csv = duplicates_to_csv(groups, library_id=5)
    assert "group_id" in csv.splitlines()[0]


def test_series_has_external_id():
    assert series_has_external_id({"aniListId": 12}) is True
    assert series_has_external_id({"webLinks": "https://myanimelist.net/manga/1"}) is True
    assert series_has_external_id({"metadata": {"malId": 42}}) is True
    assert series_has_external_id({"name": "x"}) is False


def test_duplicate_cache_empty_still_hits(isolated_db):
    from db_manager import (
        get_duplicate_groups_cache,
        has_duplicate_groups_cache,
        save_duplicate_groups_cache,
    )

    assert has_duplicate_groups_cache(3) is False
    save_duplicate_groups_cache(3, [])
    assert has_duplicate_groups_cache(3) is True
    assert get_duplicate_groups_cache(3) == []


def test_get_series_isbn_uses_volumes(monkeypatch):
    """Caractérisation: get_series_isbn still returns first ISBN after extract."""
    api = KavitaAPI("http://example.invalid", "key")
    api.token = "t"
    vols = [
        {"isbn": "", "chapters": [{"isbn": "978-1-234-56789-7"}]},
        {"isbn": "9789999999999", "chapters": []},
    ]
    monkeypatch.setattr(api, "get_series_volumes", lambda _sid: vols)
    assert api.get_series_isbn(1) == "9781234567897"


def test_volume_report_api(isolated_db, monkeypatch):
    from flask import Flask

    from routes.library_audit import library_audit_bp

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(library_audit_bp)

    class FakeAPI:
        def __init__(self, *a, **k):
            pass

        def get_series(self, sid):
            return {"id": sid, "name": "Test", "libraryId": 1, "libraryType": "Manga"}

        def get_library_type_for_series(self, sid):
            return "Manga"

        def get_series_metadata(self, sid):
            return {}

        def get_series_volumes(self, sid):
            return [
                {
                    "id": 1,
                    "number": 1,
                    "chapters": [{"id": 1, "number": 1, "summary": "ok"}],
                },
                {
                    "id": 3,
                    "number": 3,
                    "chapters": [{"id": 3, "number": 1}],
                },
            ]

    monkeypatch.setattr("routes.library_audit.KavitaAPI", FakeAPI)
    monkeypatch.setattr(
        "routes.library_audit.load_config",
        lambda: {"UI_LANG": "en", "KAVITA_URL": "http://x", "KAVITA_API_KEY": "k"},
    )
    monkeypatch.setattr("routes.library_audit.get_kavita_ui_url", lambda c: "http://ui")
    monkeypatch.setattr(
        "routes.library_audit.resolve_catalog_expected",
        lambda *a, **k: {
            "expected": 4,
            "provider": "ANILIST",
            "unit": "volumes",
            "status": "ok",
        },
    )

    client = app.test_client()
    res = client.get("/api/series/9/volume-report?refresh=1")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["gaps"] == [2]
    assert data["stats"]["kavita_count"] == 2
    assert data["catalog"]["expected"] == 4
    assert data["missing_volumes"] == [2, 4]


def test_duplicates_api_cache_and_refresh_rejected(isolated_db, monkeypatch):
    from flask import Flask

    from db_manager import save_duplicate_groups_cache, set_series_external_id_flags
    from routes.library_audit import library_audit_bp

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(library_audit_bp)

    monkeypatch.setattr(
        "routes.library_audit.load_config",
        lambda: {"UI_LANG": "en", "KAVITA_URL": "http://x", "KAVITA_API_KEY": "k"},
    )

    groups = [
        {
            "group_id": "dup-1",
            "group_key": "abc",
            "series_ids": [1, 2],
            "names": ["Same Title", "Same Title"],
            "score": 1.0,
            "reasons": ["same_anilist_id"],
        }
    ]
    save_duplicate_groups_cache(2, groups)
    set_series_external_id_flags({1: True, 2: True, 3: False})

    client = app.test_client()
    res = client.get("/api/libraries/2/duplicates")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["cached"] is True
    assert data["count"] == 1
    assert set(data["member_ids"]) == {1, 2}

    res_refresh = client.get("/api/libraries/2/duplicates?refresh=1")
    assert res_refresh.status_code == 400


def test_identity_nested_and_weblink():
    from services.library_audit import merge_series_identity, series_has_external_id

    ident = merge_series_identity(
        {"id": 1, "name": "X"},
        {"malId": 42},
    )
    assert ident["ids"]["mal"] == "42"
    assert series_has_external_id({"webLinks": "https://anilist.co/manga/99"}) is True
    assert series_has_external_id({"name": "x"}) is False


def test_hygiene_dismissals_db(isolated_db):
    from db_manager import (
        delete_dup_dismissal,
        get_hygiene_library_meta,
        list_dup_dismissals,
        save_dup_dismissal,
        set_hygiene_library_meta,
    )

    set_hygiene_library_meta(7, {"missing": 1, "duplicates": 2, "no_external_id": 3})
    meta = get_hygiene_library_meta(7)
    assert meta["counts"]["missing"] == 1
    key = save_dup_dismissal(7, [10, 11], "not_duplicate")
    assert key
    assert len(list_dup_dismissals(7)) == 1
    assert delete_dup_dismissal(7, group_key=key) is True
    assert list_dup_dismissals(7) == []


def test_modal_overlay_in_template():
    from pathlib import Path

    html = Path("templates/partials/_library_audit_modal.html").read_text(encoding="utf-8")
    assert "modal-overlay" in html
    assert "missingVolumesModal" in html
    assert "missingIncludeUnknownCb" in html


def test_inventory_i18n_rename():
    from translations import translations

    assert translations["fr"]["toolbar_group_duplicates"] == "Inventaire"
    assert translations["en"]["toolbar_group_duplicates"] == "Inventory"
    assert "audit_chip_finished" in translations["fr"]
    assert "audit_missing_detail" in translations["en"]
    assert "Inventaire" in translations["fr"]["providers_completion_hint"]
    assert "Inventory" in translations["en"]["providers_completion_hint"]
    assert set(translations["fr"]) == set(translations["en"])


def test_cascade_ok_skips_backup(monkeypatch, caplog):
    import logging

    from services.library_audit.catalog_count import resolve_catalog_expected

    calls = []

    def fake_call(provider, **kwargs):
        calls.append(provider)
        if provider == "ANILIST":
            return {
                "expected": 12,
                "provider": "ANILIST",
                "unit": "volumes",
                "status": "ok",
                "publication_status": "FINISHED",
                "reason": "ok",
            }
        return {"status": "unknown", "provider": provider, "reason": "no_id"}

    monkeypatch.setattr(
        "services.library_audit.catalog_count._call_provider", fake_call
    )
    with caplog.at_level(logging.INFO):
        out = resolve_catalog_expected(
            {"aniListId": 1, "name": "Done"},
            library_type="Manga",
            series_name="Done",
            config={"PROVIDER_1": "ANILIST", "PROVIDER_2": "MANGADEX"},
        )
    assert out["expected"] == 12
    assert out["source"] == "cascade"
    assert out["publication_status"] == "FINISHED"
    assert calls == ["ANILIST"]
    assert "secours" not in caplog.text


def test_cascade_no_count_triggers_backup(monkeypatch, caplog):
    import logging

    from services.library_audit.catalog_count import resolve_catalog_expected

    calls = []

    def fake_call(provider, **kwargs):
        calls.append(provider)
        if provider == "MAL":
            return {
                "expected": 20,
                "provider": "MAL",
                "unit": "volumes",
                "status": "ok",
                "publication_status": "RELEASING",
                "reason": "ok",
            }
        return {
            "status": "unknown",
            "provider": provider,
            "reason": "volumes_null",
            "publication_status": "FINISHED",
        }

    monkeypatch.setattr(
        "services.library_audit.catalog_count._call_provider", fake_call
    )
    with caplog.at_level(logging.INFO):
        out = resolve_catalog_expected(
            {"malId": 99, "name": "Hole"},
            library_type="Manga",
            series_name="Hole",
            config={"PROVIDER_1": "MANGADEX", "PROVIDER_2": "KITSU"},
            identity={
                "name": "Hole",
                "libraryType": "Manga",
                "ids": {"mal": "99"},
            },
        )
    assert out["expected"] == 20
    assert out["source"] == "backup"
    assert out["backup_from"] == "MAL"
    assert "ANILIST" in calls and "MAL" in calls
    assert "MANGADEX" not in calls  # not catalog-capable
    assert "secours" in caplog.text


def test_backup_skips_already_tried(monkeypatch):
    from services.library_audit.catalog_count import resolve_catalog_expected

    calls = []

    def fake_call(provider, **kwargs):
        calls.append(provider)
        return {
            "status": "unknown",
            "provider": provider,
            "reason": "ongoing_no_count",
            "publication_status": "RELEASING",
        }

    monkeypatch.setattr(
        "services.library_audit.catalog_count._call_provider", fake_call
    )
    out = resolve_catalog_expected(
        {"aniListId": 5, "malId": 6, "name": "Ongoing"},
        library_type="Manga",
        series_name="Ongoing",
        config={"PROVIDER_1": "ANILIST", "PROVIDER_2": "MAL"},
        identity={
            "name": "Ongoing",
            "libraryType": "Manga",
            "ids": {"anilist": "5", "mal": "6"},
        },
    )
    assert out["status"] == "unknown"
    assert out["reason"] == "ongoing_no_count"
    assert out["publication_status"] == "RELEASING"
    assert calls == ["ANILIST", "MAL"]  # backup chain empty after cascade


def test_apply_catalog_override_keeps_pub():
    from services.library_audit import apply_catalog_override

    cat = apply_catalog_override(
        {
            "status": "unknown",
            "reason": "ongoing_no_count",
            "publication_status": "RELEASING",
            "provider": "ANILIST",
        },
        15,
    )
    assert cat["expected"] == 15
    assert cat["provider"] == "MANUAL"
    assert cat["status"] == "ok"
    assert cat["publication_status"] == "RELEASING"
    assert cat["reason"] == "manual"


def test_catalog_override_db_and_missing_api(isolated_db, monkeypatch):
    from flask import Flask

    from db_manager import (
        get_catalog_expected_override,
        save_volume_report_cache,
        set_catalog_expected_override,
        set_hygiene_library_meta,
    )
    from routes.library_audit import library_audit_bp

    set_catalog_expected_override(42, 10)
    assert get_catalog_expected_override(42) == 10
    set_catalog_expected_override(42, None)
    assert get_catalog_expected_override(42) is None

    save_volume_report_cache(
        7,
        {
            "series_name": "Gap Series",
            "badge": "1/5",
            "structure": "multi_volume",
            "missing_volumes": [2, 3, 4, 5],
            "publication_status": "FINISHED",
            "catalog": {
                "expected": 5,
                "status": "ok",
                "provider": "ANILIST",
                "reason": "ok",
                "publication_status": "FINISHED",
            },
            "stats": {"kavita_count": 1},
        },
    )
    save_volume_report_cache(
        8,
        {
            "series_name": "Unknown Series",
            "badge": "2/?",
            "structure": "multi_volume",
            "missing_volumes": [],
            "publication_status": "RELEASING",
            "catalog": {
                "status": "unknown",
                "reason": "ongoing_no_count",
                "publication_status": "RELEASING",
            },
            "stats": {"kavita_count": 2},
        },
    )
    set_hygiene_library_meta(1, {"missing": 1, "duplicates": 0, "no_external_id": 0})

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(library_audit_bp)
    monkeypatch.setattr(
        "routes.library_audit.load_config",
        lambda: {"UI_LANG": "en", "KAVITA_URL": "http://x", "KAVITA_API_KEY": "k"},
    )

    class FakeAPI:
        def __init__(self, *a, **k):
            pass

        def get_all_series(self, library_id=None):
            return [{"id": 7}, {"id": 8}]

    monkeypatch.setattr("routes.library_audit.KavitaAPI", FakeAPI)

    client = app.test_client()
    res = client.get("/api/libraries/1/missing-volumes")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["count"] == 1
    assert data["rows"][0]["series_id"] == 7
    assert data["rows"][0]["missing_volumes"] == [2, 3, 4, 5]
    assert data["rows"][0]["publication_status"] == "FINISHED"

    res_u = client.get("/api/libraries/1/missing-volumes?include_unknown=1")
    assert res_u.status_code == 200
    assert res_u.get_json()["count"] == 2

    csv = client.get("/api/libraries/1/missing-volumes?format=csv")
    assert csv.status_code == 200
    assert b"missing_volumes" in csv.data


def test_catalog_expected_post(isolated_db, monkeypatch):
    from flask import Flask

    from routes.library_audit import library_audit_bp

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(library_audit_bp)

    class FakeAPI:
        def __init__(self, *a, **k):
            pass

        def get_series(self, sid):
            return {"id": sid, "name": "Force Me", "libraryId": 1, "libraryType": "Manga"}

        def get_library_type_for_series(self, sid):
            return "Manga"

        def get_series_metadata(self, sid):
            return {}

        def get_series_volumes(self, sid):
            return [
                {"id": 1, "number": 1, "chapters": [{"id": 1, "number": 1, "summary": "a"}]},
                {"id": 2, "number": 2, "chapters": [{"id": 2, "number": 1, "summary": "b"}]},
            ]

    monkeypatch.setattr("routes.library_audit.KavitaAPI", FakeAPI)
    monkeypatch.setattr(
        "routes.library_audit.load_config",
        lambda: {"UI_LANG": "en", "KAVITA_URL": "http://x", "KAVITA_API_KEY": "k"},
    )
    monkeypatch.setattr("routes.library_audit.get_kavita_ui_url", lambda c: "http://ui")
    monkeypatch.setattr(
        "routes.library_audit.resolve_catalog_expected",
        lambda *a, **k: {
            "status": "unknown",
            "reason": "ongoing_no_count",
            "publication_status": "RELEASING",
            "provider": "ANILIST",
        },
    )

    client = app.test_client()
    res = client.post(
        "/api/series/55/catalog-expected",
        json={"expected": 5},
        content_type="application/json",
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["catalog"]["provider"] == "MANUAL"
    assert data["catalog"]["expected"] == 5
    assert data["missing_volumes"] == [3, 4, 5]
    assert data["publication_status"] == "RELEASING"


def test_format_number_ranges_compresses_and_elides():
    from services.library_audit import format_number_ranges

    assert format_number_ranges([2, 3, 4, 12]) == "2\u20134, 12"
    assert format_number_ranges([]) == ""
    assert format_number_ranges([7]) == "7"
    # Numéros isolés : au-delà de max_groups intervalles la suite est élidée.
    assert format_number_ranges([1, 3, 5], max_groups=2) == "1, 3, \u2026"


def test_resolve_completion_state_matrix():
    from services.library_audit import resolve_completion_state

    assert resolve_completion_state(5, 5)[0] == "complete"
    assert resolve_completion_state(5, 5, publication_status="RELEASING")[0] == "uptodate"
    assert resolve_completion_state(6, 5)[0] == "overshoot"
    assert resolve_completion_state(18, 20, missing_count=2)[0] == "near"
    assert resolve_completion_state(10, 20, missing_count=10)[0] == "partial"
    assert resolve_completion_state(2, 20, missing_count=18)[0] == "poor"
    assert resolve_completion_state(3, None)[0] == "unknown"
    assert resolve_completion_state(1, 1, is_oneshot=True)[0] == "neutral"


def test_volume_report_chapter_series_uses_chapter_unit():
    """Série sans tome (scans en chapitres) : l'attendu et le badge comptent
    des chapitres, pas des tomes."""
    volumes = [
        {
            "id": 1,
            "number": 0,
            "chapters": [
                {"id": 1, "number": 1, "summary": "a"},
                {"id": 2, "number": 2, "summary": "b"},
                {"id": 3, "number": 3, "summary": "c"},
            ],
        }
    ]
    report = build_volume_report(
        7,
        volumes,
        series_name="Chapter Only",
        catalog={
            "status": "ok",
            "expected": None,
            "expected_chapters": 10,
            "publication_status": "RELEASING",
            "provider": "ANILIST",
        },
    )
    assert report["unit_mode"] == "chapters"
    assert report["primary"]["unit"] == "chapters"
    assert report["primary"]["count"] == 3
    assert report["primary"]["expected"] == 10
    assert report["primary"]["missing_label"] == "4\u201310"
    assert "ch" in report["badge"]
    assert report["completion"]["state"] == "poor"


def test_loose_leaf_volume_is_counted_in_chapters():
    """Kavita 0.8 range les chapitres sans tome dans un volume `-100000`. Non
    reconnu, ce volume était compté comme un tome : « 7th garden » affichait
    8/8 tomes ET 1–8 manquants, avec « Tome -100000 » sur chaque ligne."""
    volumes = [
        {
            "id": 1,
            "number": -100000,
            "name": "",
            "chapters": [{"id": i, "number": i} for i in range(1, 9)],
        }
    ]
    report = build_volume_report(
        11,
        volumes,
        series_name="7th garden",
        catalog={
            "status": "ok",
            "expected": 8,
            "expected_chapters": 32,
            "publication_status": "RELEASING",
            "provider": "MAL",
        },
    )
    assert report["unit_mode"] == "chapters"
    assert report["primary"]["count"] == 8
    assert report["primary"]["expected"] == 32
    assert report["primary"]["missing_label"] == "9\u201332"
    assert report["missing_volumes"] == [], "aucun tome n'est attendu ici"
    assert all(u["volume_number"] is None for u in report["units"])


def test_isolated_volume_number_far_beyond_expected_is_out_of_range():
    """« Johan et Pirlouit » : 17 tomes + un tome numéroté 101 (intégrale mal
    parsée) annonçait 18/17 en violet (« plus que l'attendu ») et des trous
    locaux `18–100`, soit 83 numéros fantômes. Le hors-série est écarté du
    compte et nommé à part."""
    volumes = [
        {"id": n, "number": n, "name": str(n), "chapters": [{"id": n, "number": n}]}
        for n in list(range(1, 18)) + [101]
    ]
    report = build_volume_report(
        6000,
        volumes,
        series_name="Johan et Pirlouit",
        catalog={"status": "ok", "expected": 17, "provider": "COMICVINE", "unit": "issues"},
    )
    assert report["badge"] == "17/17"
    assert report["completion"]["state"] == "complete"
    assert report["primary"]["gaps"] == [], "aucun trou entre 1 et 17"
    assert report["primary"]["out_of_range"] == [101]
    assert report["stats"]["kavita_count"] == 17
    # Le nom recopiait le numéro du fichier : la colonne « Nom » affichait 1, 2, 3…
    assert all(u["name"] == "" for u in report["units"])


def test_default_chapter_sentinel_never_reaches_the_name_column():
    """« Adler » : chaque tome contient un chapitre couvrant tout le volume, donc
    sans numéro — Kavita 0.8 y met `-100000` (Parser.DefaultChapterNumber) et le
    recopie dans `range`. Faute de titre, le rapport affichait « -100000 » en
    guise de nom sur chaque ligne."""
    volumes = [
        {
            "id": n,
            "number": n,
            "name": str(n),
            "chapters": [{"id": n, "number": -100000, "minNumber": -100000,
                          "range": "-100000", "title": ""}],
        }
        for n in (1, 2)
    ]
    report = build_volume_report(
        12, volumes, series_name="Adler",
        catalog={"status": "ok", "expected": 10, "provider": "COMICVINE", "unit": "issues"},
    )
    assert [u["name"] for u in report["units"]] == ["", ""]
    assert all(u["chapter_number"] is None for u in report["units"])
    assert report["primary"]["count"] == 2
    assert report["primary"]["missing_label"] == "3\u201310"
    assert report["stats"]["chapter_count"] == 0, "la sentinelle n'est pas un chapitre"


def test_volumes_beyond_a_stale_expected_still_count():
    """L'écart ne doit pas devenir une excuse pour ignorer les tomes réels : un
    catalogue resté à 3 alors qu'on possède les tomes 4 et 5 doit continuer à
    signaler un dépassement, pas les jeter."""
    volumes = [
        {"id": n, "number": n, "chapters": [{"id": n, "number": n}]} for n in range(1, 6)
    ]
    report = build_volume_report(
        6001, volumes, series_name="Encore en cours",
        catalog={"status": "ok", "expected": 3, "provider": "ANILIST"},
    )
    assert report["primary"]["count"] == 5
    assert report["primary"]["out_of_range"] == []
    assert report["completion"]["state"] == "overshoot"


def test_volume_report_completion_and_labels_for_volumes():
    volumes = [
        {"id": i, "number": i, "chapters": [{"id": i, "number": i, "summary": "s"}]}
        for i in (1, 2, 5)
    ]
    report = build_volume_report(
        8,
        volumes,
        series_name="Gappy",
        catalog={
            "status": "ok",
            "expected": 6,
            "publication_status": "ENDED",
            "provider": "MAL",
        },
    )
    assert report["unit_mode"] == "volumes"
    assert report["primary"]["missing"] == [3, 4, 6]
    assert report["primary"]["missing_label"] == "3\u20134, 6"
    assert report["primary"]["gaps_label"] == "3\u20134"
    assert report["completion"]["state"] == "partial"
    assert report["completion"]["forced"] is False


def test_forced_expected_marks_completion_forced():
    volumes = [{"id": 1, "number": 1, "chapters": [{"id": 1, "number": 1}]}]
    report = build_volume_report(
        9,
        volumes,
        series_name="Forced",
        catalog={
            "status": "ok",
            "expected": 4,
            "provider": "MANUAL",
            "publication_status": "RELEASING",
        },
    )
    assert report["completion"]["forced"] is True
    assert report["badge"].endswith("*")


def test_inventory_exclusion_db_roundtrip(isolated_db):
    from db_manager import get_inventory_excluded_ids, set_inventory_excluded

    assert get_inventory_excluded_ids() == set()

    set_inventory_excluded(2, True)
    assert get_inventory_excluded_ids() == {2}

    set_inventory_excluded(2, False)
    assert get_inventory_excluded_ids() == set()


def test_inventory_routes_blocked_when_disabled(isolated_db, monkeypatch):
    """Un onglet resté ouvert ne doit pas relancer de scan quand la
    fonctionnalité est éteinte."""
    from flask import Flask

    from routes.library_audit import library_audit_bp

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(library_audit_bp)
    monkeypatch.setattr(
        "routes.library_audit.load_config",
        lambda: {"UI_LANG": "en", "LIBRARY_INVENTORY_ENABLED": False},
    )

    client = app.test_client()
    res = client.post(
        "/api/libraries/1/hygiene-scan", json={}, content_type="application/json"
    )
    assert res.status_code == 403
    assert res.get_json()["disabled"] is True


def test_inventory_translation_keys_present():
    from translations import translations

    for lang in ("fr", "en"):
        t = translations[lang]
        for state in (
            "complete",
            "uptodate",
            "near",
            "partial",
            "poor",
            "overshoot",
            "unknown",
            "neutral",
        ):
            assert t["audit_state_" + state]
        for key in (
            "audit_unit_volumes",
            "audit_unit_chapters",
            "audit_health_healthy",
            "audit_health_incomplete",
            "audit_health_unknown",
            "audit_excluded_badge",
            "audit_exclude_series",
            "audit_analyse_quick",
            "audit_cancel",
            "audit_err_disabled",
            "library_inventory_enabled",
            "library_inventory_enabled_hint",
            "scraping_cat_inventory",
        ):
            assert t[key]


def test_dashboard_translations_expose_audit_keys():
    """AppTranslations est injecté en boucle : les clés dynamiques
    (audit_state_*) doivent arriver au JS sans liste manuelle."""
    from pathlib import Path

    html = Path("templates/index.html").read_text(encoding="utf-8")
    assert "key.startswith('audit_')" in html
    assert "Object.assign(window.AppTranslations" in html


def test_no_enrich_imports_volume_report():
    import inspect
    import services.enrichment_engine as ee

    src = inspect.getsource(ee)
    assert "library_audit" not in src
    assert "volume_report" not in src
    assert "build_volume_report" not in src
