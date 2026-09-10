"""Tests unitaires pour le recalcul dynamique du seuil des doublons (Partie 2 / C114)."""

from __future__ import annotations

from pathlib import Path
from flask import Flask

from db_manager import (
    clean_orphaned_cache,
    get_duplicate_groups_cache,
    get_hygiene_library_meta,
    get_hygiene_series_identities,
    purge_series_hygiene_cache,
    save_dup_dismissal,
    save_duplicate_groups_cache,
    save_hygiene_series_identities,
    set_hygiene_library_meta,
)
from routes.library_audit import library_audit_bp
from services.library_audit.duplicates import (
    recluster_library_duplicates,
)
import translations


def test_hygiene_series_identities_crud(isolated_db):
    """Vérifie la persistance SQLite des identités de séries d'hygiène."""
    identities = [
        {
            "id": 10,
            "name": "Berserk",
            "libraryId": 1,
            "volume_count": 41,
            "chapter_count": 364,
            "ids": {"anilist": "30002"},
        },
        {
            "id": 11,
            "name": "Berserk (Max)",
            "libraryId": 1,
            "volume_count": 20,
            "chapter_count": 360,
            "ids": {"anilist": "30002"},
        },
        {
            "id": 20,
            "name": "Naruto",
            "libraryId": 2,
            "volume_count": 72,
            "chapter_count": 700,
            "ids": {"anilist": "30011"},
        },
    ]
    save_hygiene_series_identities(identities)

    # Récupération filtrée par bibliothèque
    lib1_items = get_hygiene_series_identities(1)
    assert len(lib1_items) == 2
    assert {x["id"] for x in lib1_items} == {10, 11}

    lib2_items = get_hygiene_series_identities("2")
    assert len(lib2_items) == 1
    assert lib2_items[0]["id"] == 20

    # Récupération globale
    all_items = get_hygiene_series_identities("all")
    assert len(all_items) == 3

    # Purge unitaire
    purge_series_hygiene_cache(20)
    assert len(get_hygiene_series_identities("2")) == 0
    assert len(get_hygiene_series_identities("all")) == 2

    # Purge orphelins : 10 reste actif, 11 devient orphelin
    clean_orphaned_cache({10})
    remaining = get_hygiene_series_identities("all")
    assert len(remaining) == 1
    assert remaining[0]["id"] == 10


def test_recluster_library_duplicates_logic(isolated_db):
    """Vérifie le re-clustering instantané en mémoire à différents seuils."""
    # Deux séries aux titres distincts ('Atlas boreal' vs 'Atlas boreale' -> score 0.71)
    identities = [
        {
            "id": 101,
            "name": "Atlas boreal",
            "libraryId": 3,
            "volume_count": 5,
            "chapter_count": 20,
            "folder_path": "/manga/Atlas",
            "ids": {},
        },
        {
            "id": 102,
            "name": "Atlas boreale",
            "libraryId": 3,
            "volume_count": 5,
            "chapter_count": 20,
            "folder_path": "/manga/Atlas Boreale",
            "ids": {},
        },
    ]
    save_hygiene_series_identities(identities)
    # Marquer la bibliothèque comme ayant été scannée
    save_duplicate_groups_cache(3, [])
    set_hygiene_library_meta(3, {"duplicates": 0, "missing": 0})

    # Au seuil par défaut 0.92 : aucun doublon trouvé (score 0.71 < 0.92)
    default_groups = recluster_library_duplicates(3, 0.92)
    assert len(default_groups) == 0
    meta = get_hygiene_library_meta(3)
    assert meta["counts"]["duplicates"] == 0

    # Au seuil élargi 0.70 : les deux séries sont regroupées en doublon (score 0.71 > 0.70)
    soft_groups = recluster_library_duplicates(3, 0.70)
    assert len(soft_groups) == 1
    assert set(soft_groups[0]["series_ids"]) == {101, 102}

    # Le cache de doublons et le compteur d'hygiène ont été mis à jour
    cached = get_duplicate_groups_cache(3)
    assert len(cached) == 1
    meta = get_hygiene_library_meta(3)
    assert meta["counts"]["duplicates"] == 1


def test_recluster_respects_dismissals(isolated_db):
    """Vérifie que les groupes archivés ou ignorés restent écartés lors du re-clustering."""
    identities = [
        {"id": 201, "name": "Claymore", "libraryId": 4, "ids": {"anilist": "30583"}},
        {"id": 202, "name": "Claymore Digital", "libraryId": 4, "ids": {"anilist": "30583"}},
    ]
    save_hygiene_series_identities(identities)
    save_duplicate_groups_cache(4, [])
    set_hygiene_library_meta(4, {"duplicates": 0})

    # Avant exclusion : 1 doublon
    groups = recluster_library_duplicates(4, 0.92)
    assert len(groups) == 1

    # Ignorer le doublon
    save_dup_dismissal(4, [201, 202], "ignored")

    # Recluster : le groupe doit être exclu
    groups_after = recluster_library_duplicates(4, 0.92)
    assert len(groups_after) == 0


def test_recluster_route_404_when_never_scanned(isolated_db, monkeypatch):
    """La route renvoie 404 si la bibliothèque n'a jamais été analysée."""
    app = Flask(__name__)
    app.register_blueprint(library_audit_bp)
    monkeypatch.setattr(
        "routes.library_audit.load_config",
        lambda: {"UI_LANG": "fr", "KAVITA_URL": "http://k", "KAVITA_API_KEY": "x"},
    )
    client = app.test_client()
    res = client.post(
        "/api/libraries/999/duplicates/recluster",
        json={"threshold": 0.85},
    )
    assert res.status_code == 404
    data = res.get_json()
    assert data["success"] is False


def test_recluster_route_success(isolated_db, monkeypatch, tmp_path):
    """La route recluste en mémoire, sauvegarde la configuration et renvoie les groupes."""
    cfg_saved = {}

    def fake_save_config(c):
        cfg_saved.update(c)
        return True

    monkeypatch.setattr(
        "routes.library_audit.load_config",
        lambda: {"UI_LANG": "fr", "KAVITA_URL": "http://k", "KAVITA_API_KEY": "x", "DUP_ACCEPT_THRESHOLD": 0.92},
    )
    monkeypatch.setattr("routes.library_audit.save_config", fake_save_config)

    identities = [
        {"id": 301, "name": "One Piece", "libraryId": 5, "ids": {"mal": "13"}},
        {"id": 302, "name": "One Piece Color", "libraryId": 5, "ids": {"mal": "13"}},
    ]
    save_hygiene_series_identities(identities)
    save_duplicate_groups_cache(5, [])
    set_hygiene_library_meta(5, {"duplicates": 0})

    app = Flask(__name__)
    app.register_blueprint(library_audit_bp)
    client = app.test_client()

    res = client.post(
        "/api/libraries/5/duplicates/recluster",
        json={"threshold": 0.85},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["count"] == 1
    assert len(data["groups"]) == 1
    assert set(data["groups"][0]["series_ids"]) == {301, 302}
    assert cfg_saved.get("DUP_ACCEPT_THRESHOLD") == 0.85
    assert cfg_saved.get("DUP_THRESHOLD_CUSTOM") is True


def test_recluster_frontend_js_and_i18n():
    """Vérifie la présence des bindings JavaScript et des traductions bilingues."""
    js_content = Path("static/js/library_audit.js").read_text(encoding="utf-8")
    assert "_reclusterDuplicates" in js_content
    assert "/duplicates/recluster" in js_content
    assert "setDupThresholdPreset" in js_content
    assert "dataset.boundRecluster" in js_content

    # Vérification des clés bilingues
    assert "audit_dup_reclustering" in translations.translations["fr"]
    assert "audit_dup_reclustering" in translations.translations["en"]
    assert "audit_dup_recluster_success" in translations.translations["fr"]
    assert "audit_dup_recluster_success" in translations.translations["en"]
    assert "audit_dup_preset_rescan" in translations.translations["fr"]
    assert "Recalcul instantané" in translations.translations["fr"]["audit_dup_preset_rescan"]
    assert "Instant re-clustering" in translations.translations["en"]["audit_dup_preset_rescan"]
