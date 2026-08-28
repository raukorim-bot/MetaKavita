"""A1 — ProviderFieldSource : carte MR vs blob scraper."""
from __future__ import annotations

from services.field_assembly import source_from_card, source_from_scraper_data


def test_source_from_card_cover_prefers_data_then_toplevel():
    card = {
        "provider": "ANILIST",
        "cover_url": "http://card/top.jpg",
        "data": {"cover_url": "http://card/data.jpg", "title": "Ani"},
    }
    src = source_from_card(card)
    assert src.get("cover") == "http://card/data.jpg"
    assert src.blob()["cover_url"] == "http://card/data.jpg"

    fallback = {
        "provider": "MAL",
        "cover_url": "http://card/top-only.jpg",
        "data": {"title": "Mal"},
    }
    assert source_from_card(fallback).get("cover") == "http://card/top-only.jpg"


def test_source_from_scraper_data_cover_has_no_card_fallback():
    blob = {"title": "Hit", "cover_url": "http://scraper/cover.jpg"}
    src = source_from_scraper_data(blob)
    assert src.get("cover") == "http://scraper/cover.jpg"
    assert src.get("summary") is None

    empty = source_from_scraper_data({"title": "Empty"})
    assert empty.get("cover") is None


def test_source_from_card_staff_payload_roles():
    card = {
        "provider": "CV",
        "data": {"writers": ["Alice"], "pencillers": ["Bob"]},
    }
    payload = source_from_card(card).staff_payload()
    assert payload["writers"] == ["Alice"]
    assert payload["pencillers"] == ["Bob"]
    assert source_from_scraper_data({"staff": [{"name": "Z"}]}).get("staff") == [
        {"name": "Z"}
    ]


def test_absorb_identity_fills_empty_ids_only():
    from services.field_assembly import absorb_identity

    target = {"summary": "keep", "cover_url": "http://a", "anilist_id": 1}
    absorb_identity(
        target,
        [
            {"mal_id": 99, "summary": "mal", "cover_url": "http://mal", "anilist_id": 2},
            {"isbn": "978-1", "age_rating": "x18", "genres": ["Hentai"]},
        ],
    )
    assert target["anilist_id"] == 1
    assert target["mal_id"] == 99
    assert target["isbn"] == "978-1"
    assert target["summary"] == "keep"
    assert target["cover_url"] == "http://a"
    assert "age_rating" not in target
    assert "genres" not in target


def test_pick_assembly_base_prefers_useful_default_then_override():
    from services.field_assembly import pick_assembly_base

    default = {"title": "empty"}
    mal = {"summary": "from mal"}
    cv = {"cover_url": "http://cv"}
    assert pick_assembly_base("MAL", mal, {"CV": cv}, ["CV"]).provider_id == "MAL"
    assert pick_assembly_base("NONE", default, {"CV": cv, "MAL": mal}, ["MAL", "CV"]).provider_id == "MAL"
    assert pick_assembly_base("NONE", default, {"X": {"tags": ["only"]}}, ["X"]) is None
