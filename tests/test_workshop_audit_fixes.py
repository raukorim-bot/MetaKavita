import os
import pytest

from db_manager import (
    save_volume_unit_override,
    get_volume_unit_overrides,
    save_workshop_series_override,
    get_workshop_series_override,
    clear_workshop_series_override,
    park_pending_review,
    list_pending_reviews,
    get_all_cached_data,
    update_status,
)
from services.workshop import (
    confirm_volume_review,
    overlay_overrides,
    _merge_override_inscribed,
    workshop_payload,
    send_volume,
    send_series,
    reset_workshop,
    begin_volume_review,
    extract_external_ids_from_weblinks,
)
from services.volume_enrichment.job import enrich_one_series


class DummyKavita:
    def __init__(self):
        self.chapter_metadata_calls = []
        self.chapter_cover_calls = []
        self.series_metadata_calls = []
        self.series_general_calls = []
        self.series_external_ids_calls = []
        self.series_cover_calls = []

    def get_series(self, series_id):
        return {"id": series_id, "name": "Audit Series", "libraryType": "Manga", "libraryId": 1}

    def get_series_metadata(self, series_id):
        return {"summary": "A test summary"}

    def get_series_volumes(self, series_id):
        return [
            {
                "id": 100,
                "minNumber": 1,
                "chapters": [
                    {
                        "id": 10,
                        "minNumber": 1,
                        "title": "Old Title",
                        "summary": "Old Summary",
                        "isbn": "",
                        "releaseDate": "2020-01-01",
                        "coverImage": "hash123",
                    }
                ],
            }
        ]

    def get_chapter(self, chapter_id):
        return {
            "id": chapter_id,
            "title": "Old Title",
            "summary": "Old Summary",
            "isbn": "",
            "releaseDate": "2020-01-01",
            "coverImage": "hash123",
        }

    def update_chapter_metadata(self, dto):
        self.chapter_metadata_calls.append(dto)
        return True, "OK"

    def upload_chapter_cover(self, chapter_id, url, lock=True):
        self.chapter_cover_calls.append((chapter_id, url, lock))
        return True, "OK"

    def update_series_metadata(self, dto):
        self.series_metadata_calls.append(dto)
        return True, "OK"

    def update_series_general(self, series_id, localized_name=None):
        self.series_general_calls.append((series_id, localized_name))
        return True, "OK"

    def update_series_external_ids(self, series_id, anilist_id=None, mal_id=None, mangabaka_id=None):
        self.series_external_ids_calls.append((series_id, anilist_id, mal_id, mangabaka_id))
        return True, "OK"

    def upload_series_cover(self, series_id, url):
        self.series_cover_calls.append((series_id, url))
        return True, "OK"



# ---------------------------------------------------------------------------
# Priorité 1 : Bulk-accept & Bouton Liste dans l'Atelier
# ---------------------------------------------------------------------------

def test_bulk_accept_rejects_workshop_flag():
    """POST /api/manual-reviews/bulk-accept avec workshop: True est refusé avec HTTP 400."""
    from flask import Flask
    from routes.manual_review import manual_review_bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(manual_review_bp)
    c = app.test_client()

    res = c.post("/api/manual-reviews/bulk-accept", json={"threshold": 0.6, "workshop": True})
    assert res.status_code == 400
    data = res.get_json()
    assert data["success"] is False
    assert data["error"] == "bulk_accept_unsupported_in_workshop"


def test_volumes_css_hides_list_toggle_on_workshop_page():
    """Le CSS volumes.css masque explicitement .mr-list-toggle-btn et #mrListToggleBtn sur workshop-page."""
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "volumes.css")
    with open(css_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "html.workshop-page .mr-list-toggle-btn" in content
    assert "html.workshop-page #mrListToggleBtn" in content
    assert "display: none !important;" in content


def test_manual_review_js_guards_against_workshop():
    """Le fichier manual_review.js court-circuite mrToggleListView et mrBulkAccept si isWorkshopPage()."""
    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "manual_review.js")
    with open(js_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "window.mrToggleListView = function () {" in content
    assert "if (isWorkshopPage()) return;" in content
    assert "window.mrBulkAccept = function () {" in content
    assert "if (isWorkshopPage() || bulkAcceptInFlight) return;" in content


# ---------------------------------------------------------------------------
# Priorité 2 : Staging Override Tome vs Passe Automatique
# ---------------------------------------------------------------------------

def test_confirm_volume_review_marks_staged(isolated_db):
    """confirm_volume_review pose un override marqué _staged: True."""
    api = DummyKavita()
    cand = {
        "title": "Tome 1 Staged",
        "summary": "Résumé Staged",
        "cover_url": "https://example.com/cover1.jpg",
        "provider": "MANGANEWS",
        "provider_ref": "https://example.com/item1",
    }
    res = confirm_volume_review(api, series_id=42, chapter_id=10, candidate=cand)
    assert res["success"] is True
    assert res["staged"] is True

    ovs = get_volume_unit_overrides(42)
    assert 10 in ovs
    ov = ovs[10]
    assert ov["payload"]["_staged"] is True
    assert ov["payload"]["_source"] == "review"
    assert ov["payload"]["title"] == "Tome 1 Staged"
    assert ov["payload"]["cover_url"] == "https://example.com/cover1.jpg"


def test_overlay_overrides_ignores_staged_overrides(isolated_db):
    """overlay_overrides ignore les overrides dont le payload contient _staged: True."""
    save_volume_unit_override(
        42,
        10,
        provider="MANGANEWS",
        provider_ref="https://example.com/item1",
        payload={"title": "Staged Title", "_staged": True},
    )
    units = [{"chapter_id": 10, "volume_number": 1, "chapter_number": None}]
    merged = overlay_overrides(42, {"1": {"title": "Index Title"}}, units)
    # L'override étant _staged, il ne doit PAS écraser l'index !
    assert merged["1"]["title"] == "Index Title"

    # En revanche, un override non-staged (ex: Champ Magique) doit toujours gagner
    save_volume_unit_override(
        42,
        10,
        provider="MANGANEWS",
        provider_ref="https://example.com/item1",
        payload={"title": "Magic Title"},
    )
    merged_magic = overlay_overrides(42, {"1": {"title": "Index Title"}}, units)
    assert merged_magic["1"]["title"] == "Magic Title"


def test_enrich_one_series_skips_staged_chapters(isolated_db, monkeypatch):
    """_enrich_one_series exclut les unités marquées _staged pour ne pas écrire par-dessus l'atelier."""
    api = DummyKavita()
    # On pose un override staged sur le chapitre 10
    save_volume_unit_override(
        42,
        10,
        provider="MANGANEWS",
        provider_ref="https://example.com/item1",
        payload={"title": "Tome 1 Staged", "_staged": True},
    )
    series = api.get_series(42)

    # Si la passe automatique tourne sur cette série où la seule unité est staged :
    # elle doit se clore sans appeler d'écriture dans Kavita
    result = enrich_one_series(api, series, resume=False, config={})
    assert result["counts"]["done"] == 0
    assert len(api.chapter_metadata_calls) == 0
    assert len(api.chapter_cover_calls) == 0


def test_send_volume_clears_staged_flag(isolated_db):
    """send_volume nettoie le drapeau _staged une fois l'écriture effectuée dans Kavita."""
    api = DummyKavita()
    save_volume_unit_override(
        42,
        10,
        provider="MANGANEWS",
        provider_ref="https://example.com/item1",
        payload={"title": "Tome 1 Staged", "summary": "Nouveau", "_staged": True},
    )

    res = send_volume(api, 42, 10, edits={"title": "Tome 1 Envoyé"})
    assert res["success"] is True
    assert res["status"] == "DONE"

    # Vérifie que l'override en base existe encore mais n'a plus _staged
    ovs = get_volume_unit_overrides(42)
    assert 10 in ovs
    assert "_staged" not in ovs[10]["payload"]


# ---------------------------------------------------------------------------
# Priorité 3 : Jaquette Tome après Reload (F5)
# ---------------------------------------------------------------------------

def test_merge_override_inscribed_includes_cover_url():
    """_merge_override_inscribed propage cover_url depuis le payload de l'override."""
    inscribed = {"title": "Base", "summary": "", "isbn": "", "release_date": ""}
    override = {"payload": {"title": "New Title", "cover_url": "https://example.com/pic.jpg"}}
    merged = _merge_override_inscribed(inscribed, override)
    assert merged["title"] == "New Title"
    assert merged["cover_url"] == "https://example.com/pic.jpg"


def test_workshop_payload_exposes_staged_cover_url(isolated_db):
    """workshop_payload expose staged_cover_url sur les cartes d'unité."""
    api = DummyKavita()
    save_volume_unit_override(
        42,
        10,
        provider="MANGANEWS",
        provider_ref="https://example.com/item1",
        payload={"title": "Tome 1", "cover_url": "https://example.com/scraped_cover.jpg"},
    )
    p = workshop_payload(api, 42)
    assert len(p["units"]) == 1
    card = p["units"][0]
    assert card["chapter_id"] == 10
    assert card["staged_cover_url"] == "https://example.com/scraped_cover.jpg"
    assert card["inscribed"]["cover_url"] == "https://example.com/scraped_cover.jpg"


def test_volumes_js_renders_data_cover_url_from_staged_cover():
    """volumes.js inclut data-cover-url et data-cover-display si un stagedCover est présent."""
    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "volumes.js")
    with open(js_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "var stagedCover = (ov.payload && ov.payload.cover_url) || u.staged_cover_url" in content
    assert "data-cover-url=" in content
    assert "data-cover-display=" in content


# ---------------------------------------------------------------------------
# Audit Anomalie 2 : Recherche de review par ISBN sur override non transmis
# ---------------------------------------------------------------------------

def test_begin_volume_review_propagates_override_isbn(isolated_db, monkeypatch):
    """begin_volume_review transmet l'ISBN de l'override à fetch_by_isbn même si le chapitre Kavita a isbn vide."""
    api = DummyKavita()
    save_volume_unit_override(
        42,
        10,
        provider="MANGANEWS",
        provider_ref="https://example.com/item1",
        payload={"isbn": "9782012345678"},
    )

    captured_units = []

    def mock_fetch_by_isbn(units, library_type=None, config=None):
        captured_units.extend(units)
        return {
            10: {
                "title": "Trouvé par ISBN",
                "isbn": "9782012345678",
                "provider": "BEDETHEQUE",
            }
        }

    import services.volume_enrichment.providers as providers
    monkeypatch.setattr(providers, "fetch_by_isbn", mock_fetch_by_isbn)

    res = begin_volume_review(api, 42, 10)
    assert res["success"] is True
    assert len(captured_units) == 1
    assert captured_units[0]["isbn"] == "9782012345678"
    assert captured_units[0]["chapter"]["isbn"] == "9782012345678"
    cand_titles = [c.get("title") for c in res.get("candidates", [])]
    assert "Trouvé par ISBN" in cand_titles


# ---------------------------------------------------------------------------
# Audit Anomalie 3 : Persistance Fiche Série (Staging SQLite & Auto-save)
# ---------------------------------------------------------------------------

def test_workshop_series_override_crud_and_staging(isolated_db):
    """CRUD complet de workshop_series_overrides et comportement lors du F5."""
    assert get_workshop_series_override(42) is None

    save_workshop_series_override(
        42,
        {"summary": "Mon résumé brouillon", "localizedName": "Titre FR"},
        cover_url="https://example.com/staged_series.jpg",
    )
    ov = get_workshop_series_override(42)
    assert ov is not None
    assert ov["payload"]["summary"] == "Mon résumé brouillon"
    assert ov["payload"]["localizedName"] == "Titre FR"
    assert ov["cover_url"] == "https://example.com/staged_series.jpg"

    clear_workshop_series_override(42)
    assert get_workshop_series_override(42) is None


def test_workshop_payload_rehydrates_series_draft(isolated_db):
    """workshop_payload injecte les champs du brouillon série dans le formulaire et les métadonnées."""
    api = DummyKavita()
    save_workshop_series_override(
        42,
        {"summary": "Résumé brouillon persistant", "localizedName": "Titre Localisé"},
        cover_url="https://example.com/staged_series.jpg",
    )

    p = workshop_payload(api, 42)
    assert p is not None
    s = p["series"]
    assert s["summary"] == "Résumé brouillon persistant"
    assert s["localizedName"] == "Titre Localisé"
    assert s["staged_cover_url"] == "https://example.com/staged_series.jpg"
    assert s["cover_url"] == "https://example.com/staged_series.jpg"
    assert s["override"]["summary"] == "Résumé brouillon persistant"

    # Vérifie que le champ form correspondant est pré-rempli et marqué staged
    summary_field = next(f for f in s["form"] if f["key"] == "summary")
    assert summary_field["value"] == "Résumé brouillon persistant"
    assert summary_field.get("staged") is True


def test_draft_series_route(isolated_db, monkeypatch):
    """POST /api/series/<id>/workshop/draft-series enregistre le brouillon en base."""
    from flask import Flask
    from routes.workshop import workshop_bp

    monkeypatch.setattr("routes.workshop.workshop_enabled", lambda *a: True)
    monkeypatch.setattr("routes.workshop._guard_series", lambda *a: (DummyKavita().get_series(42), None))

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(workshop_bp)
    c = app.test_client()

    res = c.post(
        "/api/series/42/workshop/draft-series",
        json={
            "edits": {"summary": "Nouveau résumé draft"},
            "cover_url": "https://example.com/draft.jpg",
        },
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["staged"] is True

    ov = get_workshop_series_override(42)
    assert ov is not None
    assert ov["payload"]["summary"] == "Nouveau résumé draft"
    assert ov["cover_url"] == "https://example.com/draft.jpg"


def test_reset_workshop_clears_series_override(isolated_db):
    """reset_workshop avec chapter_id=None purge le brouillon de série."""
    api = DummyKavita()
    save_workshop_series_override(42, {"summary": "Brouillon"}, cover_url="https://example.com/c.jpg")
    assert get_workshop_series_override(42) is not None

    # Reset sur un seul chapitre ne doit pas purger la série
    reset_workshop(api, 42, chapter_id=10)
    assert get_workshop_series_override(42) is not None

    # Reset global purge la série
    reset_workshop(api, 42, chapter_id=None)
    assert get_workshop_series_override(42) is None


# ---------------------------------------------------------------------------
# Audit Anomalie 4 : Statut Global & Cache après « Envoyer la fiche »
# ---------------------------------------------------------------------------

def test_send_series_updates_status_and_closes_pending_reviews(isolated_db, monkeypatch):
    """send_series passe le statut à COMPLETED, purge la review pendante et vide l'override."""
    api = DummyKavita()
    update_status(42, "PENDING_REVIEW")
    park_pending_review(
        "rev-42",
        42,
        "Audit Series",
        candidates_json=[{"title": "C1"}],
    )
    assert any(r["series_id"] == 42 for r in list_pending_reviews())
    save_workshop_series_override(42, {"summary": "Résumé Final"})

    emitted_statuses = []

    def mock_emit_status(series_id, status, series_name=""):
        emitted_statuses.append((series_id, status, series_name))

    import services.enrichment_engine as engine
    monkeypatch.setattr(engine, "_emit_series_status", mock_emit_status)

    res = send_series(api, 42, edits={"summary": "Résumé Final"}, force=True)
    assert res["success"] is True
    assert "summary" in res["written"]

    # 1. Statut dans series_cache mis à jour en COMPLETED
    cached = get_all_cached_data()
    assert cached[42]["status"] == "COMPLETED"

    # 2. Review pendante clôturée/supprimée
    assert not any(r["series_id"] == 42 for r in list_pending_reviews())

    # 3. Événement WebSocket émis
    assert (42, "COMPLETED", "Audit Series") in emitted_statuses

    # 4. Brouillon de série supprimé
    assert get_workshop_series_override(42) is None


# ---------------------------------------------------------------------------
# Audit Anomalie 5 : Synchronisation des Identifiants Externes
# ---------------------------------------------------------------------------

def test_extract_external_ids_from_weblinks():
    """extract_external_ids_from_weblinks extrait proprement AniList, MAL et MangaBaka."""
    links = (
        "https://anilist.co/manga/1015/Monster/,\n"
        "https://myanimelist.net/manga/22/Death_Note,\n"
        "https://mangabaka.org/series/999-berserk"
    )
    a_id, m_id, mb_id = extract_external_ids_from_weblinks(links)
    assert a_id == 1015
    assert m_id == 22
    assert mb_id == 999

    # Test avec extra_ids prioritaire
    a2, m2, mb2 = extract_external_ids_from_weblinks("", extra_ids={"anilist": 444, "mal": "555"})
    assert a2 == 444
    assert m2 == 555
    assert mb2 is None


def test_send_series_syncs_external_ids(isolated_db):
    """send_series extrait les IDs externes et appelle update_series_external_ids sur Kavita."""
    api = DummyKavita()
    weblinks = "https://anilist.co/manga/777, https://myanimelist.net/manga/888"
    res = send_series(api, 42, edits={"webLinks": weblinks})
    assert res["success"] is True
    assert "webLinks" in res["written"]
    assert "externalIds" in res["written"]

    assert len(api.series_external_ids_calls) == 1
    sid, anilist_id, mal_id, mangabaka_id = api.series_external_ids_calls[0]
    assert sid == 42
    assert anilist_id == 777
    assert mal_id == 888
    assert mangabaka_id is None


# ---------------------------------------------------------------------------
# Audit Anomalie 6 : Sécurité XSS esc()
# ---------------------------------------------------------------------------

def test_esc_safely_encodes_all_special_characters():
    """Vérifie que la fonction esc() dans volumes.js échappe rigoureusement &, <, >, \", '."""
    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "volumes.js")
    with open(js_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert ".replace(/&/g, '&amp;')" in content
    assert ".replace(/</g, '&lt;')" in content
    assert ".replace(/>/g, '&gt;')" in content
    assert ".replace(/\"/g, '&quot;')" in content
    assert ".replace(/'/g, '&#39;')" in content


# ---------------------------------------------------------------------------
# Workshop Manual Review : Complétion Manuelle, Fusion & Suppression Phase Edit
# ---------------------------------------------------------------------------

@pytest.fixture
def mr_client(isolated_db):
    from flask import Flask
    from routes.manual_review import manual_review_bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"
    app.register_blueprint(manual_review_bp)
    return app.test_client()


def test_workshop_choice_bypasses_edit_phase_and_stages_directly(mr_client, isolated_db, mocker):
    """Dans l'atelier, /choice applique directement la review et ne renvoie jamais mode='preview'."""
    from kavita_api import KavitaAPI
    mocker.patch.object(KavitaAPI, "authenticate", return_value=False)
    candidates = {
        "above": [
            {
                "provider": "AniList",
                "score": 0.95,
                "data": {
                    "title": "AniList Title",
                    "summary": "AniList Summary",
                    "cover_url": "https://anilist.co/cover.jpg",
                    "genres": ["Action"],
                    "year": 2021,
                }
            }
        ],
        "below": []
    }
    park_pending_review("rev-ws-direct", 55, "Series Direct", candidates, state="awaiting_pick")

    resp = mr_client.post(
        "/api/manual-reviews/rev-ws-direct/choice",
        json={"base_provider": "AniList", "prefer_edit": False, "workshop": True}
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["mode"] == "applied"
    assert data["detail"]["workshop"] is True
    assert data["detail"]["series_id"] == 55
    assert data["detail"]["series_edits"]["releaseYear"] == "2021"

    override = get_workshop_series_override(55)
    assert override is not None
    assert override["payload"]["releaseYear"] == "2021"


def test_workshop_choice_preview_and_confirm_flow(mr_client, isolated_db, mocker):
    """Dans l'atelier, /choice avec prefer_edit=True passe par les bonnes étapes : mode='preview' puis /confirm applique le staging."""
    from kavita_api import KavitaAPI
    mocker.patch.object(KavitaAPI, "authenticate", return_value=False)
    candidates = {
        "above": [
            {
                "provider": "AniList",
                "score": 0.95,
                "data": {
                    "title": "AniList Title",
                    "summary": "AniList Summary",
                    "cover_url": "https://anilist.co/cover.jpg",
                    "genres": ["Action"],
                    "year": 2021,
                }
            }
        ],
        "below": []
    }
    park_pending_review("rev-ws-flow", 58, "Series Flow", candidates, state="awaiting_pick")

    # Étape 1 : /choice renvoie mode='preview'
    resp_choice = mr_client.post(
        "/api/manual-reviews/rev-ws-flow/choice",
        json={"base_provider": "AniList", "prefer_edit": True, "workshop": True}
    )
    assert resp_choice.status_code == 200
    data_choice = resp_choice.get_json()
    assert data_choice["success"] is True
    assert data_choice["mode"] == "preview"
    assert "preview" in data_choice
    assert data_choice["preview"]["year"] == 2021

    # Étape 2 : /confirm applique et stage dans l'atelier
    resp_confirm = mr_client.post(
        "/api/manual-reviews/rev-ws-flow/confirm",
        json={
            "base_provider": "AniList",
            "include_providers": [],
            "edited_fields": {"year": 2022, "summary": "Custom Summary"},
            "field_edits": 2,
            "workshop": True
        }
    )
    assert resp_confirm.status_code == 200
    data_confirm = resp_confirm.get_json()
    assert data_confirm["success"] is True
    assert data_confirm["detail"]["workshop"] is True
    assert data_confirm["detail"]["series_edits"]["releaseYear"] == "2022"

    override = get_workshop_series_override(58)
    assert override is not None
    assert override["payload"]["releaseYear"] == "2022"
    assert override["payload"]["summary"] == "Custom Summary"


def test_workshop_choice_with_manual_completion_field_picks(mr_client, isolated_db, mocker):
    """Dans l'atelier, /choice avec complétion manuelle et fusion des champs applique fidèlement les sélections."""
    from kavita_api import KavitaAPI
    mocker.patch.object(KavitaAPI, "authenticate", return_value=False)
    candidates = {
        "above": [
            {
                "provider": "AniList",
                "score": 0.95,
                "data": {
                    "title": "AniList Title",
                    "summary": "AniList Summary",
                    "cover_url": "https://anilist.co/cover.jpg",
                    "genres": ["Action"],
                    "year": 2021,
                }
            },
            {
                "provider": "MAL",
                "score": 0.85,
                "data": {
                    "title": "MAL Title",
                    "summary": "MAL Summary",
                    "cover_url": "https://mal.net/cover.jpg",
                    "genres": ["Comedy"],
                    "year": 2020,
                }
            }
        ],
        "below": []
    }
    park_pending_review("rev-ws-picks", 56, "Series Picks", candidates, state="awaiting_pick")

    resp = mr_client.post(
        "/api/manual-reviews/rev-ws-picks/choice",
        json={
            "base_provider": "AniList",
            "include_providers": ["MAL"],
            "prefer_edit": False,
            "manual_completion": True,
            "merge_fields": True,
            "field_picks": {
                "cover": ["MAL"],
                "summary": ["MAL"],
                "genres": ["AniList", "MAL"],
            },
            "workshop": True,
        }
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["mode"] == "applied"
    assert data["detail"]["workshop"] is True
    assert data["detail"]["cover_url"] == "https://mal.net/cover.jpg"
    assert "Action, Comedy" in data["detail"]["series_edits"]["genres"]

    override = get_workshop_series_override(56)
    assert override is not None
    assert "Action, Comedy" in override["payload"]["genres"]
    assert override["cover_url"] == "https://mal.net/cover.jpg"


def test_dashboard_choice_preserves_preview_edit_mode(mr_client, isolated_db, mocker):
    """Sur le dashboard de base (hors workshop), /choice avec prefer_edit renvoie bien mode='preview'."""
    mocker.patch("services.enrichment_engine.KavitaAPI")
    candidates = {
        "above": [
            {
                "provider": "AniList",
                "score": 0.95,
                "data": {
                    "title": "AniList Title",
                    "summary": "AniList Summary",
                    "genres": ["Action"],
                    "year": 2021,
                }
            }
        ],
        "below": []
    }
    park_pending_review("rev-dash-prev", 57, "Series Dash", candidates, state="awaiting_pick")

    resp = mr_client.post(
        "/api/manual-reviews/rev-dash-prev/choice",
        json={"base_provider": "AniList", "prefer_edit": True}
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["mode"] == "preview"
    assert "preview" in data


def test_js_manual_review_resets_and_workshop_prefer_edit():
    """Vérifie dans manual_review.js que les étapes de review fonctionnent dans l'atelier et que les resets sont présents."""
    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "manual_review.js")
    with open(js_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "prefer_edit: !!(editEnabled || coverPickEnabled)" in content
    assert "review.preview && (isAutoConfirmReview(review) || review.state === \"awaiting_confirm\")" in content
    assert "window.WORKSHOP_CONFIG" in content
    assert "resetFieldPicks();" in content
    assert "syncManualCompletionControls();" in content


def test_inscribed_from_chapter_filters_zero_date():
    """Vérifie que la date sentinelle 0001-01-01 de Kavita est vidée dans inscribed_from_chapter."""
    from services.workshop import inscribed_from_chapter
    chap_sentinel = {"id": 1, "releaseDate": "0001-01-01T00:00:00", "title": "Tome 1"}
    data = inscribed_from_chapter(chap_sentinel)
    assert data["release_date"] == ""

    chap_valid = {"id": 2, "releaseDate": "2023-05-12T00:00:00", "title": "Tome 2"}
    data_valid = inscribed_from_chapter(chap_valid)
    assert data_valid["release_date"] == "2023-05-12T00:00:00"


def test_begin_volume_review_with_explicit_isbn(mocker, isolated_db):
    """Vérifie que begin_volume_review prend en compte l'ISBN fourni explicitement."""
    from services.workshop import begin_volume_review
    dummy = DummyKavita()
    mock_fetch = mocker.patch("services.volume_enrichment.providers.fetch_by_isbn")
    mock_fetch.return_value = {
        10: {
            "title": "Hit By ISBN",
            "provider": "MockProvider",
            "isbn": "9782012345678",
            "summary": "Found via explicit ISBN",
        }
    }

    res = begin_volume_review(dummy, 1, 10, isbn="9782012345678")
    assert res["success"] is True
    assert len(res["candidates"]) == 1
    assert res["candidates"][0]["title"] == "Hit By ISBN"
    assert mock_fetch.called
    units_passed = mock_fetch.call_args[0][0]
    assert units_passed[0]["isbn"] == "9782012345678"


def test_workshop_review_route_propagates_isbn(monkeypatch, mocker, isolated_db):
    """Vérifie que la route /workshop/review relaie le paramètre isbn à begin_volume_review."""
    from flask import Flask
    from routes.workshop import workshop_bp

    monkeypatch.setattr("routes.workshop.workshop_enabled", lambda *a: True)
    monkeypatch.setattr("routes.workshop._guard_series", lambda *a: (DummyKavita().get_series(1), None))
    mock_begin = mocker.patch("routes.workshop.begin_volume_review")
    mock_begin.return_value = {"success": True, "candidates": []}
    mocker.patch("routes.workshop._api", return_value=DummyKavita())

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(workshop_bp)
    c = app.test_client()

    resp = c.post(
        "/api/series/1/workshop/review",
        json={"chapter_id": 10, "isbn": "9781234567890"}
    )
    assert resp.status_code == 200
    mock_begin.assert_called_once()
    assert mock_begin.call_args.kwargs["isbn"] == "9781234567890"


def test_js_workshop_audit_fixes_integrity():
    """Vérifie dans volumes.js l'application de tous les correctifs d'audit."""
    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "volumes.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    # 1.1 Contexte de tome et classes candidats
    assert "mrVolumeContextText" in js
    assert "workshop-candidate-cover" in js
    assert "workshop_vol_n" in js

    # 1.2 Dirty state sync et nettoyage send
    assert "function syncDirtyState()" in js
    assert "function refreshGlobalDirty()" in js
    assert "seriesCard.removeAttribute('data-dirty')" in js
    assert "card.removeAttribute('data-cover-url')" in js

    # 1.3 Sécurisation du timer de draft
    assert "if (String(seriesId) !== String(targetSid)) return;" in js
    assert "if (seriesDraftTimer) clearTimeout(seriesDraftTimer);" in js

    # 1.4 Décompte Plus de champs
    assert "updateMoreSummary(seriesMore);" in js
    assert "summary.textContent = moreSummaryText(filled, total);" in js

    # 2.1 Décompte supporter nag sur statut DONE
    assert "r && (r.status === 'DONE' || (r.success && !r.noop))" in js

    # 2.2 Filtrage date sentinelle dans JS
    assert "0001-01-01" in js

    # 2.3 Transmission de l'ISBN
    assert "isbn: visbn" in js

    # 2.4 Synchronisation rail et websocket series_status
    assert "function updateRailStatus(sid, newStatus)" in js
    assert "window.socket.on('series_status'" in js

    # 2.5 Libellé send-selection dans l'historique
    assert "'send-selection': T().workshop_send_selection" in js

    # 3.1 Entrée sur champ magique
    assert "magicInput.addEventListener('keydown'" in js

    # 3.2 licenseNagModal dans isTypingTarget
    assert "var nag = document.getElementById('licenseNagModal');" in js

    # 3.3 Vérification empty sur workshopSendAll
    assert "if (!items.length) {" in js

    # 3.4 Rechargement sur fin de passe concurrente
    assert "_lastPassWasRunning && String(st.series_id) === String(seriesId)" in js


# ===========================================================================
# BF194 : Tests de non-régression — Correction intégrale de l'Atelier
# ===========================================================================

@pytest.fixture
def workshop_client(monkeypatch, isolated_db):
    from flask import Flask
    from routes.workshop import workshop_bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"
    app.register_blueprint(workshop_bp)

    # Mock _api pour renvoyer une série valide et activer l'atelier
    monkeypatch.setattr("routes.workshop.workshop_enabled", lambda config=None: True)
    monkeypatch.setattr("routes.workshop._api", lambda: DummyKavita())
    return app.test_client()


def test_bf194_draft_series_preserves_external_ids(workshop_client, isolated_db):
    """Vérifie que l'auto-save draft-series préserve les _external_ids déjà stagés."""
    sid = 991
    initial_payload = {
        "summary": "Résumé initial",
        "_external_ids": {"anilist": 12345, "mal": 67890},
    }
    save_workshop_series_override(sid, initial_payload, cover_url="https://example.com/cover.jpg")

    # Appel draft-series sans _external_ids et sans cover_url
    res = workshop_client.post(
        f"/api/series/{sid}/workshop/draft-series",
        json={"edits": {"summary": "Résumé modifié par utilisateur"}, "cover_url": ""},
    )
    assert res.status_code == 200
    assert res.get_json()["success"] is True

    # Vérification en base : _external_ids et la jaquette existante sont préservés
    stored = get_workshop_series_override(sid)
    assert stored is not None
    assert stored["payload"]["summary"] == "Résumé modifié par utilisateur"
    assert stored["payload"]["_external_ids"] == {"anilist": 12345, "mal": 67890}
    assert stored["cover_url"] == "https://example.com/cover.jpg"


def test_bf194_fetch_by_isbn_and_title_sets_provider(monkeypatch):
    """Vérifie que fetch_by_isbn et fetch_by_title_volume injectent provider et provider_ref."""
    from scrapers import ScraperRegistry
    from services.volume_enrichment.providers import fetch_by_isbn, fetch_by_title_volume

    class DummyScraper:
        id = "DUMMY_PROVIDER"

        def fetch(self, query, **kwargs):
            return {
                "title": "Tome Test",
                "summary": "Résumé Test",
                "isbn": "9782000000001",
                "provider_ref": "https://dummy.org/book/1",
            }

        def fetch_volume(self, query, volume_number=None, **kwargs):
            return {
                "title": f"Tome {volume_number}",
                "summary": "Résumé Test",
                "provider_ref": f"https://dummy.org/vol/{volume_number}",
            }

    monkeypatch.setattr(ScraperRegistry, "get", lambda pid: DummyScraper())

    # 1. fetch_by_isbn
    units = [{"volume_number": 1, "isbn": "978-2-000-00000-1"}]
    res_isbn = fetch_by_isbn(units, provider_ids=["DUMMY_PROVIDER"])
    assert "1" in res_isbn
    assert res_isbn["1"]["provider"] == "DUMMY_PROVIDER"
    assert res_isbn["1"]["provider_ref"] == "https://dummy.org/book/1"

    # 2. fetch_by_title_volume
    res_tv = fetch_by_title_volume("Série Test", units, provider_ids=["DUMMY_PROVIDER"])
    assert "1" in res_tv
    assert res_tv["1"]["provider"] == "DUMMY_PROVIDER"
    assert res_tv["1"]["provider_ref"] == "https://dummy.org/vol/1"


def test_bf194_send_selection_records_sent_and_total(isolated_db, monkeypatch):
    """Vérifie que send_selection enregistre sent et total dans l'historique."""
    from services.workshop import send_selection, list_workshop_history

    api = DummyKavita()
    # DummyKavita chapters setup
    sid = 992
    items = [
        {"chapter_id": 10, "edits": {"title": "Tome 1"}},
        {"chapter_id": 11, "edits": {"title": "Tome 2"}},
    ]
    res = send_selection(api, sid, items, force=True)
    assert res["success"] is True

    hist = list_workshop_history(sid)
    selection_events = [h for h in hist if h.get("event") == "send-selection"]
    assert len(selection_events) > 0
    detail = selection_events[0].get("detail") or {}
    assert detail.get("sent") == 2
    assert detail.get("total") == 2
    assert detail.get("count") == 2


def test_bf194_frontend_safeguards_and_volume_modal():
    """Vérifie la présence de tous les correctifs BF194 dans le code JavaScript."""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root, "static", "js", "manual_review.js"), "r", encoding="utf-8") as f:
        mr_js = f.read()
    with open(os.path.join(root, "static", "js", "volumes.js"), "r", encoding="utf-8") as f:
        vol_js = f.read()

    # 1. Isolation de la modale manual review en mode volume
    assert 'if (!modal || modal.dataset.kind === "volume") return false;' in mr_js

    # 2. Raccourcis clavier modale volume dans volumes.js
    assert "volModal.dataset.kind === 'volume'" in vol_js
    assert "closeVolumeModal();" in vol_js
    assert "confirmVolumeReview();" in vol_js
    assert "var isStaged = !!(ov.payload && ov.payload._staged);" in vol_js
    assert "dirtyAttr +" in vol_js

    # 3. seriesIsDirty considère les overrides et jaquettes stagées
    assert "if ((s.override && Object.keys(s.override).length) || s.staged_cover_url) return true;" in vol_js

    # 4. Envoi unitaire avec markDoneClean et notification supporter
    assert "markDoneClean([data]);" in vol_js
    assert "window.SupporterNag.onWorkshopComplete({ series_count: 0, volumes_count: 1 });" in vol_js

    # 5. Gardes défensives sur seriesId
    assert "if (!card || !seriesId) return;" in vol_js
    assert "if (!seriesId) return;" in vol_js
    assert "if (!s || !s.id) return;" in vol_js


def test_c112_js_css_hardening():
    """Vérifie la robustesse du JS et du CSS suite à la refonte C112 de l'Atelier."""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root, "static", "js", "volumes.js"), "r", encoding="utf-8") as f:
        vol_js = f.read()
    with open(os.path.join(root, "static", "css", "volumes.css"), "r", encoding="utf-8") as f:
        vol_css = f.read()

    # 1. ROW_H à 48px aligné sur le scroll virtuel du rail
    assert "var ROW_H = 48;" in vol_js
    assert "height: 48px;" in vol_css

    # 2. isTypingTarget ne bloque pas les raccourcis dans la modale de review de tome
    assert "if (mr.dataset.kind === 'volume') return false;" in vol_js

    # 3. Sauvegarde automatique de brouillon lors du choix de jaquette de tome
    assert "scheduleVolumeDraft(coverPickTarget.card);" in vol_js

    # 4. display: none !important garanti sur les images [hidden]
    assert ".workshop-cover-well img[hidden]" in vol_css
    assert ".workshop-pass-banner[hidden] { display: none !important; }" in vol_css

    # 5. Dimensions valorisées des jaquettes (104px tomes, 136px séries) et responsive propre
    assert "20px 104px" in vol_css
    assert "repeat(6, minmax(0, 1fr));" in vol_css
    assert ".workshop-cover--volume {\n    width: 104px;\n}" in vol_css
    assert ".workshop-cover--series {\n    width: 136px;\n}" in vol_css
    assert ".workshop-volume-meta {\n        grid-column: 1 / -1;\n    }" in vol_css

def test_c113_series_to_volumes_cascade_and_modern_cards():
    """Vérifie la duplication série -> tomes et la modernisation des cartes de l'Atelier (C113)."""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root, "static", "js", "volumes.js"), "r", encoding="utf-8") as f:
        vol_js = f.read()
    with open(os.path.join(root, "static", "css", "volumes.css"), "r", encoding="utf-8") as f:
        vol_css = f.read()
    with open(os.path.join(root, "templates", "volumes.html"), "r", encoding="utf-8") as f:
        vol_html = f.read()
    with open(os.path.join(root, "templates", "partials", "_icons_sprite.html"), "r", encoding="utf-8") as f:
        icons_html = f.read()
    from translations import translations

    # 1. Présence des clés de cascade bilingues FR et EN en parité stricte
    cascade_keys = (
        "workshop_cascade_btn",
        "workshop_cascade_field_tip",
        "workshop_cascade_all",
        "workshop_cascade_all_tip",
        "workshop_cascade_success",
        "workshop_cascade_all_success",
        "workshop_cascade_empty_tip",
        "workshop_cascade_none_found",
    )
    for k in cascade_keys:
        assert k in translations["fr"], f"Clé manquante en FR: {k}"
        assert k in translations["en"], f"Clé manquante en EN: {k}"

    # 2. Bouton global et icône de cascade dans le template
    assert 'id="workshopCascadeAllBtn"' in vol_html
    assert 'mk-ico-cascade' in vol_html
    assert 'id="mk-ico-cascade"' in icons_html

    # 3. Mécanisme de duplication dans volumes.js
    assert "CASCADE_COMPATIBLE_FIELDS" in vol_js
    assert "cascadeFieldToVolumes" in vol_js
    assert "cascadeAllSeriesToVolumes" in vol_js
    assert "workshop-cascade-btn" in vol_js
    assert "data-cascade-key" in vol_js
    assert "workshopCascadeAllBtn" in vol_js

    # 4. Modernisation CSS inspirée de la Revue Manuelle
    assert ".workshop-cascade-btn" in vol_css
    assert "background: #141926;" in vol_css or "background-color: #141926;" in vol_css or "#141926" in vol_css
    assert "text-transform: none;" in vol_css
    assert ".workshop-status-chip" in vol_css
    assert ".workshop-status-chip--done" in vol_css
    assert ".workshop-status-chip--staged" in vol_css


def test_workshop_css_modular_architecture():
    """Vérifie l'architecture modulaire de volumes.css et l'intégrité des 14 modules."""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    manifest_path = os.path.join(root, "static", "css", "volumes.css")
    backup_path = os.path.join(root, "static", "css", "volumes.backup.css")
    workshop_css_dir = os.path.join(root, "static", "css", "workshop")

    # 1. Sauvegarde bit-à-bit présente
    assert os.path.isfile(backup_path)
    assert os.path.getsize(backup_path) > 30000

    # 2. volumes.css est un manifest @import lisible (lu en binaire pour contourner l'expansion conftest)
    with open(manifest_path, "rb") as f:
        raw_manifest = f.read().decode("utf-8")
    assert "@import url(" in raw_manifest
    assert len(raw_manifest.splitlines()) < 40

    # 3. Les 14 modules thématiques existent et sont importés
    expected_modules = (
        "_base.css",
        "_navbar.css",
        "_layout.css",
        "_rail.css",
        "_main.css",
        "_series-card.css",
        "_covers.css",
        "_forms.css",
        "_action-bar.css",
        "_volume-cards.css",
        "_candidates.css",
        "_logs.css",
        "_modals.css",
        "_responsive.css",
    )
    for mod in expected_modules:
        mod_path = os.path.join(workshop_css_dir, mod)
        assert os.path.isfile(mod_path), f"Module manquant : {mod}"
        assert f"workshop/{mod}" in raw_manifest, f"Module non importé : {mod}"
        with open(mod_path, "rb") as f:
            content = f.read().decode("utf-8")
        assert content.count("{") == content.count("}"), f"Accolades asymétriques dans {mod}"
