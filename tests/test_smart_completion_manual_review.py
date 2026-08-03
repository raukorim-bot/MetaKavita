"""
Contrat SMART_COMPLETION × Manual Review.

SMART_COMPLETION (sidebar) = fusion Auto cascade uniquement.
MR park = cartes brutes ; MR accept = cases Source ; bulk-accept = TOP1 seul.
Auto SMART_COMPLETION : age_rating non-adult comblé (BF102) ; NSFW bloqué.
MR Sources cochées : age_rating peut se combler (max info, tout âge).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import metadata_fetcher
import routes.manual_review as mr_routes
import services.enrichment_engine as enrichment_engine
import services.manual_review as mr
from flask import Flask
from routes.manual_review import manual_review_bp
from scrapers.utils import MATCH_SCORE_KEY


def _client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(manual_review_bp)
    return app.test_client()


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


def test_return_candidates_ignores_smart_completion_flag(monkeypatch):
    """Park path: return_candidates=True ne fusionne jamais les cartes."""
    scrapers = {
        "A": SimpleNamespace(
            id="A",
            supported_types={"Manga"},
            rate_limit=0.0,
            extract_id_from_url=lambda url: None,
            fetch=lambda *a, **k: {
                "title": "Master",
                "summary": "from A",
                MATCH_SCORE_KEY: 0.95,
            },
        ),
        "B": SimpleNamespace(
            id="B",
            supported_types={"Manga"},
            rate_limit=0.0,
            extract_id_from_url=lambda url: None,
            fetch=lambda *a, **k: {
                "title": "Alt",
                "genres": ["Action"],
                "publisher": "Pub",
                MATCH_SCORE_KEY: 0.80,
            },
        ),
    }
    monkeypatch.setattr(metadata_fetcher, "LAST_REQUEST_TIMES", {})
    monkeypatch.setattr(metadata_fetcher, "_THROTTLE_LOCKS", {})
    monkeypatch.setattr(
        metadata_fetcher,
        "load_config",
        lambda: {"UI_LANG": "en", "SMART_SCORING": True, "SMART_COMPLETION": True},
    )
    monkeypatch.setattr(
        metadata_fetcher,
        "ScraperRegistry",
        SimpleNamespace(get=lambda sid: scrapers.get(sid)),
    )

    result, _ = metadata_fetcher.fetch_metadata(
        query="Q",
        providers_list=["A", "B"],
        smart_fusion=True,
        library_type="Manga",
        existing_metadata={},
        return_candidates=True,
    )
    assert isinstance(result, dict)
    assert "above" in result
    # Pas un payload fusionné unique : des cartes séparées
    providers = [c["provider"] for c in result["above"]]
    assert providers == ["A", "B"] or set(providers) == {"A", "B"}
    by = {c["provider"]: c["data"] for c in result["above"]}
    assert by["A"].get("genres") in (None, [], ())
    assert "Action" not in (by["A"].get("genres") or [])
    assert by["B"].get("genres") == ["Action"]
    assert not by["A"].get("publisher")


def test_choice_and_merge_sources_fill_holes_including_age(isolated_db):
    """Sources cochées ⇒ genres + age_rating comblés (choix explicite MR)."""
    payload = {
        "above": [
            _card("TOP", 0.92, summary="base", age_rating=""),
            _card(
                "ALT",
                0.70,
                genres=["Action"],
                age_rating="mature",
                publisher="Kadokawa",
            ),
        ],
        "below": [],
        "query": "q",
    }
    rid = mr.create_review_from_candidates(301, "AgeHole", payload)
    master = mr.choice_and_merge(
        rid, "TOP", include_providers=["ALT"], smart_fusion=True
    )
    assert master is not None
    assert master["_provider_used"] == "TOP"
    assert master["genres"] == ["Action"]
    assert master["publisher"] == "Kadokawa"
    assert master.get("age_rating") == "mature"
    assert "ALT" in (master.get("_fusion_providers") or [])


def test_merge_candidates_auto_still_skips_adult_age_without_flag():
    """BF102 : Auto comble suggestive, refuse pornographic ; MR fill_age_rating=True tout âge."""
    adult_ordered = [
        ("SAFE", {"title": "Safe", "summary": "S", "age_rating": ""}),
        ("ADULT", {"title": "Adult", "age_rating": "pornographic", "genres": ["Adult"]}),
    ]
    merged = metadata_fetcher.merge_candidates(adult_ordered, smart_fusion=True)
    assert merged.get("age_rating") == ""
    assert merged["genres"] == ["Adult"]

    filled = metadata_fetcher.merge_candidates(
        adult_ordered, smart_fusion=True, fill_age_rating=True
    )
    assert filled.get("age_rating") == "pornographic"

    teen_ordered = [
        ("BASE", {"title": "Base", "summary": "S", "age_rating": ""}),
        ("MD", {"title": "MD", "age_rating": "suggestive"}),
    ]
    teen = metadata_fetcher.merge_candidates(teen_ordered, smart_fusion=True)
    assert teen.get("age_rating") == "suggestive"


def test_choice_and_merge_no_sources_even_if_caller_passes_smart_true(isolated_db):
    """Sans includes, smart_fusion=True ne doit rien combler (ordered = base seul)."""
    payload = {
        "above": [
            _card("TOP", 0.9, summary="only"),
            _card("ALT", 0.7, genres=["X"]),
        ],
        "below": [],
        "query": "q",
    }
    rid = mr.create_review_from_candidates(302, "NoSrc", payload)
    master = mr.choice_and_merge(
        rid, "TOP", include_providers=[], smart_fusion=True
    )
    assert "X" not in (master.get("genres") or [])
    assert master.get("_fusion_providers", []) == []


def test_apply_manual_review_smart_completion_config_ignored_without_sources(
    isolated_db, mocker
):
    payload = {
        "above": [
            _card("TOP", 0.91, summary="base only", title="Top"),
            _card("ALT", 0.75, genres=["Action"], publisher="Kadokawa"),
        ],
        "below": [],
        "query": "q",
    }
    rid = mr.create_review_from_candidates(303, "CfgIgn", payload)

    mocker.patch.object(
        enrichment_engine,
        "load_config",
        return_value={
            "KAVITA_URL": "http://kavita.local",
            "KAVITA_API_KEY": "k",
            "UI_LANG": "fr",
            "SMART_COMPLETION": True,
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
        return_value={"seriesId": 303, "summary": ""},
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


def test_bulk_accept_calls_apply_with_empty_includes(mocker, isolated_db):
    """Bulk-accept = TOP1 sans fusion Sources, même si SMART_COMPLETION on."""
    calls = []

    def _fake_apply(review_id, base_provider, include_providers=None, **kwargs):
        calls.append(
            {
                "review_id": review_id,
                "base": base_provider,
                "includes": list(include_providers or []),
            }
        )
        return True, "Succès", {}

    mocker.patch.object(mr_routes, "apply_manual_review", side_effect=_fake_apply)
    mocker.patch.object(
        mr_routes,
        "load_config",
        return_value={"UI_LANG": "en", "SMART_COMPLETION": True},
    )

    isolated_db.park_pending_review(
        "bulk-sc",
        401,
        "BulkSC",
        candidates_json={
            "above": [
                _card("ANILIST", 0.95, summary="a"),
                _card("MAL", 0.80, genres=["Action"]),
            ],
            "below": [],
            "query": "BulkSC",
        },
        state="awaiting_pick",
    )

    res = _client().post("/api/manual-reviews/bulk-accept", json={"threshold": 0.6})
    body = res.get_json()
    assert res.status_code == 200
    assert body["accepted"] == 1
    assert calls == [
        {"review_id": "bulk-sc", "base": "ANILIST", "includes": []}
    ]


def test_cbw_frozen_payload_keeps_prior_fusion_on_confirm(isolated_db, mocker):
    """CBW park : payload déjà fusionné ; confirm sans Sources réécrit tel quel."""
    fused = {
        "title": "Frozen",
        "summary": "auto fused",
        "genres": ["Action"],
        "publisher": "FromSecondary",
        "_provider_used": "TOP",
        "_fusion_providers": ["ALT"],
    }
    preview = {
        "title": "Frozen",
        "summary": "auto fused",
        "year": "",
        "genres": "Action",
        "tags": "",
        "publisher": "FromSecondary",
        "staff": "",
        "cover_url": "",
        "localized_name": "",
        "status": "",
        "age_rating": "",
        "format": "",
    }
    rid = mr.create_confirm_from_auto(
        402,
        "CBWFrozen",
        fused,
        preview,
        actual_provider="TOP",
        fusion_providers=["ALT"],
        chosen_score=0.91,
        query="CBWFrozen",
        force_update=False,
    )
    assert rid

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
        return_value={"seriesId": 402, "summary": ""},
    )
    mocker.patch.object(KavitaAPI, "update_series_metadata", side_effect=_capture)
    mocker.patch.object(KavitaAPI, "update_series_general", return_value=(True, "ok", True))
    mocker.patch.object(KavitaAPI, "update_series_external_ids", return_value=True)

    review = isolated_db.get_pending_review(rid)
    cands = json.loads(review["candidates_json"])
    assert cands.get("flow") == "auto_confirm"
    base = cands["above"][0]["provider"]

    ok, msg, _ = enrichment_engine.apply_manual_review(
        rid, base_provider=base, include_providers=[], field_edits=0
    )
    assert ok is True, msg
    meta = captured.get("meta") or {}
    genres = [
        (g.get("title") if isinstance(g, dict) else str(g))
        for g in (meta.get("genres") or [])
    ]
    assert "Action" in genres
    assert "auto fused" in (meta.get("summary") or "")
