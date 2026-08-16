"""C87 — cases d'envoi sur Ajuster avant envoi (send_fields ∩ override série)."""
from __future__ import annotations

import os
import re

from models import SeriesOverride
from services.enrichment_engine import (
    ALL_TARGETED_FIELDS,
    MR_EDIT_SENDABLE_FIELDS,
    normalize_send_fields,
    resolve_mr_write_fields,
)
from translations import translations

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _read(rel):
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def test_normalize_send_fields_none_is_legacy():
    assert normalize_send_fields(None) is None
    assert normalize_send_fields("summary") == []
    assert normalize_send_fields([]) == []
    assert normalize_send_fields(["cover_url", "age_rating", "localized_name", "nope"]) == [
        "cover",
        "age",
        "alt_titles",
    ]


def test_resolve_mr_write_fields_omitted_matches_series_mask():
    assert resolve_mr_write_fields("ALL") == list(ALL_TARGETED_FIELDS)
    assert resolve_mr_write_fields("summary,cover") == ["summary", "cover"]


def test_resolve_mr_write_fields_intersects_sendable_keeps_hidden():
    # weblinks / language ne sont pas sur la fiche : le masque série les garde.
    assert resolve_mr_write_fields("ALL", []) == ["weblinks", "language"]
    assert resolve_mr_write_fields("ALL", ["summary", "tags"]) == [
        "summary",
        "tags",
        "weblinks",
        "language",
    ]
    assert resolve_mr_write_fields("summary,cover,tags", ["tags", "staff"]) == ["tags"]
    assert "staff" in MR_EDIT_SENDABLE_FIELDS


def test_apply_send_fields_skips_unchecked_and_blocks_cover(isolated_db, mocker):
    import services.enrichment_engine as enrichment_engine
    import services.manual_review as mr
    from scrapers.utils import MATCH_SCORE_KEY

    isolated_db.save_series_override(
        SeriesOverride(series_id=4101, targeted_fields="ALL"),
        purge_pending=False,
        status="PENDING_REVIEW",
    )
    rid = mr.create_review_from_candidates(
        4101,
        "SendMask",
        {
            "above": [
                {
                    "provider": "TOP",
                    "score": 0.9,
                    "title": "Master",
                    "cover_url": "http://cdn.example/c.jpg",
                    "data": {
                        "title": "Master",
                        MATCH_SCORE_KEY: 0.9,
                        "summary": "hello",
                        "tags": ["A", "B"],
                        "cover_url": "http://cdn.example/c.jpg",
                    },
                }
            ],
            "below": [],
            "query": "SendMask",
        },
    )
    mocker.patch.object(
        enrichment_engine,
        "load_config",
        return_value={
            "KAVITA_URL": "http://kavita.local",
            "KAVITA_API_KEY": "k",
            "UI_LANG": "fr",
            "SMART_COMPLETION": False,
            "TARGET_LANG": "FR",
            "AUTO_COVER": True,
            "AUTO_READING_DIR": False,
        },
    )
    mocker.patch("services.kavita_payload.translate_text", side_effect=lambda text, *a, **k: text)
    mocker.patch.object(enrichment_engine, "_broadcast_enrichment_stats", lambda *a, **k: None)

    from kavita_api import KavitaAPI

    captured = {}

    def _capture(meta):
        captured["meta"] = meta
        return True, "ok", True

    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    mocker.patch.object(
        KavitaAPI, "get_series_metadata", return_value={"seriesId": 4101, "summary": "old"}
    )
    mocker.patch.object(KavitaAPI, "update_series_metadata", side_effect=_capture)
    mocker.patch.object(KavitaAPI, "update_series_general", return_value=(True, "ok", True))
    mocker.patch.object(KavitaAPI, "update_series_external_ids", return_value=True)
    upload = mocker.patch.object(KavitaAPI, "upload_series_cover", return_value=(True, "ok"))

    ok, msg, _detail = enrichment_engine.apply_manual_review(
        rid,
        base_provider="TOP",
        send_fields=["summary"],
        force_cover_upload=True,
        edited_preview={"cover_url": "http://cdn.example/picked.jpg"},
    )
    assert ok is True, msg
    assert (captured.get("meta") or {}).get("summary") == "hello"
    assert "tags" not in (captured.get("meta") or {})
    upload.assert_not_called()


def test_apply_without_send_fields_keeps_legacy_write(isolated_db, mocker):
    import services.enrichment_engine as enrichment_engine
    import services.manual_review as mr
    from scrapers.utils import MATCH_SCORE_KEY

    rid = mr.create_review_from_candidates(
        4102,
        "LegacySend",
        {
            "above": [
                {
                    "provider": "TOP",
                    "score": 0.9,
                    "title": "Master",
                    "data": {
                        "title": "Master",
                        MATCH_SCORE_KEY: 0.9,
                        "summary": "hello",
                        "tags": ["A"],
                    },
                }
            ],
            "below": [],
            "query": "LegacySend",
        },
    )
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
    mocker.patch("services.kavita_payload.translate_text", side_effect=lambda text, *a, **k: text)
    mocker.patch.object(enrichment_engine, "_broadcast_enrichment_stats", lambda *a, **k: None)

    from kavita_api import KavitaAPI

    captured = {}
    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    mocker.patch.object(
        KavitaAPI, "get_series_metadata", return_value={"seriesId": 4102, "summary": ""}
    )
    mocker.patch.object(
        KavitaAPI,
        "update_series_metadata",
        side_effect=lambda meta: captured.update(meta=meta) or (True, "ok", True),
    )
    mocker.patch.object(KavitaAPI, "update_series_general", return_value=(True, "ok", True))
    mocker.patch.object(KavitaAPI, "update_series_external_ids", return_value=True)

    ok, msg, _ = enrichment_engine.apply_manual_review(rid, base_provider="TOP")
    assert ok is True, msg
    assert (captured.get("meta") or {}).get("summary") == "hello"
    assert (captured.get("meta") or {}).get("tags")


def test_preview_exposes_series_active_fields(isolated_db, mocker):
    import services.enrichment_engine as enrichment_engine
    import services.manual_review as mr
    from scrapers.utils import MATCH_SCORE_KEY

    isolated_db.save_series_override(
        SeriesOverride(series_id=4103, targeted_fields="summary,cover"),
        purge_pending=False,
        status="PENDING_REVIEW",
    )
    rid = mr.create_review_from_candidates(
        4103,
        "MaskPreview",
        {
            "above": [
                {
                    "provider": "TOP",
                    "score": 0.9,
                    "title": "Master",
                    "data": {"title": "Master", MATCH_SCORE_KEY: 0.9, "summary": "s"},
                }
            ],
            "below": [],
            "query": "MaskPreview",
        },
    )
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
    mocker.patch("services.kavita_payload.translate_text", side_effect=lambda text, *a, **k: text)
    from kavita_api import KavitaAPI

    mocker.patch.object(KavitaAPI, "authenticate", return_value=True)
    mocker.patch.object(
        KavitaAPI, "get_series_metadata", return_value={"seriesId": 4103, "summary": ""}
    )

    ok, preview, _ = enrichment_engine.preview_manual_review(rid, "TOP")
    assert ok is True
    assert preview.get("_active_fields") == ["summary", "cover"]


def test_parse_send_fields_omitted_vs_list():
    from routes.manual_review import _parse_send_fields

    assert _parse_send_fields({}) is None
    assert _parse_send_fields({"send_fields": ["summary", "cover"]}) == ["summary", "cover"]
    assert _parse_send_fields({"send_fields": []}) == []
    assert _parse_send_fields({"send_fields": "summary"}) == []


def test_frontend_edit_send_contract():
    js = _read("static/js/manual_review.js")
    modal = _read("templates/partials/_manual_review_modal.html")
    assert "function collectSendFields" in js
    assert "data-mr-send" in js
    assert "send_fields" in js
    assert "mr_edit_never_writable" in js
    assert "is-display-only" in js
    assert "Tableau vide = override NONE" in js
    assert 'class="mr-edit-send-hint"' in modal
    for key in (
        "mr_edit_send_hint",
        "mr_edit_send",
        "mr_edit_send_title",
        "mr_edit_send_locked",
        "mr_edit_never_writable",
    ):
        assert translations["fr"].get(key), key
        assert translations["en"].get(key), key
        assert re.search(rf"^\s*{key}:", _read("templates/index.html"), re.M), key
