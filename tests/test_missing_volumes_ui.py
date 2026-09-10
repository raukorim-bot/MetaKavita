# tests/test_missing_volumes_ui.py
"""Tests pour la modale des tomes manquants : recherche instantanée, filtres de parution,
tri des colonnes, bouton Atelier et exclusion réversible (Partie 3 / C114).
"""
from flask import Flask
from pathlib import Path
from translations import translations


def test_missing_volumes_modal_template_markup():
    """Vérifie la présence de la barre d'outils, du champ de recherche et des filtres dans le gabarit."""
    tmpl_path = Path(__file__).resolve().parent.parent / "templates" / "partials" / "_library_audit_modal.html"
    content = tmpl_path.read_text(encoding="utf-8")

    assert 'id="missingVolumesModal"' in content
    assert 'id="missingFilterBar"' in content
    assert 'id="missingSearchInput"' in content
    assert 'class="audit-missing-status-filters"' in content
    assert 'data-filter="all"' in content
    assert 'data-filter="finished"' in content
    assert 'data-filter="ongoing"' in content
    assert 'id="missingFilterCountBadge"' in content
    assert 'id="missingVolumesBody"' in content


def test_missing_volumes_translations_parity():
    """Vérifie la parité stricte FR/EN de toutes les clés relatives aux manquants et à l'exclusion."""
    fr = translations["fr"]
    en = translations["en"]

    expected_keys = [
        "audit_quick_reinclude",
        "audit_quick_reinclude_title",
        "audit_quick_exclude_success",
        "audit_quick_reinclude_success",
        "audit_missing_search_placeholder",
        "audit_missing_filter_status",
        "audit_missing_filter_all",
        "audit_missing_filter_finished",
        "audit_missing_filter_finished_hint",
        "audit_missing_filter_ongoing",
        "audit_missing_filtered_empty",
        "audit_missing_sort_title",
        "audit_missing_sort_badge",
        "audit_missing_sort_pub",
        "audit_missing_sort_missing",
    ]

    for key in expected_keys:
        assert key in fr, f"Missing FR key: {key}"
        assert key in en, f"Missing EN key: {key}"
        assert len(fr[key].strip()) > 0, f"Empty FR key: {key}"
        assert len(en[key].strip()) > 0, f"Empty EN key: {key}"

    # Parité globale
    assert set(fr.keys()) == set(en.keys())


def test_missing_volumes_css_rules():
    """Vérifie que les classes CSS requises pour la modale des manquants sont définies."""
    css_path = Path(__file__).resolve().parent.parent / "static" / "css" / "modals" / "_modal-inventory.css"
    content = css_path.read_text(encoding="utf-8")

    assert ".audit-missing-filter-bar" in content
    assert ".audit-missing-search-wrap" in content
    assert ".audit-missing-status-filters" in content
    assert ".audit-missing-count-badge" in content
    assert ".audit-table thead th.sortable" in content
    assert ".btn-opt.btn-opt-workshop" in content
    assert ".audit-table tr.is-excluded" in content
    assert ".audit-quick-reinclude" in content


def test_missing_volumes_javascript_logic():
    """Vérifie que library_audit.js intègre les fonctions et variables de filtrage et tri."""
    js_path = Path(__file__).resolve().parent.parent / "static" / "js" / "library_audit.js"
    content = js_path.read_text(encoding="utf-8")

    assert "_missingState" in content
    assert "_bindMissingFilterBar" in content
    assert "_renderMissingFilteredRows" in content
    assert "_bindQuickExcludeButton" in content
    assert "btn-opt-workshop" in content
    assert "audit-quick-reinclude" in content
    assert "window._missingState = _missingState;" in content
    assert "window._renderMissingFilteredRows = _renderMissingFilteredRows;" in content


def test_series_inventory_exclude_reversible_route(isolated_db, monkeypatch):
    """Vérifie le cycle complet exclusion -> réinclusion réactive via l'API."""
    from db_manager import (
        init_db,
        save_volume_report_cache,
        set_inventory_excluded,
        get_inventory_excluded_ids,
        set_hygiene_library_meta,
        get_hygiene_library_meta,
    )
    from routes.library_audit import library_audit_bp

    init_db()

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(library_audit_bp)

    class FakeAPI:
        def __init__(self, *a, **k):
            pass
        def get_series(self, sid):
            return {"id": sid, "name": "Reversible Series", "libraryId": 1, "libraryType": "Manga"}
        def get_all_series(self, library_id=None):
            return [{"id": 77, "name": "Reversible Series", "libraryId": 1}]

    monkeypatch.setattr("routes.library_audit.KavitaAPI", FakeAPI)
    monkeypatch.setattr(
        "routes.library_audit.load_config",
        lambda: {"UI_LANG": "fr", "KAVITA_URL": "http://x", "KAVITA_API_KEY": "k"},
    )

    set_inventory_excluded(77, False)
    save_volume_report_cache(77, {
        "series_id": 77,
        "library_id": 1,
        "series_name": "Reversible Series",
        "stats": {"primary_count": 2},
        "catalog": {"status": "ok", "expected": 5},
        "missing_volumes": [3, 4, 5],
    })
    set_hygiene_library_meta("1", {"missing": 1, "excluded": 0, "series": 1})
    set_hygiene_library_meta("all", {"missing": 1, "excluded": 0, "series": 1})

    client = app.test_client()

    # 1. Exclusion rapide
    res1 = client.post("/api/series/77/inventory-exclude", json={"excluded": True})
    assert res1.status_code == 200
    assert res1.json["success"] is True
    assert res1.json["excluded"] is True
    assert 77 in get_inventory_excluded_ids()

    m1_after_ex = get_hygiene_library_meta("1")
    assert m1_after_ex["counts"]["excluded"] == 1
    assert m1_after_ex["counts"]["missing"] == 0

    # 2. Réinclusion rapide (reversible)
    save_volume_report_cache(77, {
        "series_id": 77,
        "library_id": 1,
        "series_name": "Reversible Series",
        "stats": {"primary_count": 2},
        "catalog": {"status": "ok", "expected": 5},
        "missing_volumes": [3, 4, 5],
    })
    res2 = client.post("/api/series/77/inventory-exclude", json={"excluded": False})
    assert res2.status_code == 200
    assert res2.json["success"] is True
    assert res2.json["excluded"] is False
    assert 77 not in get_inventory_excluded_ids()

    m1_after_reinc = get_hygiene_library_meta("1")
    assert m1_after_reinc["counts"]["excluded"] == 0
    assert m1_after_reinc["counts"]["missing"] == 1


def test_health_bar_interactivity_and_filters():
    """Vérifie le balisage interactif de la barre de santé, des puces et les gestionnaires JS (Partie 4)."""
    toolbar_path = Path(__file__).resolve().parent.parent / "templates" / "partials" / "_toolbar.html"
    toolbar_content = toolbar_path.read_text(encoding="utf-8")

    assert "applyHygieneFilter('HEALTHY')" in toolbar_content
    assert "applyHygieneFilter('INCOMPLETE')" in toolbar_content
    assert "applyHygieneFilter('UNKNOWN_EXPECTED')" in toolbar_content
    assert 'data-hygiene="EXCLUDED"' in toolbar_content
    assert 'id="auditChipExcluded"' in toolbar_content
    assert 'id="hygieneCountExcluded"' in toolbar_content

    css_path = Path(__file__).resolve().parent.parent / "static" / "css" / "components" / "_inventory-badge.css"
    css_content = css_path.read_text(encoding="utf-8")
    assert ".hh-seg.is-active" in css_content
    assert ".hh-key.is-active" in css_content

    batch_path = Path(__file__).resolve().parent.parent / "static" / "js" / "batch.js"
    batch_content = batch_path.read_text(encoding="utf-8")
    assert "window.hygieneFilter === 'HEALTHY'" in batch_content
    assert "window.hygieneFilter === 'INCOMPLETE'" in batch_content
    assert "window.hygieneFilter === 'UNKNOWN_EXPECTED'" in batch_content
    assert "window.hygieneFilter === 'EXCLUDED'" in batch_content

    series_path = Path(__file__).resolve().parent.parent / "static" / "js" / "series_list.js"
    series_content = series_path.read_text(encoding="utf-8")
    assert "hygiene === 'HEALTHY'" in series_content
    assert "hygiene === 'INCOMPLETE'" in series_content
    assert "hygiene === 'UNKNOWN_EXPECTED'" in series_content
    assert "hygiene === 'EXCLUDED'" in series_content

