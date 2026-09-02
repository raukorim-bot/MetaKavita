"""Atelier des tomes : hydratation sans scrape, overlay Magic, jaquette, 403."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from flask import Flask

from services.volume_enrichment.matching import match_units, units_from_volumes
from services.workshop import inscribed_from_chapter, overlay_overrides


@pytest.fixture
def client(monkeypatch, isolated_db):
    from routes.pages import pages_bp
    from routes.workshop import workshop_bp
    from routes.volume_enrichment import volume_enrichment_bp

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    app = Flask(
        __name__,
        template_folder=os.path.join(root, "templates"),
        static_folder=os.path.join(root, "static"),
    )
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    app.register_blueprint(pages_bp)
    app.register_blueprint(workshop_bp)
    app.register_blueprint(volume_enrichment_bp)
    return app.test_client()


def _enable(monkeypatch, **extra):
    import routes.pages as rp
    import routes.volume_enrichment as rve
    import routes.workshop as rw

    config = {
        "UI_LANG": "fr",
        "VOLUME_ENRICHMENT_ENABLED": True,
        "KAVITA_URL": "http://kavita.local",
        "KAVITA_API_KEY": "secret-key",
    }
    config.update(extra)
    monkeypatch.setattr(rw, "load_config", lambda: config)
    monkeypatch.setattr(rp, "load_config", lambda: config)
    monkeypatch.setattr(rve, "load_config", lambda: config)
    monkeypatch.setattr("services.workshop.load_config", lambda: config)
    return config


class FakeApi:
    def get_series(self, sid):
        if sid == 404:
            return None
        return {
            "id": sid,
            "name": "Saga",
            "localizedName": "La Saga",
            "libraryId": 1,
            "libraryType": "Manga",
            "coverImage": "series1.jpg",
        }

    def get_series_metadata(self, sid):
        return {"summary": "Un résumé."}

    def get_series_volumes(self, sid):
        return [
            {
                "id": 9,
                "minNumber": 1,
                "chapters": [
                    {
                        "id": 42,
                        "minNumber": 1,
                        "titleName": "Tome 1",
                        "summary": "Déjà là",
                        "isbn": "",
                        "releaseDate": "",
                        "coverImage": "chapter42.jpg",
                    }
                ],
            }
        ]

    def get_all_series(self, library_id=None):
        return [self.get_series(7)]

    def fetch_kavita_image(self, kind, entity_id):
        return b"\xff\xd8\xff", "image/jpeg"

    def authenticate(self):
        return True


def test_workshop_api_403_when_disabled(client, monkeypatch):
    _enable(monkeypatch, VOLUME_ENRICHMENT_ENABLED=False)
    res = client.get("/api/series/7/workshop")
    assert res.status_code == 403
    assert res.get_json()["disabled"] is True


def test_workshop_page_403_when_disabled(client, monkeypatch):
    _enable(monkeypatch, VOLUME_ENRICHMENT_ENABLED=False)
    assert client.get("/series/7/volumes").status_code == 403
    assert client.get("/volumes").status_code == 403


def test_workshop_landing_does_not_require_a_series(client, monkeypatch):
    """C108 : GET /volumes ouvre l'atelier sans id de série. Le rail (et le
    dernier sid en localStorage) choisit la fiche côté client."""
    _enable(monkeypatch)
    import routes.pages as rp

    api = FakeApi()
    monkeypatch.setattr(rp, "KavitaAPI", lambda *a, **k: api)
    monkeypatch.setattr("routes.pages.get_kavita_ui_url", lambda cfg: "http://kavita.ui")
    res = client.get("/volumes")
    html = res.get_data(as_text=True)
    assert res.status_code == 200
    assert "WORKSHOP_SERIES_ID = null" in html
    assert 'id="workshopIdle"' in html
    assert "Choisis une série dans le rail." in html
    assert "volumes.js" in html
    assert 'id="workshopRail"' in html


def test_dashboard_toolbar_links_to_the_workshop_landing():
    root = Path(__file__).resolve().parents[1]
    index_html = (root / "templates" / "index.html").read_text(encoding="utf-8")
    toolbar = (root / "templates" / "partials" / "_toolbar.html").read_text(encoding="utf-8")
    assert 'id="btnOpenWorkshop"' in index_html
    assert 'id="toolbarBtnOpenWorkshop"' in toolbar
    assert "pages.volumes" in toolbar
    assert "pages.volumes" in index_html
    assert "#mk-ico-workshop" in index_html
    assert "#mk-ico-workshop" in toolbar
    js = (root / "static" / "js" / "volumes.js").read_text(encoding="utf-8")
    assert "workshop_last_sid" in js
    assert "function pickLandingSeries" in js
    assert "is-idle" in js


def test_workshop_button_design_and_svg_icon_integrity():
    root = Path(__file__).resolve().parents[1]
    sprite = (root / "templates" / "partials" / "_icons_sprite.html").read_text(encoding="utf-8")
    assert '<symbol id="mk-ico-workshop" viewBox="0 0 24 24">' in sprite

    index_html = (root / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'class="btn-icon topbar-btn-workshop"' in index_html
    assert 'id="btnOpenWorkshop"' in index_html

    toolbar = (root / "templates" / "partials" / "_toolbar.html").read_text(encoding="utf-8")
    assert 'class="btn-toolbar-workshop"' in toolbar
    assert 'id="toolbarBtnOpenWorkshop"' in toolbar
    assert 'id="btnOpenWorkshop"' not in toolbar  # n'est plus un addon enfermé dans le panneau de volume

    css = (root / "static" / "css" / "style.css").read_text(encoding="utf-8")
    assert ".topbar-btn-workshop" in css
    assert ".btn-toolbar-workshop" in css
    assert ".topbar-workshop-label" in css


def test_workshop_payload_has_no_scrape(client, monkeypatch):
    _enable(monkeypatch)
    import routes.workshop as rw
    import routes.pages as rp

    api = FakeApi()
    monkeypatch.setattr(rw, "_api", lambda: api)
    monkeypatch.setattr(rp, "KavitaAPI", lambda *a, **k: api)
    monkeypatch.setattr("routes.pages.get_kavita_ui_url", lambda cfg: "http://kavita.ui")

    res = client.get("/api/series/7/workshop")
    data = res.get_json()
    assert res.status_code == 200
    assert data["series"]["name"] == "Saga"
    assert data["units"][0]["chapter_id"] == 42
    assert data["units"][0]["inscribed"]["title"] == "Tome 1"
    assert "language" in data["units"][0]["inscribed"]
    assert "/api/kavita-cover/chapter/42" in data["units"][0]["cover_url"]
    assert "secret-key" not in res.get_data(as_text=True)
    assert data.get("skipped_reason") == ""
    keys = [f["key"] for f in data["series"]["form"]]
    assert "localizedName" in keys
    assert "genres" in keys
    assert "writers" in keys
    assert "publicationStatus" in keys
    assert data["lookups"]["ageRating"]
    assert data["lookups"]["publicationStatus"]
    assert data["force"] is True
    groups = {f["key"]: f["group"] for f in data["series"]["form"]}
    assert groups["localizedName"] == "primary"
    assert groups["publishers"] == "primary"
    assert groups["writers"] == "primary"
    assert groups["coverArtists"] == "more"
    assert groups["language"] == "more"
    sizes = {f["key"]: f["size"] for f in data["series"]["form"]}
    assert sizes["language"] == "short"
    assert sizes["summary"] == "wide"
    assert sizes["localizedName"] == "mid"


def test_workshop_payload_flags_a_oneshot(client, monkeypatch):
    _enable(monkeypatch)
    import routes.workshop as rw

    class OneshotApi(FakeApi):
        def get_series_volumes(self, sid):
            return [
                {
                    "id": 9,
                    "minNumber": -100000,
                    "chapters": [{"id": 1, "minNumber": -100000, "titleName": "One shot"}],
                }
            ]

    monkeypatch.setattr(rw, "_api", lambda: OneshotApi())
    res = client.get("/api/series/7/workshop")
    data = res.get_json()
    assert res.status_code == 200
    assert data["skipped_reason"] == "oneshot"
    assert len(data["units"]) == 1


def test_workshop_payload_inscribes_magic_override(client, monkeypatch, isolated_db):
    _enable(monkeypatch)
    import routes.workshop as rw
    from db_manager import save_volume_unit_override

    class OneshotApi(FakeApi):
        def get_series_volumes(self, sid):
            return [
                {
                    "id": 9,
                    "minNumber": -100000,
                    "chapters": [{"id": 1, "minNumber": -100000, "titleName": ""}],
                }
            ]

    save_volume_unit_override(
        7,
        1,
        provider="BEDETHEQUE",
        provider_ref="http://x/album",
        payload={"title": "Magique", "isbn": "978123"},
    )
    monkeypatch.setattr(rw, "_api", lambda: OneshotApi())
    data = client.get("/api/series/7/workshop").get_json()
    ins = data["units"][0]["inscribed"]
    assert ins["title"] == "Magique"
    assert ins["isbn"] == "978123"
    assert data["skipped_reason"] == ""


def test_workshop_page_renders_distinct_cards(client, monkeypatch):
    _enable(monkeypatch)
    import routes.pages as rp

    api = FakeApi()
    monkeypatch.setattr(rp, "KavitaAPI", lambda *a, **k: api)
    monkeypatch.setattr("routes.pages.get_kavita_ui_url", lambda cfg: "http://kavita.ui")
    monkeypatch.setattr("routes.pages.workshop_rail", lambda *a, **k: [])
    monkeypatch.setattr("routes.pages.workshop_payload", lambda *a, **k: {
        "series": api.get_series(7) | {"cover_url": "/api/kavita-cover/series/7?v=1", "summary": "Un résumé."},
        "units": [],
        "history": [],
        "force": False,
        "pass_running": False,
    })
    res = client.get("/series/7/volumes")
    html = res.get_data(as_text=True)
    assert res.status_code == 200
    assert 'class="workshop-series-card"' in html
    assert 'id="workshopVolumeList"' in html
    assert 'id="workshopRail"' in html
    assert "secret-key" not in html
    assert 'name="csrf-token"' in html


def test_workshop_page_404_unknown_series(client, monkeypatch):
    _enable(monkeypatch)
    import routes.pages as rp

    api = FakeApi()
    monkeypatch.setattr(rp, "KavitaAPI", lambda *a, **k: api)
    assert client.get("/series/404/volumes").status_code == 404


def test_kavita_cover_does_not_leak_api_key(client, monkeypatch):
    _enable(monkeypatch)
    import routes.workshop as rw

    api = FakeApi()
    monkeypatch.setattr(rw, "_api", lambda: api)
    res = client.get("/api/kavita-cover/chapter/42")
    assert res.status_code == 200
    assert res.mimetype.startswith("image/")
    assert b"secret-key" not in res.data
    assert "KAVITA_API_KEY" not in (res.headers.get("Content-Disposition") or "")


def test_kavita_cover_is_served_from_disk_on_the_second_hit(client, monkeypatch, isolated_db):
    _enable(monkeypatch)
    import routes.workshop as rw

    calls = []

    class CountingApi(FakeApi):
        def fetch_kavita_image(self, kind, entity_id):
            calls.append((kind, entity_id))
            return super().fetch_kavita_image(kind, entity_id)

    monkeypatch.setattr(rw, "_api", lambda: CountingApi())
    url = "/api/kavita-cover/series/7?v=abc123def456"
    first = client.get(url)
    cached = client.get(url)
    not_modified = client.get(url, headers={"If-None-Match": '"abc123def456"'})
    assert first.status_code == 200
    assert cached.status_code == 200
    assert first.data == cached.data == b"\xff\xd8\xff"
    assert not_modified.status_code == 304
    assert calls == [("series", 7)]
    assert "max-age=86400" in (cached.headers.get("Cache-Control") or "")
    assert first.headers.get("ETag") == '"abc123def456"'


def test_kavita_cover_cache_rejects_path_etags_and_prunes_old_files(isolated_db):
    from services import kavita_cover_cache

    assert kavita_cover_cache.safe_etag("../etc/passwd") == "0"
    assert kavita_cover_cache.safe_etag("abc123def456") == "abc123def456"
    kavita_cover_cache.write("series", 7, "abc123def456", b"old", "image/jpeg")
    kavita_cover_cache.write("series", 7, "otheretag12", b"new", "image/png")
    assert kavita_cover_cache.read("series", 7, "abc123def456") is None
    hit = kavita_cover_cache.read("series", 7, "otheretag12")
    assert hit == (b"new", "image/png")


def test_workshop_rail_carries_dashboard_status(client, monkeypatch, isolated_db):
    _enable(monkeypatch)
    import routes.workshop as rw
    from db_manager import save_series_override
    from models import SeriesOverride

    save_series_override(SeriesOverride(series_id=7), status="COMPLETED")
    monkeypatch.setattr(rw, "_api", lambda: FakeApi())
    res = client.get("/api/workshop/rail")
    data = res.get_json()
    assert res.status_code == 200
    assert data["rail"][0]["id"] == 7
    assert data["rail"][0]["status"] == "COMPLETED"
    assert "/api/kavita-cover/series/7" in data["rail"][0]["cover_url"]


def test_overlay_override_wins_field_by_field(isolated_db):
    from db_manager import save_volume_unit_override

    save_volume_unit_override(
        1,
        42,
        provider="MANGANEWS",
        provider_ref="https://www.manga-news.com/index.php/serie/x/vol-1",
        payload={"title": "VF", "summary": ""},
    )
    units = units_from_volumes(
        [{"id": 1, "minNumber": 1, "chapters": [{"id": 42, "minNumber": 1}]}]
    )
    merged = overlay_overrides(
        1,
        {"1": {"title": "EN", "summary": "From index"}},
        units,
    )
    assert merged["1"]["title"] == "VF"
    assert merged["1"]["summary"] == "From index"


def test_match_units_honours_chapter_override_key():
    units = [
        {
            "chapter_id": 9,
            "volume_number": None,
            "chapter_number": None,
            "is_special": False,
            "chapter": {},
        }
    ]
    matched, unmatched = match_units(
        units,
        {"ch:9": {"title": "One-shot", "summary": "x"}},
    )
    assert len(matched) == 1
    assert matched[0][1]["title"] == "One-shot"
    assert unmatched == []


def test_inscribed_from_chapter_reads_nested_dto():
    ins = inscribed_from_chapter(
        {
            "titleName": "Album",
            "summary": "S",
            "isbn": "978123",
            "titleNameLocked": True,
        }
    )
    assert ins["title"] == "Album"
    assert ins["title_locked"] is True


def test_workshop_reset_does_not_call_kavita_write(client, monkeypatch, isolated_db):
    _enable(monkeypatch)
    import routes.volume_enrichment as rve
    from db_manager import save_volume_unit_override

    save_volume_unit_override(7, 42, provider="X", provider_ref="http://x", payload={"title": "A"})
    written = []

    class GuardApi(FakeApi):
        def update_chapter_metadata(self, *a, **k):
            written.append("chapter")
            return False, "no"

        def update_series_metadata(self, *a, **k):
            written.append("series")
            return False, "no", False

    monkeypatch.setattr(rve, "_api", lambda: GuardApi())
    res = client.post("/api/series/7/volume-enrich/reset", json={"workshop": True})
    assert res.status_code == 200
    assert res.get_json()["workshop"] is True
    assert written == []
    from db_manager import get_volume_unit_overrides

    assert get_volume_unit_overrides(7) == {}


def test_pass_reset_keeps_magic_overrides(client, monkeypatch, isolated_db):
    _enable(monkeypatch)
    import routes.volume_enrichment as rve
    from db_manager import get_volume_unit_overrides, save_volume_unit_override

    save_volume_unit_override(7, 42, provider="X", provider_ref="http://x", payload={"title": "A"})
    monkeypatch.setattr(rve, "clear_volume_unit_states", lambda sid: None)
    monkeypatch.setattr(rve, "forget_series", lambda sid: 0)
    res = client.post("/api/series/7/volume-enrich/reset", json={})
    assert res.status_code == 200
    assert res.get_json().get("workshop") is None
    assert get_volume_unit_overrides(7)[42]["provider"] == "X"


def test_dom_ids_exist_in_volumes_template():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "templates" / "volumes.html").read_text(
        encoding="utf-8"
    )
    for dom_id in (
        "workshopRail",
        "workshopSeriesCard",
        "workshopSeriesFields",
        "workshopVolumeList",
        "workshopSendSelection",
        "workshopSendAll",
        "workshopHistory",
        "workshopForce",
        "workshopRailSearch",
        "workshopSearchInside",
        "workshopRailStatus",
        "workshopHideIgnored",
        "workshopMain",
        "workshopSeriesName",
        "workshopPrev",
        "workshopNext",
        "workshopRailCount",
        "workshopBarStats",
        "workshopLoading",
        "workshopSeriesMore",
        "workshopReviewSeries",
        "workshopSuperSeries",
        "workshopSeriesCoverPick",
        "workshopCoverModal",
    ):
        assert f'id="{dom_id}"' in html
    assert '_manual_review_modal.html' in html
    assert '<input type="checkbox" id="workshopForce"' not in html
    assert "workshop-series-card" in html
    assert "workshop-more" in html
    assert "workshop-force-note" in html
    assert "/library/" in html
    css = (Path(__file__).resolve().parents[1] / "static" / "css" / "volumes.css").read_text(
        encoding="utf-8"
    )
    assert ".workshop-series-card" in css
    assert ".workshop-volume-card" in css
    assert "#fdba74" in css or "253, 186, 116" in css
    assert ".workshop-force-note" in css
    assert ".workshop-more" in css
    assert 'position: sticky' in css
    assert '[data-dirty="1"]' in css
    js = (Path(__file__).resolve().parents[1] / "static" / "js" / "volumes.js").read_text(
        encoding="utf-8"
    )
    assert "applyForceLocks" in js
    assert "data-isbn-locked" in js
    assert "workshopSeriesFields" in js
    assert "data-series-field" in js
    assert "snapshotDirty" in js
    assert "data-dirty" in js
    assert "function forceOn" in js
    assert "keepDirty" in js
    assert "skipped_reason" in js
    assert "vol_preview_oneshot" in js
    assert "function boot" in js
    assert "library_id" not in js
    assert "history.pushState" in js
    assert "popstate" in js
    assert "workshopSearchInside" in js
    assert "filter_search_inside" in js
    assert "filter_hide_ignored" in js
    assert "filter_library" in js
    assert "force: true" in js
    assert "force: forceOn()" not in js
    assert "window.location.href = workshopUrl" not in js
    assert "function kavitaSeriesUrl" in js
    assert "libraryId" in js
    assert "/library/" in js
    assert "workshop-rail-chip" in js
    assert "mk-ico-lock" in js
    assert "workshop-field--empty" in css
    assert "workshop-field--short" in css
    assert "repeat(6, minmax(0, 1fr))" in css
    assert "workshop_show_more" in js
    assert "fieldsByGroup" in js
    assert 'class="workshop-more workshop-filled"' not in js
    assert "workshop-magic-chip" in js
    assert "function updateNavButtons" in js
    assert "ev.key === '/' " in js or "ev.key === '/'" in js
    assert "function unitFromHistory" in js
    assert "volume_number: item.volume_number" in js
    assert "workshopMain.scrollTop" not in js
    assert "WORKSHOP_FORCE_REVIEW" in js
    assert "mrPrepareForBatch" in js
    assert "openManualReviewModal" in js
    assert "startCoverSearch" in js
    assert "data-cover-url" in js
    assert "/update-cover" not in js
    assert "function openCoverPicker" in js
    assert "aspect-ratio: 2 / 3" in css
    assert "workshop-cover-pick" in css
    assert 'id="log-console"' in html
    assert 'id="logFollowBtn"' in html
    assert "workshop-logs" in html
    sprite = (
        Path(__file__).resolve().parents[1] / "templates" / "partials" / "_icons_sprite.html"
    ).read_text(encoding="utf-8")
    assert 'id="mk-ico-lock"' in sprite
    assert 'id="mk-ico-wand"' in sprite
    assert 'id="mk-ico-info"' in sprite


def test_volumes_js_parses():
    """Un `.catch` en trop a déjà rendu l'atelier entier muet : le fichier
    ne s'exécutait plus, d'où une page sans nom, sans rail et sans cartes."""
    from pathlib import Path
    import shutil
    import subprocess

    path = Path(__file__).resolve().parents[1] / "static" / "js" / "volumes.js"
    src = path.read_text(encoding="utf-8")
    assert "            }).catch(function () { setSending(false); });\n            }).catch" not in src
    node = shutil.which("node")
    if not node:
        return
    result = subprocess.run(
        [node, "--check", str(path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_workshop_series_review_opens_the_waiting_modal():
    """The workshop has no sidebar Review checkboxes. forceSync must set a
    one-shot flag so mrPrepareForBatch / mrOnSyncSettled do not no-op, then
    open the waiting shell before POST /force-sync."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    volumes = (root / "static" / "js" / "volumes.js").read_text(encoding="utf-8")
    review = (root / "static" / "js" / "manual_review.js").read_text(encoding="utf-8")
    socket = (root / "static" / "js" / "websocket.js").read_text(encoding="utf-8")
    css = (root / "static" / "css" / "volumes.css").read_text(encoding="utf-8")
    assert "WORKSHOP_FORCE_REVIEW" in volumes
    assert "mrPrepareForBatch" in volumes
    assert "openManualReviewModal" in volumes
    assert "workshopApplyReview" in volumes
    assert "applyVolumeReview" in volumes
    assert "workshop_confirm_volume" not in volumes
    assert "function workshopForceReviewShot" in review
    assert "function applyWorkshopQueueScope" in review
    assert "function isWorkshopPage" in review
    assert "confirmBody.workshop = true" in review
    assert "body.workshop = true" in review
    assert "isWorkshopPage()" in review
    assert "workshopForceReviewShot()" in review
    assert "window.WORKSHOP_FORCE_REVIEW = null" in review
    assert "seriesId: s.id" in volumes
    assert "companionOnlySeriesId = Number(sid)" in review
    assert "typeof window.mrOnSyncSettled === 'function'" in socket
    assert "html.workshop-page #manualReviewModal" in css
    assert "mrPickPanel" in volumes
    assert "dataset.kind = 'volume'" in volumes


def test_workshop_page_embeds_the_series_payload(client, monkeypatch):
    _enable(monkeypatch)
    import routes.pages as rp

    api = FakeApi()
    monkeypatch.setattr(rp, "KavitaAPI", lambda *a, **k: api)
    monkeypatch.setattr("routes.pages.get_kavita_ui_url", lambda cfg: "http://kavita.ui")
    res = client.get("/series/7/volumes")
    html = res.get_data(as_text=True)
    assert res.status_code == 200
    assert "WORKSHOP_PAYLOAD" in html
    assert "Saga" in html
    assert "42" in html
    assert "volumes.js" in html
    assert 'id="workshopRailStatus"' in html
    assert 'id="workshopSearchInside"' in html
    assert 'id="workshopHideIgnored"' in html
    assert 'id="workshopMain"' in html
    assert 'id="workshopSeriesName"' in html
    assert "/library/1/series/7" in html
    assert "Plus de champs" in html
    assert "Champ Magique" in html
    assert 'id="log-console"' in html
    assert "websocket.js" in html
    assert "live_logs" in html
    assert 'id="manualReviewModal"' in html
    assert 'id="workshopReviewSeries"' in html
    assert "manual_review.js" in html
    assert "covers.js" in html
    assert 'id="workshopCoverModal"' in html
    assert 'id="workshopSeriesCoverPick"' in html


def _lock_writes(monkeypatch):
    monkeypatch.setattr(
        "services.volume_enrichment.job.claim_series_write", lambda sid: True
    )
    monkeypatch.setattr(
        "services.volume_enrichment.job.release_series_write", lambda sid: None
    )
    monkeypatch.setattr(
        "services.volume_enrichment.job.get_volume_enrich_state",
        lambda: {"running": False},
    )


def test_send_volume_noop_is_200(client, monkeypatch, isolated_db):
    _enable(monkeypatch)
    import routes.workshop as rw

    monkeypatch.setattr(rw, "_api", lambda: FakeApi())
    _lock_writes(monkeypatch)
    monkeypatch.setattr(
        "services.workshop.apply_entry",
        lambda *a, **k: {"status": "SKIPPED", "written": [], "error": ""},
    )
    res = client.post(
        "/api/series/7/workshop/send",
        json={"chapter_id": 42, "edits": {"title": "Tome 1"}},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["noop"] is True


def test_send_volume_failure_is_500(client, monkeypatch, isolated_db):
    _enable(monkeypatch)
    import routes.workshop as rw

    monkeypatch.setattr(rw, "_api", lambda: FakeApi())
    _lock_writes(monkeypatch)
    monkeypatch.setattr(
        "services.workshop.apply_entry",
        lambda *a, **k: {"status": "FAILED", "written": [], "error": "boom"},
    )
    res = client.post(
        "/api/series/7/workshop/send",
        json={"chapter_id": 42, "edits": {"title": "Tome 1"}},
    )
    assert res.status_code == 500
    assert res.get_json()["success"] is False


def test_send_series_skips_unchanged_and_empty_localized_name(client, monkeypatch, isolated_db):
    _enable(monkeypatch)
    import routes.workshop as rw

    calls = []

    class Api(FakeApi):
        def update_series_general(self, *a, **k):
            calls.append("loc")
            return True, "ok"

        def update_series_metadata(self, *a, **k):
            calls.append("meta")
            return True, "ok", True

    monkeypatch.setattr(rw, "_api", lambda: Api())
    _lock_writes(monkeypatch)
    res = client.post(
        "/api/series/7/workshop/send-series",
        json={"edits": {"summary": "Un résumé.", "localizedName": ""}},
    )
    assert res.status_code == 200
    assert res.get_json()["noop"] is True
    assert calls == []


def test_send_series_force_overwrites_summary(client, monkeypatch, isolated_db):
    _enable(monkeypatch)
    import routes.workshop as rw

    calls = []

    class Api(FakeApi):
        def update_series_metadata(self, payload):
            calls.append(payload.get("summary"))
            return True, "ok", True

        def update_series_general(self, *a, **k):
            calls.append("loc")
            return True, "ok"

    monkeypatch.setattr(rw, "_api", lambda: Api())
    _lock_writes(monkeypatch)
    res = client.post(
        "/api/series/7/workshop/send-series",
        json={"edits": {"summary": "Nouveau"}, "force": False},
    )
    assert res.status_code == 200
    assert res.get_json()["success"] is True
    assert "Nouveau" in calls
    assert "loc" not in calls


def test_send_series_handles_kavita_3_tuple_from_update_series_general(client, monkeypatch, isolated_db):
    _enable(monkeypatch)
    import routes.workshop as rw

    calls = []

    class Api(FakeApi):
        def update_series_metadata(self, payload):
            calls.append("meta")
            return True, "ok", True

        def update_series_general(self, *a, **k):
            calls.append("general")
            # KavitaAPI.update_series_general returns a 3-tuple (success, message, sealed)
            return True, "Mise à jour réussie", True

    monkeypatch.setattr(rw, "_api", lambda: Api())
    _lock_writes(monkeypatch)
    res = client.post(
        "/api/series/7/workshop/send-series",
        json={"edits": {"localizedName": "Titre Alternatif"}},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "localizedName" in data["written"]
    assert "general" in calls


def test_send_series_uploads_chosen_cover(client, monkeypatch, isolated_db):
    _enable(monkeypatch)
    import routes.workshop as rw

    covers = []

    class Api(FakeApi):
        def upload_series_cover(self, series_id, cover_url):
            covers.append((series_id, cover_url))
            return True, "ok"

    marked = []
    monkeypatch.setattr(rw, "_api", lambda: Api())
    monkeypatch.setattr("services.workshop.mark_cover_manual", lambda sid: marked.append(sid))
    _lock_writes(monkeypatch)
    res = client.post(
        "/api/series/7/workshop/send-series",
        json={"edits": {}, "cover_url": "https://cdn.example/cover.jpg"},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["success"] is True
    assert "cover" in body["written"]
    assert covers == [(7, "https://cdn.example/cover.jpg")]
    assert marked == [7]


def test_workshop_sends_ignore_client_force_false(client, monkeypatch, isolated_db):
    _enable(monkeypatch)
    import routes.workshop as rw

    seen = []
    monkeypatch.setattr(rw, "_api", lambda: FakeApi())
    monkeypatch.setattr(
        rw,
        "send_volume",
        lambda *a, **k: seen.append(("vol", k.get("force"))) or {"success": True, "noop": True, "status": "SKIPPED"},
    )
    monkeypatch.setattr(
        rw,
        "send_series",
        lambda *a, **k: seen.append(("series", k.get("force"))) or {"success": True, "noop": True, "written": []},
    )
    monkeypatch.setattr(
        rw,
        "send_selection",
        lambda *a, **k: seen.append(("sel", k.get("force"))) or {"success": True, "noop": True, "results": []},
    )
    monkeypatch.setattr(
        rw,
        "confirm_volume_review",
        lambda *a, **k: seen.append(("rev", k.get("force"))) or {"success": True, "noop": True},
    )
    assert client.post(
        "/api/series/7/workshop/send",
        json={"chapter_id": 42, "edits": {"title": "X"}, "force": False},
    ).status_code == 200
    assert client.post(
        "/api/series/7/workshop/send-series",
        json={"edits": {"summary": "X"}, "force": False},
    ).status_code == 200
    assert client.post(
        "/api/series/7/workshop/send-selection",
        json={"items": [{"chapter_id": 42}], "force": False},
    ).status_code == 200
    assert client.post(
        "/api/series/7/workshop/review/confirm",
        json={"chapter_id": 42, "candidate": {}, "force": False},
    ).status_code == 200
    assert seen == [("vol", True), ("series", True), ("sel", True), ("rev", True)]


def test_workshop_volume_review_confirm_stages_without_kavita(client, monkeypatch, isolated_db):
    """BF190 : Review tome remplit la carte. Kavita n'est écrit qu'à l'envoi."""
    _enable(monkeypatch)
    import routes.workshop as rw
    from db_manager import get_volume_unit_overrides

    writes = []
    monkeypatch.setattr(rw, "_api", lambda: FakeApi())
    monkeypatch.setattr(
        "services.workshop.send_volume",
        lambda *a, **k: writes.append("send") or {"success": True, "status": "DONE"},
    )
    res = client.post(
        "/api/series/7/workshop/review/confirm",
        json={
            "chapter_id": 42,
            "candidate": {
                "title": "Album",
                "summary": "Résumé",
                "isbn": "9782205073348",
                "cover_url": "https://cdn.example/a.jpg",
                "provider": "MANGANEWS",
                "provider_ref": "http://mn/x",
            },
        },
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["staged"] is True
    assert writes == []
    assert data["edits"]["title"] == "Album"
    assert data["cover_url"] == "https://cdn.example/a.jpg"
    ov = get_volume_unit_overrides(7)[42]
    assert ov["payload"]["title"] == "Album"


def test_series_edits_from_built_maps_preview_to_form():
    from services.workshop_form import series_edits_from_built

    edits, cover = series_edits_from_built(
        {
            "metadata": {
                "summary": "Hello",
                "releaseYear": 2020,
                "publicationStatus": 2,
                "ageRating": 8,
                "publishers": [{"name": "Ki-oon"}],
                "genres": [{"title": "Action"}],
                "writers": [{"name": "Auteur"}],
                "webLinks": "https://anilist.co/manga/1",
                "language": "fr",
            },
            "localized_name": "Titre VF",
            "cover_url": "https://cdn.example/c.jpg",
        },
        [
            "summary",
            "year",
            "status",
            "age",
            "publisher",
            "genres",
            "staff",
            "alt_titles",
            "weblinks",
            "language",
            "cover",
        ],
    )
    assert edits["summary"] == "Hello"
    assert edits["releaseYear"] == "2020"
    assert edits["publicationStatus"] == "2"
    assert edits["ageRating"] == "8"
    assert edits["publishers"] == "Ki-oon"
    assert edits["genres"] == "Action"
    assert edits["writers"] == "Auteur"
    assert edits["localizedName"] == "Titre VF"
    assert edits["webLinks"] == "https://anilist.co/manga/1"
    assert edits["language"] == "fr"
    assert cover == "https://cdn.example/c.jpg"
    empty, no_cover = series_edits_from_built(
        {"metadata": {"ageRating": 0, "summary": ""}, "cover_url": "https://x"},
        ["summary", "age", "cover"],
    )
    assert empty == {}
    assert no_cover == "https://x"


def test_send_series_partial_is_not_500(client, monkeypatch, isolated_db):
    _enable(monkeypatch)
    import routes.workshop as rw

    class Api(FakeApi):
        def update_series_metadata(self, payload):
            return True, "ok", True

        def update_series_general(self, *a, **k):
            return False, "loc failed"

    monkeypatch.setattr(rw, "_api", lambda: Api())
    _lock_writes(monkeypatch)
    res = client.post(
        "/api/series/7/workshop/send-series",
        json={"edits": {"summary": "Nouveau", "localizedName": "Autre"}, "force": True},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is False
    assert data["partial"] is True
    assert "summary" in data["written"]


def test_send_series_writes_genres_in_one_metadata_post(client, monkeypatch, isolated_db):
    _enable(monkeypatch)
    import routes.workshop as rw

    payloads = []

    class Api(FakeApi):
        def update_series_metadata(self, payload):
            payloads.append(payload)
            return True, "ok", True

        def update_series_general(self, *a, **k):
            raise AssertionError("localizedName must stay untouched")

    monkeypatch.setattr(rw, "_api", lambda: Api())
    _lock_writes(monkeypatch)
    res = client.post(
        "/api/series/7/workshop/send-series",
        json={"edits": {"genres": "Action, Fantasy"}, "force": True},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["written"] == ["genres"]
    assert len(payloads) == 1
    assert payloads[0]["seriesId"] == 7
    assert payloads[0]["genres"] == [
        {"id": 0, "title": "Action"},
        {"id": 0, "title": "Fantasy"},
    ]
    assert payloads[0]["genresLocked"] is True


def test_send_selection_partial_is_200(client, monkeypatch, isolated_db):
    _enable(monkeypatch)
    import routes.workshop as rw

    monkeypatch.setattr(rw, "_api", lambda: FakeApi())
    _lock_writes(monkeypatch)

    def fake_apply(_api, _sid, entry, **_k):
        cid = entry.get("chapter_id")
        if cid == 42:
            return {"status": "DONE", "written": ["title"], "error": ""}
        return {"status": "FAILED", "written": [], "error": "boom"}

    monkeypatch.setattr("services.workshop.apply_entry", fake_apply)
    res = client.post(
        "/api/series/7/workshop/send-selection",
        json={
            "items": [
                {"chapter_id": 42, "edits": {"title": "Tome 1"}},
                {"chapter_id": 43, "edits": {"title": "Tome 2"}},
            ]
        },
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is False
    assert data["partial"] is True
    assert data["sent"] == 1


def test_send_selection_holds_the_series_lock_until_the_last_volume(client, monkeypatch, isolated_db):
    _enable(monkeypatch)
    import routes.workshop as rw

    claims = []
    releases = []
    monkeypatch.setattr(rw, "_api", lambda: FakeApi())
    monkeypatch.setattr(
        "services.volume_enrichment.job.claim_series_write",
        lambda sid: claims.append(sid) or True,
    )
    monkeypatch.setattr(
        "services.volume_enrichment.job.release_series_write",
        lambda sid: releases.append(sid),
    )
    monkeypatch.setattr(
        "services.volume_enrichment.job.get_volume_enrich_state",
        lambda: {"running": False},
    )
    monkeypatch.setattr(
        "services.workshop.apply_entry",
        lambda *a, **k: {"status": "DONE", "written": ["title"], "error": ""},
    )
    res = client.post(
        "/api/series/7/workshop/send-selection",
        json={
            "items": [
                {"chapter_id": 42, "edits": {"title": "Tome 1"}},
                {"chapter_id": 43, "edits": {"title": "Tome 2"}},
            ]
        },
    )
    assert res.status_code == 200
    assert claims == [7]
    assert releases == [7]
    assert res.get_json()["results"][0]["chapter_id"] == 42


def test_pass_blocks_only_the_series_being_written(monkeypatch):
    monkeypatch.setattr(
        "services.volume_enrichment.job.get_volume_enrich_state",
        lambda: {"running": True, "library_id": "1", "series_id": 9},
    )
    from services.workshop import _pass_blocks

    assert _pass_blocks(7) is False
    assert _pass_blocks(9) is True


def test_workshop_volume_reset_clears_that_unit_state(client, monkeypatch, isolated_db):
    _enable(monkeypatch)
    import routes.volume_enrichment as rve
    from db_manager import get_volume_unit_states, save_volume_unit_state

    save_volume_unit_state(7, 42, "DONE")
    save_volume_unit_state(7, 43, "DONE")
    monkeypatch.setattr(rve, "_api", lambda: FakeApi())
    res = client.post(
        "/api/series/7/volume-enrich/reset",
        json={"workshop": True, "chapter_id": 42},
    )
    assert res.status_code == 200
    states = get_volume_unit_states(7)
    assert 42 not in states
    assert 43 in states


def test_apply_entry_workshop_writes_language_without_index_fields(isolated_db):
    from services.volume_enrichment.apply import apply_entry

    class Api:
        def __init__(self):
            self.written = []

        def get_chapter(self, cid):
            return {"id": cid, "titleName": "Tome 1", "summary": "", "isbn": "", "language": ""}

        def update_chapter_metadata(self, dto):
            self.written.append(dto)
            return True, "ok"

    api = Api()
    out = apply_entry(
        api,
        7,
        {"chapter_id": 42, "changes": {}, "edits": {"language": "fr"}},
        origin="workshop",
    )
    assert out["status"] == "DONE"
    assert "language" in out["written"]
    assert api.written[0]["language"] == "fr"
    assert api.written[0]["languageLocked"] is True


def test_workshop_send_history_names_the_volume(isolated_db):
    from db_manager import list_workshop_history
    from services.volume_enrichment.apply import apply_entry

    class Api:
        def get_chapter(self, cid):
            return {"id": cid, "titleName": "Tome 1", "summary": "", "isbn": "", "language": ""}

        def update_chapter_metadata(self, dto):
            return True, "ok"

    apply_entry(
        Api(),
        7,
        {"chapter_id": 42, "volume_number": 3, "changes": {}, "edits": {"language": "fr"}},
        origin="workshop",
    )
    row = list_workshop_history(7)[0]
    assert row["event"] == "send"
    assert row["detail"]["volume_number"] == 3
    assert "language" in row["detail"]["fields"]


def test_workshop_form_skips_empty_localized_name_and_unknown_age():
    from services.workshop_form import apply_series_edits, series_form
    from translations import translations

    t = translations["fr"]
    series = {"id": 7, "localizedName": "La Saga"}
    metadata = {"summary": "Un résumé.", "ageRating": 0}
    form = series_form(series, metadata, t)
    meta, written, localized = apply_series_edits(
        metadata,
        series,
        form,
        {"localizedName": "", "ageRating": "0", "writers": "Moebius"},
        force=True,
    )
    assert localized is None
    assert "localizedName" not in written
    assert "ageRating" not in written
    assert written == ["writers"]
    assert meta["writers"] == [{"id": 0, "name": "Moebius"}]
    meta2, written2, _ = apply_series_edits(
        metadata,
        series,
        form,
        {"ageRating": "8"},
        force=False,
    )
    assert written2 == ["ageRating"]
    assert meta2["ageRating"] == 8


def test_series_form_splits_primary_and_more():
    from services.workshop_form import series_form
    from translations import translations

    form = series_form(
        {"id": 7, "localizedName": "La Saga"},
        {"summary": "Un résumé."},
        translations["fr"],
    )
    groups = {f["key"]: f["group"] for f in form}
    assert groups["localizedName"] == "primary"
    assert groups["summary"] == "primary"
    assert groups["publishers"] == "primary"
    assert groups["genres"] == "primary"
    assert groups["tags"] == "primary"
    assert groups["writers"] == "primary"
    assert groups["pencillers"] == "primary"
    assert groups["coverArtists"] == "more"
    assert groups["translators"] == "more"
    assert groups["language"] == "more"
    sizes = {f["key"]: f["size"] for f in form}
    assert sizes["summary"] == "wide"
    assert sizes["genres"] == "wide"
    assert sizes["tags"] == "wide"
    assert sizes["localizedName"] == "mid"
    assert sizes["publishers"] == "mid"
    assert sizes["writers"] == "mid"
    assert sizes["pencillers"] == "mid"
    assert sizes["releaseYear"] == "short"
    assert sizes["publicationStatus"] == "short"
    assert sizes["ageRating"] == "short"
    assert sizes["language"] == "short"
    primary = [f["key"] for f in form if f["group"] == "primary"]
    assert primary == [
        "localizedName",
        "summary",
        "releaseYear",
        "publicationStatus",
        "ageRating",
        "publishers",
        "genres",
        "tags",
        "writers",
        "pencillers",
    ]


def test_workshop_copy_names_the_sheet_and_volumes():
    from translations import translations

    assert translations["fr"]["workshop_send_series"] == "Envoyer la fiche"
    assert translations["en"]["workshop_send_series"] == "Send the sheet"
    assert translations["fr"]["workshop_send_all"] == "Envoyer tous les tomes"
    assert translations["en"]["workshop_send_all"] == "Send every volume"
    assert translations["fr"]["workshop_review_series"] == "Manual Review"
    assert translations["en"]["workshop_review_series"] == "Manual Review"
    assert translations["fr"]["workshop_super_series"] == "Super Review"
    assert translations["en"]["workshop_super_series"] == "Super Review"
    assert translations["fr"]["workshop_reset_series"] == "Reset"
    assert translations["en"]["workshop_reset_series"] == "Reset"
    assert translations["fr"]["workshop_super"] == "Super Review"
    assert translations["en"]["workshop_super"] == "Super Review"
    assert translations["fr"]["workshop_choose_cover"] == "Choisir une couverture"
    assert translations["en"]["workshop_choose_cover"] == "Choose a cover"
    assert "identique" in translations["fr"]["workshop_noop"]
    assert "identical" in translations["en"]["workshop_noop"]
    assert translations["fr"]["workshop_magic_label"] == "Champ Magique"
    assert translations["en"]["workshop_magic_label"] == "Magic Input"
    assert translations["fr"]["workshop_more_fields"] == "Plus de champs"
    assert translations["en"]["workshop_more_fields"] == "More fields"
    assert "{0} complétés / {1}" in translations["fr"]["workshop_more_fields_count"]
    assert "{0} filled / {1}" in translations["en"]["workshop_more_fields_count"]
    assert "{0} complété / {1}" in translations["fr"]["workshop_more_fields_count_single"]
    assert "{0} filled / {1}" in translations["en"]["workshop_more_fields_count_single"]
    assert translations["fr"]["workshop_open"] == "Atelier"
    assert translations["en"]["workshop_open"] == "Workshop"
    assert translations["fr"]["workshop_pick_series"] == "Choisis une série dans le rail."
    assert translations["en"]["workshop_pick_series"] == "Pick a series in the rail."
    assert "rail" in translations["fr"]["workshop_open_page_hint"].lower()
    assert "rail" in translations["en"]["workshop_open_page_hint"].lower()
    assert "Kavita" in translations["fr"]["workshop_review_staged"]
    assert "Send" in translations["en"]["workshop_review_staged"]


def test_workshop_403_when_library_is_disabled(client, monkeypatch):
    _enable(monkeypatch, DISABLED_LIBRARIES="1")
    import routes.workshop as rw
    import routes.pages as rp

    api = FakeApi()
    monkeypatch.setattr(rw, "_api", lambda: api)
    monkeypatch.setattr(rp, "KavitaAPI", lambda *a, **k: api)
    assert client.get("/api/series/7/workshop").status_code == 403
    assert client.get("/series/7/volumes").status_code == 403
