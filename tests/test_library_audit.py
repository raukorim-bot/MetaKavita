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


def test_a_scan_without_providers_keeps_the_expected_it_already_knew(monkeypatch):
    """`catalog=false` relit Kavita sans interroger les providers. Sans repli sur
    le cache, chaque série était réécrite en « attendu inconnu » : des heures de
    cascade AniList/MAL effacées, tous les badges retombés à `N/?`."""
    from services.library_audit import hygiene_scan as hs

    cache = {7: {"catalog": {"status": "ok", "expected": 24, "provider": "ANILIST"}}}
    monkeypatch.setattr(hs, "get_volume_report_cache", lambda sid: cache.get(sid))

    assert hs._cached_catalog(7) == {"status": "ok", "expected": 24, "provider": "ANILIST"}
    assert hs._cached_catalog(99) is None, "aucun cache : rien à réutiliser"


def test_a_shared_id_verdict_does_not_depend_on_iteration_order():
    """Un id partagé qui concorde vaut plus qu'un id partagé qui diverge, et le
    verdict doit être le même à chaque analyse."""
    from services.library_audit.duplicates import score_duplicate_pair

    a = {"ids": {"anilist": "100", "mal": "500"}, "name": "Berserk",
         "raw_series": {}, "raw_metadata": {}}
    b = {"ids": {"anilist": "100", "mal": "999"}, "name": "Berserk",
         "raw_series": {}, "raw_metadata": {}}

    verdicts = {repr(score_duplicate_pair(a, b)) for _ in range(20)}
    assert len(verdicts) == 1, "verdict instable d'une analyse à l'autre"
    res = score_duplicate_pair(a, b)
    assert res["score"] == 1.0 and res["reasons"] == ["same_anilist_id"]

    c = {"ids": {"anilist": "101", "mal": "999"}, "name": "Berserk",
         "raw_series": {}, "raw_metadata": {}}
    assert score_duplicate_pair(a, c) == {
        "score": 0.0, "reasons": ["different_anilist_id"]
    }


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


def test_bf195_inventory_folder_partial_save_preserves_config(isolated_db, monkeypatch):
    """BF195: INVENTORY_FOLDER_SAVE ne doit pas écraser KAVITA_URL ou le reste de la config."""
    from flask import Flask
    from routes.config import config_bp
    import config_manager

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(config_bp)
    client = app.test_client()

    cfg = config_manager.load_config()
    cfg["KAVITA_URL"] = "http://kavita.local:5000"
    cfg["SMART_COMPLETION"] = True
    cfg["SMART_SCORING"] = True
    cfg["TARGET_LANG"] = "EN"
    config_manager.save_config(cfg)

    resp = client.post(
        "/save-config",
        data={
            "INVENTORY_FOLDER_SAVE": "1",
            "INVENTORY_FOLDER_PATH_PREFIX": "/data/mangas",
            "INVENTORY_FOLDER_TRASH": "/data/.trash",
        },
    )
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True

    after = config_manager.load_config()
    assert after["KAVITA_URL"] == "http://kavita.local:5000"
    assert after["SMART_COMPLETION"] is True
    assert after["SMART_SCORING"] is True
    assert after["TARGET_LANG"] == "EN"
    assert after["INVENTORY_FOLDER_PATH_PREFIX"] == "/data/mangas"
    assert after["INVENTORY_FOLDER_TRASH"] == "/data/.trash"


def test_bf195_dup_dismiss_updates_hygiene_library_meta(isolated_db, monkeypatch):
    """BF195: library_duplicates_dismiss met à jour hygiene_library_meta counts['duplicates']."""
    from flask import Flask
    from routes.library_audit import library_audit_bp
    from db_manager import (
        set_hygiene_library_meta,
        get_hygiene_library_meta,
        save_duplicate_groups_cache,
    )

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(library_audit_bp)
    client = app.test_client()

    set_hygiene_library_meta("1", {"series": 10, "healthy": 8, "duplicates": 2, "missing": 1})
    save_duplicate_groups_cache("1", [
        {"group_id": "g1", "group_key": "k1", "series_ids": [10, 11]},
        {"group_id": "g2", "group_key": "k2", "series_ids": [20, 21]},
    ])

    resp = client.post(
        "/api/libraries/1/duplicates/dismiss",
        json={"series_ids": [10, 11], "reason": "not_duplicate"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True

    meta = get_hygiene_library_meta("1")
    assert meta["counts"]["duplicates"] == 1


def test_bf195_dup_dismiss_cross_library_scoping(isolated_db):
    """BF195: un doublon ignoré en bibliothèque 1 est visible dans 'all'."""
    from db_manager import save_dup_dismissal, list_dismissed_group_keys, delete_dup_dismissal

    gkey = save_dup_dismissal("1", [101, 102], "not_duplicate")
    assert gkey in list_dismissed_group_keys("all")
    assert gkey in list_dismissed_group_keys("1")

    ok = delete_dup_dismissal("all", group_key=gkey)
    assert ok is True
    assert gkey not in list_dismissed_group_keys("1")


def test_bf195_comicvine_volume_id_prefix_sanitization(monkeypatch):
    """BF195: le préfixe 4050- est nettoyé avant d'être concaténé."""
    from services.library_audit.catalog_count import _comicvine_issues
    from services.library_audit.series_identity import extract_provider_ids
    import requests

    ids = extract_provider_ids({}, forced_id="4050-12345", forced_provider="COMICVINE")
    assert ids["comicvine"] == "12345"

    requested_urls = []

    def mock_get(url, **kwargs):
        requested_urls.append(url)
        class MockResp:
            status_code = 200
            def json(self):
                return {"results": {"count_of_issues": 10, "name": "Batman", "id": 12345}}
        return MockResp()

    monkeypatch.setattr(requests, "get", mock_get)
    monkeypatch.setattr("services.library_audit.catalog_count._throttle", lambda p: object())

    res = _comicvine_issues("4050-12345", "fake_key")
    assert res["status"] == "ok"
    assert res["expected"] == 10
    assert requested_urls == ["https://comicvine.gamespot.com/api/volume/4050-12345/"]


def test_bf195_anilist_title_search_with_other_ids(monkeypatch):
    """BF195: si une série a un MAL ID mais pas d'AniList ID, la recherche par titre AniList est autorisée."""
    from services.library_audit.catalog_count import resolve_catalog_expected
    import services.library_audit.catalog_count as cc

    called_args = []

    def mock_call_provider(prov, **kwargs):
        called_args.append((prov, kwargs.get("allow_title_search")))
        return {"status": "unknown", "provider": prov, "reason": "no_hit"}

    monkeypatch.setattr(cc, "_call_provider", mock_call_provider)

    identity = {
        "ids": {"mal": "12345"},  # pas d'AniList ID
        "name": "Solo Leveling",
        "series": {},
        "metadata": {},
    }
    cfg = {
        "PROVIDER_1": "MAL",
        "PROVIDER_2": "ANILIST",
        "PROVIDER_3": "NONE",
    }
    resolve_catalog_expected(
        identity=identity,
        library_type="Manga",
        series_name="Solo Leveling",
        config=cfg,
    )
    # Vérifie qu'AniList a été appelé avec allow_title_search=True
    al_calls = [arg for arg in called_args if arg[0] == "ANILIST"]
    assert al_calls
    assert al_calls[0][1] is True


def test_bf195_nonexistent_series_volume_report_returns_404(isolated_db, monkeypatch):
    """BF195: demander le rapport d'une série inexistante renvoie 404."""
    from flask import Flask
    from routes.library_audit import library_audit_bp
    from kavita_api import KavitaAPI

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(library_audit_bp)
    client = app.test_client()

    monkeypatch.setattr(KavitaAPI, "get_series", lambda self, sid: None)

    resp = client.get("/api/series/999999/volume-report")
    assert resp.status_code == 404
    assert resp.get_json()["success"] is False

    resp2 = client.get("/api/series/999999/volume-report/units")
    assert resp2.status_code == 404


def test_bf195_audit_badges_returns_rich_items(isolated_db, monkeypatch):
    """BF195: /api/libraries/<lib>/audit-badges renvoie badges ET items enrichis."""
    from flask import Flask
    from routes.library_audit import library_audit_bp
    from db_manager import save_volume_report_cache

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(library_audit_bp)
    client = app.test_client()

    save_volume_report_cache(50, {
        "series_name": "Test Series",
        "badge": "10/10",
        "primary": {"unit": "volumes"},
        "completion": {"state": "complete", "forced": False},
    })

    resp = client.get("/api/libraries/all/audit-badges?ids=50")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["badges"]["50"] == "10/10"
    assert "items" in data
    assert data["items"]["50"]["badge"] == "10/10"
    assert data["items"]["50"]["state"] == "complete"
    assert data["items"]["50"]["forced"] is False
    assert data["items"]["50"]["unit"] == "volumes"


def test_bf195_empty_csv_txt_exports_when_no_cache(isolated_db, monkeypatch):
    """BF195: l'export CSV/TXT sur bibliothèque non scannée renvoie un CSV/TXT vide valide au lieu d'un JSON 404."""
    from flask import Flask
    from routes.library_audit import library_audit_bp

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(library_audit_bp)
    client = app.test_client()

    monkeypatch.setattr("routes.library_audit.get_hygiene_library_meta", lambda lib: None)
    monkeypatch.setattr("routes.library_audit.has_duplicate_groups_cache", lambda lib: False)

    resp_csv = client.get("/api/libraries/999/missing-volumes?format=csv")
    assert resp_csv.status_code == 200
    assert resp_csv.headers["Content-Type"].startswith("text/csv")
    assert "series_id" in resp_csv.get_data(as_text=True)

    resp_dup_csv = client.get("/api/libraries/999/duplicates?format=csv")
    assert resp_dup_csv.status_code == 200
    assert resp_dup_csv.headers["Content-Type"].startswith("text/csv")
    assert "group_id" in resp_dup_csv.get_data(as_text=True)


def test_bf195_freshness_translation_day_unit():
    """BF195: audit_freshness_day_short est traduit en FR et EN."""
    from translations import translations
    from pathlib import Path

    assert translations["fr"]["audit_freshness_day_short"] == "j"
    assert translations["en"]["audit_freshness_day_short"] == "d"

    js = Path("static/js/library_audit.js").read_text(encoding="utf-8")
    assert "tr.audit_freshness_day_short" in js
    assert "INVENTORY_FOLDER_SAVE" in js


def test_kavita_scan_library_method(monkeypatch):
    """Vérifie scan_library() pour une bibliothèque et pour 'all'."""
    from kavita_api import KavitaAPI

    api = KavitaAPI(url="http://kavita.local", api_key="dummy_key")
    calls = []

    def mock_send(method, url, **kwargs):
        calls.append((method, url))
        class MockResp:
            status_code = 200
        return MockResp()

    monkeypatch.setattr(api, "_send", mock_send)

    # Scan d'une lib spécifique
    assert api.scan_library(42) is True
    assert ("post", f"{api.url}/api/Library/scan?libraryId=42") in calls

    # Scan de toutes les libs
    calls.clear()
    assert api.scan_library("all") is True
    assert ("post", f"{api.url}/api/Library/scan-all") in calls


def test_kavita_delete_series_and_is_series_empty(monkeypatch):
    """Vérifie delete_series() et is_series_empty()."""
    from kavita_api import KavitaAPI

    api = KavitaAPI(url="http://kavita.local", api_key="dummy_key")

    # delete_series
    def mock_send_del(method, url, **kwargs):
        assert method == "delete"
        assert "seriesId=77" in url
        class MockResp:
            status_code = 200
        return MockResp()

    monkeypatch.setattr(api, "_send", mock_send_del)
    assert api.delete_series(77) is True

    # is_series_empty : série sans volumes
    monkeypatch.setattr(api, "fetch_series_volumes", lambda sid: ([], None))
    assert api.is_series_empty(77) is True

    # is_series_empty : série avec tomes mais sans chapitres
    monkeypatch.setattr(api, "fetch_series_volumes", lambda sid: ([{"id": 1, "chapters": []}], None))
    assert api.is_series_empty(77) is True

    # is_series_empty : série avec chapitres réels (non vide)
    monkeypatch.setattr(api, "fetch_series_volumes", lambda sid: ([{"id": 1, "chapters": [{"id": 10}]}], None))
    assert api.is_series_empty(77) is False


def test_library_kavita_scan_route(monkeypatch):
    """Route POST /api/libraries/<lib>/kavita-scan."""
    from flask import Flask
    from routes.library_audit import library_audit_bp

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(library_audit_bp)
    client = app.test_client()

    class MockApi:
        def scan_library(self, lib):
            return True

    monkeypatch.setattr("routes.library_audit._api", lambda: MockApi())

    resp = client.post("/api/libraries/5/kavita-scan")
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


def test_series_purge_empty_route(isolated_db, monkeypatch):
    """Route POST /api/series/<sid>/purge-empty."""
    from flask import Flask
    from routes.library_audit import library_audit_bp
    from db_manager import init_db, save_volume_report_cache

    init_db()
    save_volume_report_cache(88, {"series_name": "Ghost Series"})

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(library_audit_bp)
    client = app.test_client()

    class MockApi:
        def __init__(self, empty=False):
            self._empty = empty
        def is_series_empty(self, sid):
            return self._empty
        def delete_series(self, sid):
            return True

    # Cas 1 : non vide
    monkeypatch.setattr("routes.library_audit._api", lambda: MockApi(empty=False))
    resp_fail = client.post("/api/series/88/purge-empty")
    assert resp_fail.status_code == 400

    # Cas 2 : vide et suppression OK
    monkeypatch.setattr("routes.library_audit._api", lambda: MockApi(empty=True))
    resp_ok = client.post("/api/series/88/purge-empty")
    assert resp_ok.status_code == 200
    assert resp_ok.get_json()["success"] is True


def test_cluster_duplicate_series_volumetric_metrics():
    """Vérifie que cluster_duplicate_series attache volume_counts et recommended_keep_id."""
    from services.library_audit.duplicates import cluster_duplicate_series

    items = [
        {
            "id": 1,
            "name": "Berserk",
            "volume_count": 41,
            "chapter_count": 364,
            "folder_path": "/manga/Berserk (Complete)",
            "mal_id": 1234,
        },
        {
            "id": 2,
            "name": "Berserk",
            "volume_count": 5,
            "chapter_count": 40,
            "folder_path": "/manga/Berserk (Incomplete)",
            "mal_id": 1234,
        },
    ]

    groups = cluster_duplicate_series(items, threshold=0.9)
    assert len(groups) == 1
    g = groups[0]
    assert g["volume_counts"] == [41, 5]
    assert g["chapter_counts"] == [364, 40]
    assert g["recommended_keep_id"] == 1  # La série avec 41 tomes


def test_signalr_series_removed_handling(monkeypatch):
    """Vérifie que handle_invocation('SeriesRemoved', ...) purge chirurgicalement la série."""
    from services.kavita_hub import handle_invocation

    purged = []
    monkeypatch.setattr(
        "db_manager.purge_single_series_from_all_caches",
        lambda sid: purged.append(sid),
    )

    handled = handle_invocation("SeriesRemoved", {"seriesId": 50})
    assert handled is False  # Ne déclenche pas de wake scan scanner
    assert purged == [50]


def test_clean_orphaned_cache_prunes_duplicate_group_cache(isolated_db):
    """Vérifie que clean_orphaned_cache retire les séries supprimées de duplicate_group_cache."""
    from db_manager import init_db, save_duplicate_groups_cache, get_duplicate_groups_cache, clean_orphaned_cache, save_volume_report_cache

    init_db()
    # On enregistre les 2 séries dans volume_report_cache pour qu'elles soient suivies
    save_volume_report_cache(100, {"series_name": "Series A"})
    save_volume_report_cache(200, {"series_name": "Series B"})

    groups = [
        {
            "group_id": "dup-1",
            "series_ids": [100, 200],
            "names": ["Series A", "Series B"],
            "folder_paths": ["/path/A", "/path/B"],
            "score": 1.0,
            "reasons": ["same_id"],
        }
    ]
    save_duplicate_groups_cache("all", groups)
    assert len(get_duplicate_groups_cache("all")) == 1

    # Purge de la série 200 (seule la 100 reste) -> le groupe disparaît car < 2 membres
    clean_orphaned_cache({100})
    remaining = get_duplicate_groups_cache("all")
    assert len(remaining) == 0


def test_purge_single_series_from_all_caches_surgical(isolated_db):
    """Vérifie que purge_single_series_from_all_caches ne supprime QUE la série ciblée."""
    from db_manager import (
        init_db,
        save_volume_report_cache,
        get_volume_report_cache,
        save_duplicate_groups_cache,
        get_duplicate_groups_cache,
        purge_single_series_from_all_caches,
    )

    init_db()
    save_volume_report_cache(101, {"series_name": "Series 101", "badge": "1/10"})
    save_volume_report_cache(102, {"series_name": "Series 102", "badge": "5/5"})

    groups = [
        {
            "group_id": "dup-1",
            "series_ids": [101, 102, 103],
            "names": ["Series 101", "Series 102", "Series 103"],
            "folder_paths": ["/path/101", "/path/102", "/path/103"],
            "library_ids": [1, 1, 2],
            "score": 1.0,
            "reasons": ["same_title"],
        }
    ]
    save_duplicate_groups_cache("all", groups)

    # Purge chirurgicale de 101 uniquement
    deleted = purge_single_series_from_all_caches(101)
    assert deleted > 0

    # 101 doit être absent, 102 doit rester intact
    assert get_volume_report_cache(101) is None
    rep102 = get_volume_report_cache(102)
    assert rep102 is not None
    assert rep102["badge"] == "5/5"

    # Le groupe doit être taillé à [102, 103]
    grps = get_duplicate_groups_cache("all")
    assert len(grps) == 1
    assert grps[0]["series_ids"] == [102, 103]
    assert grps[0]["names"] == ["Series 102", "Series 103"]
    assert grps[0]["library_ids"] == [1, 2]


def test_missing_volumes_rows_network_error_isolation(isolated_db, monkeypatch):
    """En cas d'erreur de Kavita sur une lib donnée, le rapport retourne une liste vide et ne fuite pas."""
    from routes.library_audit import _missing_volumes_rows
    from db_manager import init_db, save_volume_report_cache

    init_db()
    save_volume_report_cache(10, {"series_name": "Manga X", "missing_volumes": [1, 2]})
    save_volume_report_cache(20, {"series_name": "Manga Y", "missing_volumes": [3]})

    class FailingAPI:
        def __init__(self, *a, **k):
            pass
        def get_all_series(self, library_id=None):
            raise ConnectionError("Kavita timeout")

    monkeypatch.setattr("routes.library_audit.KavitaAPI", FailingAPI)
    monkeypatch.setattr(
        "routes.library_audit.load_config",
        lambda: {"UI_LANG": "fr", "KAVITA_URL": "http://mock", "KAVITA_API_KEY": "k"},
    )

    # Pour une bibliothèque spécifique en panne, retourne [] plutôt que de fuiter toutes les libs
    rows = _missing_volumes_rows(library_id="2", include_unknown=False)
    assert rows == []


def test_duplicates_dismiss_cross_vue_sync(isolated_db, monkeypatch):
    """Dismisser un doublon en vue lib spécifique purge aussi le cache 'all'."""
    from flask import Flask
    from routes.library_audit import library_audit_bp
    from db_manager import (
        init_db,
        save_duplicate_groups_cache,
        get_duplicate_groups_cache,
        set_hygiene_library_meta,
        get_hygiene_library_meta,
    )

    init_db()
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(library_audit_bp)

    group = {
        "group_id": "dup-99",
        "group_key": "k99",
        "series_ids": [501, 502],
        "names": ["A", "B"],
        "folder_paths": ["/a", "/b"],
        "score": 1.0,
        "reasons": ["same_id"],
    }
    save_duplicate_groups_cache("3", [group])
    save_duplicate_groups_cache("all", [group])
    set_hygiene_library_meta("3", {"duplicates": 1})
    set_hygiene_library_meta("all", {"duplicates": 1})

    monkeypatch.setattr(
        "routes.library_audit.load_config",
        lambda: {"UI_LANG": "fr", "KAVITA_URL": "http://mock", "KAVITA_API_KEY": "k"},
    )

    client = app.test_client()
    res = client.post(
        "/api/libraries/3/duplicates/dismiss",
        json={"series_ids": [501, 502], "reason": "not_duplicate"},
    )
    assert res.status_code == 200
    assert res.get_json()["success"] is True

    # Doit être purgé de la lib 3 ET de la vue all
    assert len(get_duplicate_groups_cache("3")) == 0
    assert len(get_duplicate_groups_cache("all")) == 0
    assert get_hygiene_library_meta("3")["counts"]["duplicates"] == 0
    assert get_hygiene_library_meta("all")["counts"]["duplicates"] == 0


def test_hygiene_scan_excluded_count_scoped(isolated_db, monkeypatch):
    """Vérifie que counts['excluded'] reflète les séries exclues de la bibliothèque scannée (et non le total global)."""
    from services.library_audit.hygiene_scan import _run_scan
    from db_manager import init_db, set_inventory_excluded, get_hygiene_library_meta

    init_db()
    # On a 3 séries exclues au total au niveau de la DB
    set_inventory_excluded(1, True)
    set_inventory_excluded(2, True)
    set_inventory_excluded(99, True)

    class FakeAPI:
        def __init__(self, *a, **k):
            pass
        def get_all_series(self, library_id=None):
            # La lib 5 ne contient que la série 1 (exclue) et la série 10 (active)
            if str(library_id) == "5":
                return [
                    {"id": 1, "name": "Exclue Lib 5", "libraryId": 5},
                    {"id": 10, "name": "Active Lib 5", "libraryId": 5},
                ]
            return []
        def get_series_metadata(self, sid):
            return {}
        def get_series_volumes(self, sid):
            return []
        def get_library_type_for_series(self, sid):
            return "Manga"

    monkeypatch.setattr("services.library_audit.hygiene_scan.KavitaAPI", FakeAPI)
    monkeypatch.setattr(
        "services.library_audit.hygiene_scan.load_config",
        lambda: {"UI_LANG": "fr", "KAVITA_URL": "http://mock", "KAVITA_API_KEY": "k"},
    )
    monkeypatch.setattr(
        "services.library_audit.hygiene_scan.resolve_catalog_expected",
        lambda *a, **k: {"status": "ok", "expected": 1, "provider": "TEST"},
    )

    _run_scan(library_id="5", series_ids=[], with_catalog=False)
    meta = get_hygiene_library_meta("5")
    assert meta is not None
    # 1 seule série exclue dans la lib 5, même s'il y en a 3 au global
    assert meta["counts"]["excluded"] == 1




