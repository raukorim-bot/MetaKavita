"""
Inventaire : la barre de santé doit rendre compte des séries non analysées.

Une série dont l'analyse échoue (Kavita momentanément indisponible) n'écrit plus
ni flag ni verdict depuis BF127 — mais elle n'entrait alors dans aucun segment :
`healthy + incomplete + unknown_expected` ne totalisait plus le nombre de séries
annoncé par la barre, et rien à l'écran n'expliquait le trou. Le compteur des
séries non analysées est désormais publié avec les autres et dessiné comme un
segment à part.
"""

from __future__ import annotations

import os
import re

import pytest

from services.library_audit import hygiene_scan as hs

_JS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "static", "js", "library_audit.js")
)
_TOOLBAR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "templates", "partials", "_toolbar.html")
)


class _FakeKavita:
    """Trois séries : la troisième fait échouer la lecture des métadonnées."""

    def __init__(self, *args, **kwargs):
        pass

    def get_all_series(self, library_id=None):
        return [
            {"id": 1, "name": "Berserk"},
            {"id": 2, "name": "Pluto"},
            {"id": 3, "name": "Vinland Saga"},
        ]

    def get_library_type_for_series(self, series_id):
        return "Manga"

    def get_series_metadata(self, series_id):
        if int(series_id) == 3:
            raise RuntimeError("Kavita 503")
        return {"summary": "résumé"}

    def get_series_volumes(self, series_id):
        return []


@pytest.fixture
def scan_env(monkeypatch):
    """Isole `_run_scan` : ni réseau Kavita, ni base, ni socket."""
    saved = {}

    monkeypatch.setattr(hs, "KavitaAPI", _FakeKavita)
    monkeypatch.setattr(hs, "load_config", lambda: {})
    monkeypatch.setattr(hs, "get_all_cached_data", lambda: {})
    monkeypatch.setattr(hs, "get_inventory_excluded_ids", lambda: set())
    monkeypatch.setattr(hs, "merge_series_identity", lambda *a, **k: {"ids": {"anilist": "1"}})
    monkeypatch.setattr(hs, "identity_has_external_id", lambda identity: True)
    monkeypatch.setattr(
        hs,
        "build_volume_report",
        lambda *a, **k: {
            "badge": "3/3",
            "completion": {"state": "complete", "missing_count": 0},
            "unit_mode": "volumes",
            "publication_status": "FINISHED",
            "stats": {"primary_count": 3},
        },
    )
    monkeypatch.setattr(hs, "save_volume_report_cache", lambda *a, **k: None)
    monkeypatch.setattr(hs, "get_volume_report_cache", lambda sid: None)
    monkeypatch.setattr(hs, "get_catalog_expected_override", lambda sid: None)
    monkeypatch.setattr(hs, "apply_catalog_override", lambda catalog, override: catalog)
    monkeypatch.setattr(hs, "list_dismissed_group_keys", lambda library_id: [])
    monkeypatch.setattr(hs, "get_dup_accept_threshold", lambda config: 0.8)
    monkeypatch.setattr(hs, "cluster_duplicate_series", lambda *a, **k: [])
    monkeypatch.setattr(hs, "save_duplicate_groups_cache", lambda *a, **k: None)
    monkeypatch.setattr(hs, "set_series_external_id_flags", lambda flags: None)
    monkeypatch.setattr(hs, "_emit_progress", lambda payload: None)
    monkeypatch.setattr(
        hs,
        "set_hygiene_library_meta",
        lambda library_id, counts: saved.update(counts),
    )

    for key, value in (("done", 0), ("total", 0), ("cancelled", False), ("running", True)):
        monkeypatch.setitem(hs._state, key, value)

    return saved


def test_les_segments_totalisent_les_series_analysees(scan_env):
    hs._run_scan("1", [], False, "full")

    counts = scan_env
    segments = (
        counts["healthy"]
        + counts["incomplete"]
        + counts["unknown_expected"]
        + counts.get("failed", 0)
    )
    assert counts["failed"] == 1, "la série en échec n'est comptée nulle part"
    assert segments == counts["series"], (
        "les segments de la barre de santé ne totalisent pas les séries "
        f"annoncées ({segments} contre {counts['series']})"
    )


def test_la_barre_dessine_les_series_non_analysees():
    """Sans segment ni libellé, le compteur backend ne servirait à rien."""
    with open(_JS, encoding="utf-8") as fh:
        js = fh.read()
    with open(_TOOLBAR, encoding="utf-8") as fh:
        html = fh.read()

    assert "counts.failed" in js, "le rendu de la barre ignore les séries non analysées"
    assert re.search(r"seg\(\s*'failed'", js)
    assert "hygieneHealthFailed" in js
    assert 'data-seg="failed"' in html
    assert 'id="hygieneHealthFailed"' in html


def test_les_libelles_de_la_barre_existent_dans_les_deux_langues():
    from translations import translations

    for lang in ("fr", "en"):
        assert translations[lang]["audit_health_failed"]
