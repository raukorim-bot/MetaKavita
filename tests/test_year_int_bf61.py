"""BF61 — releaseYear only written as valid int YYYY (no string lock)."""
from services.kavita_payload import build_kavita_payload, overlay_edited_preview


def test_payload_writes_int_year():
    result = build_kavita_payload(
        provider_data={"title": "X", "year": 2011},
        metadata={"seriesId": 1},
        active_fields=["year"],
        config={"TARGET_LANG": ""},
        cache_data={},
        force_update=True,
        series_id=1,
    )
    assert result["metadata"]["releaseYear"] == 2011
    assert result["metadata"]["releaseYearLocked"] is True


def test_payload_accepts_numeric_string_year():
    result = build_kavita_payload(
        provider_data={"title": "X", "year": "1999"},
        metadata={"seriesId": 1},
        active_fields=["year"],
        config={"TARGET_LANG": ""},
        cache_data={},
        force_update=True,
        series_id=1,
    )
    assert result["metadata"]["releaseYear"] == 1999


def test_payload_skips_non_int_year():
    result = build_kavita_payload(
        provider_data={"title": "X", "year": "201a"},
        metadata={"seriesId": 1},
        active_fields=["year"],
        config={"TARGET_LANG": ""},
        cache_data={},
        force_update=True,
        series_id=1,
    )
    assert "releaseYear" not in result["metadata"]
    assert result["metadata"].get("releaseYearLocked") is not True


def test_payload_skips_year_out_of_range():
    result = build_kavita_payload(
        provider_data={"title": "X", "year": 999},
        metadata={"seriesId": 1},
        active_fields=["year"],
        config={"TARGET_LANG": ""},
        cache_data={},
        force_update=True,
        series_id=1,
    )
    assert "releaseYear" not in result["metadata"]


def test_overlay_invalid_year_becomes_none():
    data = overlay_edited_preview({"title": "X", "year": 2000}, {"year": "c. 1990"})
    assert data.get("year") is None
