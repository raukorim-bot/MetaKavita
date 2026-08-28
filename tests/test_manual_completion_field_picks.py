"""
C86 — Complétion manuelle : un gagnant par champ, fusion de listes sans dédup.

Le chemin Source (hole-fill) reste le défaut. `field_picks` remplace ce merge.
"""
from __future__ import annotations

import json

import services.enrichment_engine as enrichment_engine
import services.manual_review as mr
from scrapers.utils import MATCH_SCORE_KEY
from services.field_assembly import normalize_field_picks


def _card(provider, score, **data):
    data = dict(data)
    data.setdefault("title", provider)
    data.setdefault(MATCH_SCORE_KEY, score)
    return {
        "provider": provider,
        "score": score,
        "title": data["title"],
        "cover_url": data.get("cover_url", ""),
        "data": data,
    }


def _park(series_id, name, above):
    return mr.create_review_from_candidates(
        series_id, name, {"above": above, "below": [], "query": name}
    )


def test_normalize_field_picks_scalars_stay_exclusive():
    raw = {
        "cover": ["AniList", "MAL"],
        "tags": ["MAL", "MU", "MAL"],
        "unknown": ["X"],
        "publisher": "MangaBaka",
    }
    exclusive = normalize_field_picks(raw, merge_fields=False)
    assert exclusive["cover"] == ["AniList"]
    assert exclusive["tags"] == ["MAL"]
    assert exclusive["publisher"] == ["MangaBaka"]
    assert "unknown" not in exclusive

    merged = normalize_field_picks(raw, merge_fields=True)
    assert merged["cover"] == ["AniList"]
    assert merged["tags"] == ["MAL", "MU"]


def test_exclusive_pick_overwrites_master_cover_and_staff(isolated_db):
    rid = _park(
        3801,
        "StealCover",
        [
            _card(
                "TOP",
                0.95,
                title="Master",
                cover_url="http://master/cover.jpg",
                publisher="Kadokawa",
                staff=[{"name": "Last, First", "role": "Story"}],
            ),
            _card(
                "ANILIST",
                0.80,
                title="Ani",
                cover_url="http://anilist/cover.jpg",
                staff=[{"name": "First Last", "role": "Story"}],
            ),
        ],
    )
    master = mr.choice_and_merge(
        rid,
        "TOP",
        field_picks={
            "cover": ["ANILIST"],
            "staff": ["ANILIST"],
            "publisher": ["TOP"],
        },
    )
    assert master["cover_url"] == "http://anilist/cover.jpg"
    assert master["publisher"] == "Kadokawa"
    assert master["staff"][0]["name"] == "First Last"
    assert master["_fusion_providers"] == ["ANILIST"]


def test_merge_lists_concatenate_without_dedup(isolated_db):
    rid = _park(
        3802,
        "ConcatTags",
        [
            _card("TOP", 0.9, tags=["Action", "France"], genres=["Shonen"]),
            _card("MU", 0.7, tags=["Action", "Seinen"], genres=["Adventure"]),
        ],
    )
    master = mr.choice_and_merge(
        rid,
        "TOP",
        field_picks={"tags": ["TOP", "MU"], "genres": ["TOP"]},
        merge_fields=True,
    )
    assert master["tags"] == ["Action", "France", "Action", "Seinen"]
    assert master["genres"] == ["Shonen"]
    assert "MU" in master["_fusion_providers"]


def test_merge_fields_off_keeps_one_list_winner(isolated_db):
    rid = _park(
        3803,
        "OneList",
        [
            _card("TOP", 0.9, tags=["MasterTag"]),
            _card("MU", 0.7, tags=["OtherTag"]),
        ],
    )
    master = mr.choice_and_merge(
        rid,
        "TOP",
        field_picks={"tags": ["TOP", "MU"]},
        merge_fields=False,
    )
    assert master["tags"] == ["MasterTag"]
    assert master.get("_fusion_providers") == []


def test_field_picks_empty_is_master_only_no_hole_fill(isolated_db):
    rid = _park(
        3804,
        "NoHole",
        [
            _card("TOP", 0.9, summary="base only"),
            _card("ALT", 0.7, genres=["Action"], publisher="Kadokawa"),
        ],
    )
    master = mr.choice_and_merge(
        rid, "TOP", include_providers=["ALT"], smart_fusion=True, field_picks={}
    )
    assert "Action" not in (master.get("genres") or [])
    assert not master.get("publisher")
    assert master.get("_fusion_providers") == []


def test_source_path_unchanged_without_field_picks(isolated_db):
    rid = _park(
        3805,
        "Legacy",
        [
            _card("TOP", 0.9, summary="base"),
            _card("ALT", 0.7, genres=["Action"], publisher="Kadokawa"),
        ],
    )
    master = mr.choice_and_merge(
        rid, "TOP", include_providers=["ALT"], smart_fusion=True
    )
    assert master["genres"] == ["Action"]
    assert master["publisher"] == "Kadokawa"


def test_adult_age_explicit_pick_is_allowed(isolated_db):
    rid = _park(
        3806,
        "AdultAge",
        [
            _card("TOP", 0.9, summary="safe", age_rating="safe"),
            _card("CV", 0.6, age_rating="pornographic"),
        ],
    )
    master = mr.choice_and_merge(
        rid, "TOP", field_picks={"age_rating": ["CV"]}
    )
    assert master.get("age_rating") == "pornographic"


def test_preview_persists_field_picks(isolated_db, mocker):
    rid = _park(
        3807,
        "PreviewPicks",
        [
            _card("TOP", 0.9, title="Master", cover_url="http://m/c.jpg", summary="base"),
            _card("ANILIST", 0.8, title="Ani", cover_url="http://a/c.jpg"),
        ],
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
        KavitaAPI, "get_series_metadata", return_value={"seriesId": 3807, "summary": ""}
    )

    ok, preview, _built = enrichment_engine.preview_manual_review(
        rid,
        "TOP",
        include_providers=[],
        field_picks={"cover": ["ANILIST"]},
        merge_fields=False,
    )
    assert ok is True
    assert preview.get("cover_url") == "http://a/c.jpg"
    assert preview.get("_manual_completion") is True
    assert preview.get("_field_picks")["cover"] == ["ANILIST"]
    assert "ANILIST" in (preview.get("_fusion_providers") or [])

    from db_manager import get_pending_review

    stored = json.loads(get_pending_review(rid)["preview_json"])
    assert stored["_field_picks"]["cover"] == ["ANILIST"]


def test_apply_ignores_stored_picks_when_manual_completion_off(isolated_db, mocker):
    rid = _park(
        3809,
        "OffClears",
        [
            _card("TOP", 0.9, title="Master", cover_url="http://m/c.jpg", summary="base"),
            _card("ANILIST", 0.8, title="Ani", cover_url="http://a/c.jpg"),
        ],
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
        KavitaAPI, "get_series_metadata", return_value={"seriesId": 3809, "summary": ""}
    )
    captured = {}

    def _capture(meta):
        captured["cover"] = (meta or {}).get("coverImage") or (meta or {}).get("cover")
        return True, "ok", True

    mocker.patch.object(KavitaAPI, "update_series_metadata", side_effect=_capture)
    mocker.patch.object(KavitaAPI, "update_series_general", return_value=(True, "ok", True))
    mocker.patch.object(KavitaAPI, "update_series_external_ids", return_value=True)
    mocker.patch.object(enrichment_engine, "_broadcast_enrichment_stats", lambda *a, **k: None)

    ok, preview, _ = enrichment_engine.preview_manual_review(
        rid,
        "TOP",
        include_providers=[],
        field_picks={"cover": ["ANILIST"]},
        merge_fields=False,
        manual_completion=True,
    )
    assert ok is True
    assert preview.get("cover_url") == "http://a/c.jpg"

    ok2, msg, detail = enrichment_engine.apply_manual_review(
        rid,
        base_provider="TOP",
        include_providers=[],
        field_picks=None,
        manual_completion=False,
    )
    assert ok2 is True, msg
    written = (detail or {}).get("preview") or {}
    assert written.get("cover_url") == "http://m/c.jpg"


def test_parse_field_picks_omitted_vs_manual():
    from routes.manual_review import _parse_field_picks

    assert _parse_field_picks({"include_providers": ["ALT"]}) == (None, False, None)
    picks, merge, on = _parse_field_picks({
        "manual_completion": True,
        "merge_fields": True,
        "field_picks": {"tags": ["TOP", "MU"]},
    })
    assert picks == {"tags": ["TOP", "MU"]}
    assert merge is True
    assert on is True
    empty, merge_off, still_on = _parse_field_picks({"manual_completion": True})
    assert empty == {}
    assert merge_off is False
    assert still_on is True
    assert _parse_field_picks({"manual_completion": False, "field_picks": {"cover": ["X"]}}) == (
        None, False, False
    )


def test_mal_hentai_genres_do_not_rewrite_comicvine_age(isolated_db):
    """C88 A3 : bump par blob, pas après mix — genres MAL ≠ âge ComicVine."""
    rid = _park(
        3810,
        "AgeMix",
        [
            _card(
                "COMICVINE",
                0.9,
                summary="cv",
                age_rating="mature",
                genres=["Superhero"],
            ),
            _card(
                "MAL",
                0.8,
                summary="mal",
                age_rating="",
                genres=["Hentai"],
            ),
        ],
    )
    master = mr.choice_and_merge(
        rid,
        "COMICVINE",
        field_picks={"age_rating": ["COMICVINE"], "genres": ["MAL"]},
    )
    assert master["age_rating"] == "mature"
    assert master["genres"] == ["Hentai"]
