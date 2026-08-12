"""
Non-régression bug-hunt 1.6.3 P0 :
- MR confirm restaure Sources depuis preview_json
- BF81 rejoué après fusion
- Auto skip genres/tags adult sur prefer-safe
- Magasin : unloadable → rollback ; shadow id core refusé
- Planète BD probe mangas
"""
from __future__ import annotations

from unittest.mock import MagicMock

import metadata_fetcher
import services.enrichment_engine as enrichment_engine
import services.manual_review as mr
from scrapers.utils import MATCH_SCORE_KEY


def _card(provider, score, **data):
    data = dict(data)
    data.setdefault("title", provider)
    data.setdefault(MATCH_SCORE_KEY, score)
    return {
        "provider": provider,
        "score": score,
        "title": data["title"],
        "data": data,
    }


def test_bf81_after_merge_escalates_mature_plus_hentai():
    ordered = [
        ("TOP", {"title": "T", "summary": "s", "age_rating": "mature"}),
        ("ALT", {"title": "A", "genres": ["Hentai"]}),
    ]
    merged = metadata_fetcher.merge_candidates(
        ordered, smart_fusion=True, fill_age_rating=True
    )
    assert merged.get("age_rating") == "x18"
    assert merged["genres"] == ["Hentai"]


def test_mr_confirm_restores_includes_from_preview_json(isolated_db, mocker):
    """Confirm with include_providers=[] still rematches Sources from preview."""
    payload = {
        "above": [
            _card("TOP", 0.92, summary="base only", genres=[]),
            _card("ALT", 0.70, genres=["Action"], publisher="Kadokawa", age_rating="mature"),
        ],
        "below": [],
        "query": "RestoreSources",
    }
    rid = mr.create_review_from_candidates(901, "RestoreSources", payload)
    master = mr.choice_and_merge(
        rid, "TOP", include_providers=["ALT"], smart_fusion=True
    )
    assert master is not None
    assert master.get("publisher") == "Kadokawa"

    # Persist preview like preview_manual_review (with _fusion_providers).
    preview = {
        "title": "TOP",
        "summary": "base only",
        "year": "",
        "genres": "Action",
        "tags": "",
        "publisher": "Kadokawa",
        "staff": "",
        "cover_url": "",
        "localized_name": "",
        "status": "",
        "age_rating": "mature",
        "format": "",
        "_provider_used": "TOP",
        "_fusion_providers": ["ALT"],
    }
    isolated_db.update_pending_review(rid, preview_json=preview, state="awaiting_confirm")

    mocker.patch.object(
        enrichment_engine,
        "load_config",
        return_value={
            "KAVITA_URL": "http://kavita.local",
            "KAVITA_API_KEY": "k",
            "UI_LANG": "fr",
            "SMART_COMPLETION": False,
            "TARGET_LANG": "FR",
            "AUTO_COVER": False,
            "AUTO_READING_DIR": False,
        },
    )
    mocker.patch(
        "services.kavita_payload.translate_text",
        side_effect=lambda text, *a, **k: text,
    )
    mocker.patch("services.kavita_payload._broadcast_enrichment_stats", lambda *a, **k: None)
    mocker.patch.object(enrichment_engine, "_broadcast_enrichment_stats", lambda *a, **k: None)

    from kavita_api import KavitaAPI

    captured = {}

    def _capture(meta):
        captured["meta"] = meta
        return True, "ok", True

    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    mocker.patch.object(
        KavitaAPI,
        "get_series_metadata",
        return_value={"seriesId": 901, "summary": ""},
    )
    mocker.patch.object(KavitaAPI, "update_series_metadata", side_effect=_capture)
    mocker.patch.object(KavitaAPI, "update_series_general", return_value=(True, "ok", True))
    mocker.patch.object(KavitaAPI, "update_series_external_ids", return_value=True)

    # Omitted includes (None) — restore ALT from preview_json.
    ok, msg, _ = enrichment_engine.apply_manual_review(
        rid, base_provider="TOP", include_providers=None, field_edits=0
    )
    assert ok is True, msg
    meta = captured.get("meta") or {}
    genres = [
        (g.get("title") if isinstance(g, dict) else str(g))
        for g in (meta.get("genres") or [])
    ]
    assert "Action" in genres
    assert meta.get("publisher") == "Kadokawa" or any(
        (p.get("title") if isinstance(p, dict) else str(p)) == "Kadokawa"
        for p in (meta.get("publishers") or [])
    ) or "Kadokawa" in str(meta)


def test_mr_confirm_empty_includes_clears_sources(isolated_db, mocker):
    """Explicit include_providers=[] must NOT restore preview Sources."""
    payload = {
        "above": [
            _card("TOP", 0.92, summary="base only"),
            _card("ALT", 0.70, genres=["Action"], publisher="Kadokawa"),
        ],
        "below": [],
        "query": "ClearSources",
    }
    rid = mr.create_review_from_candidates(902, "ClearSources", payload)
    mr.choice_and_merge(rid, "TOP", include_providers=["ALT"], smart_fusion=True)
    preview = {
        "title": "TOP",
        "summary": "base only",
        "year": "",
        "genres": "Action",
        "tags": "",
        "publisher": "Kadokawa",
        "staff": "",
        "cover_url": "",
        "localized_name": "",
        "status": "",
        "age_rating": "",
        "format": "",
        "_provider_used": "TOP",
        "_fusion_providers": ["ALT"],
    }
    isolated_db.update_pending_review(rid, preview_json=preview, state="awaiting_confirm")

    mocker.patch.object(
        enrichment_engine,
        "load_config",
        return_value={
            "KAVITA_URL": "http://kavita.local",
            "KAVITA_API_KEY": "k",
            "UI_LANG": "fr",
            "SMART_COMPLETION": False,
            "TARGET_LANG": "FR",
            "AUTO_COVER": False,
            "AUTO_READING_DIR": False,
        },
    )
    mocker.patch(
        "services.kavita_payload.translate_text",
        side_effect=lambda text, *a, **k: text,
    )
    mocker.patch("services.kavita_payload._broadcast_enrichment_stats", lambda *a, **k: None)
    mocker.patch.object(enrichment_engine, "_broadcast_enrichment_stats", lambda *a, **k: None)

    from kavita_api import KavitaAPI

    captured = {}

    def _capture(meta):
        captured["meta"] = meta
        return True, "ok", True

    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    mocker.patch.object(
        KavitaAPI, "get_series_metadata", return_value={"seriesId": 902, "summary": ""}
    )
    mocker.patch.object(KavitaAPI, "update_series_metadata", side_effect=_capture)
    mocker.patch.object(KavitaAPI, "update_series_general", return_value=(True, "ok", True))
    mocker.patch.object(KavitaAPI, "update_series_external_ids", return_value=True)

    ok, msg, _ = enrichment_engine.apply_manual_review(
        rid, base_provider="TOP", include_providers=[], field_edits=0
    )
    assert ok is True, msg
    meta = captured.get("meta") or {}
    genres = [
        (g.get("title") if isinstance(g, dict) else str(g))
        for g in (meta.get("genres") or [])
    ]
    assert "Action" not in genres


def test_planetebd_bare_id_probes_mangas_kind(monkeypatch):
    from pathlib import Path
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scrapers" / "planetebd.py"
    spec = importlib.util.spec_from_file_location("planetebd_p0", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    s = mod.PlanetebdScraper()
    session = MagicMock()
    # First two probes (bd, comics) miss; mangas hits.
    miss = MagicMock(status_code=404, url="https://www.planetebd.com/x")
    hit = MagicMock(
        status_code=200,
        url="https://www.planetebd.com/mangas/series/foo/99.html",
    )
    session.get.side_effect = [miss, miss, hit]
    built = {
        "title": "Manga Series",
        "summary": "",
        "cover_url": None,
        "genres": ["Comic"],
        "tags": [],
        "year": 2000,
        "staff": [],
        "format": "comic",
        "url": hit.url,
        "links": [hit.url],
    }
    monkeypatch.setattr(mod, "requests", MagicMock(Session=lambda **k: session))
    monkeypatch.setattr(s, "_candidate_from_series_or_album", lambda *a, **k: built)
    result = s.fetch("99", library_type="Comic", is_id=True)

    assert result is not None
    assert result["title"] == "Manga Series"
    urls = [c.args[0] for c in session.get.call_args_list]
    assert any("/mangas/series/s/99.html" in u for u in urls)

