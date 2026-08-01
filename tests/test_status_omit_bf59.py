"""BF59 — do not invent publication status FINISHED when provider has no signal."""
from services.kavita_payload import build_kavita_payload


def test_payload_skips_missing_status():
    result = build_kavita_payload(
        provider_data={"title": "X", "summary": "hello"},
        metadata={"seriesId": 1},
        active_fields=["status", "summary"],
        config={"TARGET_LANG": ""},
        cache_data={},
        force_update=True,
        series_id=1,
    )
    assert "publicationStatus" not in result["metadata"]
    assert result["metadata"].get("publicationStatusLocked") is not True


def test_payload_writes_real_status():
    result = build_kavita_payload(
        provider_data={"title": "X", "status": "RELEASING"},
        metadata={"seriesId": 1},
        active_fields=["status"],
        config={"TARGET_LANG": ""},
        cache_data={},
        force_update=True,
        series_id=1,
    )
    assert result["metadata"]["publicationStatus"] == 0  # RELEASING
    assert result["metadata"]["publicationStatusLocked"] is True


def test_payload_skips_empty_status_string():
    result = build_kavita_payload(
        provider_data={"title": "X", "status": ""},
        metadata={"seriesId": 1},
        active_fields=["status"],
        config={"TARGET_LANG": ""},
        cache_data={},
        force_update=True,
        series_id=1,
    )
    assert "publicationStatus" not in result["metadata"]
