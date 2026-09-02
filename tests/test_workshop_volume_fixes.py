"""Tests de validation des correctifs de la partie Volume (BF197 / C111).

Vérifie l'étanchéité du cycle de vie des tomes, l'élimination des résurrections de jaquettes,
la persistance dirty de la série, le staging magique, la purge du cache d'hygiène,
le déblocage de reprise de passe automatique et le brouillon unitaire de tome.
"""

from __future__ import annotations

import os

from db_manager import (
    clear_volume_unit_states,
    get_volume_unit_overrides,
    list_enriched_series_ids,
    mark_series_pass_done,
    save_volume_unit_override,
    save_volume_unit_state,
)
from services.workshop import (
    _merge_override_inscribed,
    save_magic_override,
    send_volume,
    send_selection,
    send_series,
    workshop_payload,
)


class DummyKavita:
    def __init__(self):
        self.series = {
            1: {
                "id": 1,
                "name": "One Piece",
                "libraryId": 10,
                "libraryType": "Manga",
                "coverImage": "kavita_cover.jpg",
            }
        }
        self.metadata = {
            1: {
                "id": 1,
                "summary": "Original series summary",
                "localizedName": "One Piece FR",
                "webLinks": "",
            }
        }
        self.volumes = {
            1: [
                {
                    "id": 100,
                    "number": 1,
                    "minNumber": 1,
                    "name": "Tome 1",
                    "chapters": [
                        {
                            "id": 10,
                            "number": 1,
                            "minNumber": 1,
                            "titleName": "Romance Dawn",
                            "summary": "Original volume summary",
                            "isbn": "",
                            "releaseDate": "2023-01-01T00:00:00",
                            "coverImage": "kavita_vol_cover.jpg",
                        }
                    ],
                }
            ]
        }

    def get_series(self, series_id):
        return self.series.get(int(series_id))

    def get_series_metadata(self, series_id):
        return self.metadata.get(int(series_id))

    def get_series_volumes(self, series_id):
        return self.volumes.get(int(series_id)) or []

    def get_chapter(self, chapter_id):
        for vols in self.volumes.values():
            for v in vols:
                for c in v.get("chapters", []):
                    if c["id"] == int(chapter_id):
                        return c
        return None

    def update_chapter_metadata(self, dto):
        return True, "ok"

    def upload_chapter_cover(self, chapter_id, url, lock=True):
        return True, "ok"

    def update_series_general(self, series_id, edits):
        return True, "ok", []

    def update_series_metadata(self, *args, **kwargs):
        return True, "ok"

    def upload_series_cover(self, series_id, url):
        return True, "ok"

    def update_series_external_ids(self, series_id, **kwargs):
        return True, "ok"


# ---------------------------------------------------------------------------
# Test 1 : Cycle de vie jaquette de tome & nettoyage post-envoi
# ---------------------------------------------------------------------------

def test_send_volume_clears_staged_cover_url_upon_success(isolated_db):
    """Quand un tome stagé avec une jaquette est envoyé, sa jaquette est retirée de l'override persistant."""
    dummy = DummyKavita()
    save_volume_unit_override(
        1,
        10,
        provider="MANGA_NEWS",
        provider_ref="https://example.com/ref",
        payload={
            "title": "Tome 1",
            "cover_url": "https://example.com/staged_cover.jpg",
            "_staged": True,
        },
    )

    before = workshop_payload(dummy, 1)
    card_before = before["units"][0]
    assert card_before["staged_cover_url"] == "https://example.com/staged_cover.jpg"

    res = send_volume(
        dummy,
        1,
        10,
        edits={"title": "Tome 1 Nouveau"},
        cover_url="https://example.com/staged_cover.jpg",
    )
    assert res["success"] is True

    after = workshop_payload(dummy, 1)
    card_after = after["units"][0]
    assert card_after["staged_cover_url"] == ""


# ---------------------------------------------------------------------------
# Test 2 : Préservation de initial_value dans les champs de série
# ---------------------------------------------------------------------------

def test_workshop_payload_preserves_series_initial_value(isolated_db):
    """workshop_payload fournit initial_value sur chaque champ pour seriesBaseline()."""
    from db_manager import save_workshop_series_override

    dummy = DummyKavita()
    save_workshop_series_override(
        1,
        {"summary": "Staged series summary"},
    )

    p = workshop_payload(dummy, 1)
    form = p["series"]["form"]
    summary_field = next(f for f in form if f["key"] == "summary")
    assert summary_field["value"] == "Staged series summary"
    assert summary_field["initial_value"] == "Original series summary"
    assert summary_field.get("staged") is True


# ---------------------------------------------------------------------------
# Test 3 : Champ Magique Tome pose _staged: True
# ---------------------------------------------------------------------------

def test_save_magic_override_sets_staged_flag(isolated_db, monkeypatch):
    """save_magic_override marque l'override en _staged: True et _source: magic."""
    def mock_fetch_volume(url, volume_number=None):
        return {
            "title": "Titre Magique",
            "summary": "Résumé Magique",
            "provider": "BEDETHEQUE",
            "provider_ref": url,
        }

    monkeypatch.setattr("services.workshop.fetch_volume_from_url", mock_fetch_volume)

    res = save_magic_override(1, 10, "https://www.bedetheque.com/album-123.html")
    assert res["success"] is True
    assert res["payload"]["_staged"] is True
    assert res["payload"]["_source"] == "magic"

    overrides = get_volume_unit_overrides(1)
    assert 10 in overrides
    assert overrides[10]["payload"]["_staged"] is True
    assert overrides[10]["payload"]["_source"] == "magic"


# ---------------------------------------------------------------------------
# Test 4 : Purge du cache d'hygiène lors des écritures Atelier
# ---------------------------------------------------------------------------

def test_workshop_sends_purge_hygiene_cache(isolated_db, monkeypatch):
    """send_volume, send_selection et send_series purgent le cache d'hygiène avec keep_overrides=True."""
    dummy = DummyKavita()
    purges = []

    def mock_purge(sid, **kw):
        purges.append((sid, kw))

    monkeypatch.setattr("services.volume_enrichment.apply.purge_series_hygiene_cache", mock_purge)

    res_v = send_volume(dummy, 1, 10, edits={"title": "Tome 1 Nouveau"}, force=True)
    assert res_v["success"] is True
    assert (1, {"keep_overrides": True}) in purges

    purges.clear()
    res_s = send_selection(dummy, 1, [{"chapter_id": 10, "edits": {"title": "Tome 1 Nouveau"}}], force=True)
    assert res_s["success"] is True
    assert (1, {"keep_overrides": True}) in purges

    purges.clear()
    res_ser = send_series(dummy, 1, edits={"summary": "Nouveau résumé"}, force=True)
    assert res_ser["success"] is True
    assert (1, {"keep_overrides": True}) in purges


# ---------------------------------------------------------------------------
# Test 5 : Déblocage de la reprise de passe après clear_volume_unit_states unitaire
# ---------------------------------------------------------------------------

def test_clear_volume_unit_states_removes_series_pass_sentinel(isolated_db):
    """clear_volume_unit_states avec un chapter_id retire aussi la sentinelle de série."""
    mark_series_pass_done(77, provider="MANGANEWS")
    save_volume_unit_state(77, 101, "DONE")
    save_volume_unit_state(77, 102, "DONE")

    assert 77 in list_enriched_series_ids()

    clear_volume_unit_states(77, chapter_id=101)

    assert 77 not in list_enriched_series_ids()


# ---------------------------------------------------------------------------
# Test 6 : Normalisation de dates et sentinelle dans _merge_override_inscribed
# ---------------------------------------------------------------------------

def test_merge_override_inscribed_normalizes_dates():
    """_merge_override_inscribed tronque le format ISO 'T' et ignore 0001-01-01."""
    base = {"title": "Base", "release_date": "2020-01-01"}

    ov_iso = {"payload": {"release_date": "2024-05-12T00:00:00"}}
    res1 = _merge_override_inscribed(base, ov_iso)
    assert res1["release_date"] == "2024-05-12"

    ov_sentinel = {"payload": {"release_date": "0001-01-01T00:00:00"}}
    res2 = _merge_override_inscribed(base, ov_sentinel)
    assert res2["release_date"] == "2020-01-01"


# ---------------------------------------------------------------------------
# Test 7 : Template volumes.html contient stats_chapter_volumes
# ---------------------------------------------------------------------------

def test_volumes_html_contains_stats_chapter_volumes():
    """templates/volumes.html injecte stats_chapter_volumes dans window.AppTranslations."""
    tpl_path = os.path.join(os.path.dirname(__file__), "..", "templates", "volumes.html")
    with open(tpl_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "stats_chapter_volumes:" in content


# ---------------------------------------------------------------------------
# Test 8 : Multi-candidats par ISBN avec all_scrapers=True
# ---------------------------------------------------------------------------

def test_fetch_by_isbn_all_scrapers_gathers_multiple_candidates(monkeypatch):
    """fetch_by_isbn avec all_scrapers=True ne s'arrête pas au premier scraper."""
    from services.volume_enrichment.providers import fetch_by_isbn

    class MockScraper1:
        id = "SCRAPER_1"
        def fetch(self, query, **kw):
            return {"title": "Tome 1 S1", "isbn": query}

    class MockScraper2:
        id = "SCRAPER_2"
        def fetch(self, query, **kw):
            return {"title": "Tome 1 S2", "isbn": query}

    class MockRegistry:
        @staticmethod
        def get(pid):
            if pid == "S1":
                return MockScraper1()
            if pid == "S2":
                return MockScraper2()
            return None

    monkeypatch.setattr("scrapers.ScraperRegistry", MockRegistry)

    units = [{"chapter_id": 1, "volume_number": 1, "isbn": "9782012345678"}]
    res = fetch_by_isbn(
        units,
        provider_ids=["S1", "S2"],
        all_scrapers=True,
    )
    assert len(res) == 2
    titles = [item["title"] for item in res.values()]
    assert "Tome 1 S1" in titles
    assert "Tome 1 S2" in titles


# ---------------------------------------------------------------------------
# Test 9 : Route draft-volume
# ---------------------------------------------------------------------------

def test_workshop_draft_volume_route(isolated_db, monkeypatch):
    """La route /workshop/draft-volume enregistre le brouillon d'un tome avec _staged: True."""
    from flask import Flask
    from routes.workshop import workshop_bp

    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test")
    app.register_blueprint(workshop_bp)
    client = app.test_client()

    monkeypatch.setattr("routes.workshop.workshop_enabled", lambda *a: True)
    dummy = DummyKavita()
    monkeypatch.setattr("routes.workshop._api", lambda *a: dummy)
    monkeypatch.setattr("routes.workshop._guard_series", lambda *a: (dummy.get_series(1), None))

    resp = client.post(
        "/api/series/1/workshop/draft-volume",
        json={
            "chapter_id": 10,
            "edits": {
                "title": "Titre Brouillon",
                "summary": "Résumé Brouillon",
            },
            "cover_url": "https://example.com/draft.jpg",
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["staged"] is True

    overrides = get_volume_unit_overrides(1)
    assert 10 in overrides
    ov = overrides[10]["payload"]
    assert ov["title"] == "Titre Brouillon"
    assert ov["summary"] == "Résumé Brouillon"
    assert ov["cover_url"] == "https://example.com/draft.jpg"
    assert ov["_staged"] is True
    assert ov["_source"] == "manual"
