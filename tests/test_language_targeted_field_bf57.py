"""BF57 — language only written when in targeted fields mask."""
from services.enrichment_engine import ALL_TARGETED_FIELDS, resolve_active_fields
from services.kavita_payload import build_kavita_payload


def test_language_in_all_targeted_fields():
    assert "language" in ALL_TARGETED_FIELDS
    assert "language" in resolve_active_fields("ALL")


def test_language_written_when_in_mask():
    result = build_kavita_payload(
        provider_data={"title": "X"},
        metadata={"seriesId": 1, "language": ""},
        active_fields=["language"],
        config={"TARGET_LANG": "FR"},
        cache_data={},
        force_update=True,
        series_id=1,
    )
    assert result["metadata"]["language"] == "fr"
    assert result["metadata"]["languageLocked"] is True


def test_language_skipped_when_not_in_mask():
    result = build_kavita_payload(
        provider_data={"title": "X", "summary": "hello"},
        metadata={"seriesId": 1, "language": ""},
        active_fields=["cover", "summary"],
        config={"TARGET_LANG": "FR"},
        cache_data={},
        force_update=True,
        series_id=1,
    )
    assert result["metadata"].get("language") in (None, "")
    assert result["metadata"].get("languageLocked") is not True
