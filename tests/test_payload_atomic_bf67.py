"""BF67 — Do not call update_series_general when metadata write failed."""

from services import kavita_payload


def _t():
    return {
        "log_sending": "[{0}] send",
        "log_success": "[{0}] ok",
        "log_needs_relock": "[{0}] needs",
        "log_kavita_refused": "[{0}] refuse {1}",
    }


def test_nr_g2_meta_success_still_calls_general(mocker, isolated_db):
    """NR-G2: successful metadata + localizedName → general called once."""
    mocker.patch("services.kavita_payload._broadcast_enrichment_stats", lambda *a, **k: None)
    mocker.patch("services.kavita_payload._emit_series_status")
    mocker.patch("services.kavita_payload._schedule_seal_retry")

    general_calls = []

    class FakeKavita:
        def update_series_external_ids(self, *a, **k):
            return True, "ok"

        def update_series_metadata(self, meta):
            return True, "Succès", True

        def update_series_general(self, series_id, localized_name=None, format_val=None):
            general_calls.append((series_id, localized_name, format_val))
            return True, "Succès", True

        def upload_series_cover(self, *a, **k):
            return True, "ok"

    built = {
        "metadata": {"seriesId": 60, "summary": "Hi", "summaryLocked": True},
        "localized_name": "Localized Title",
        "format_val": None,
        "cover_url": None,
        "external_ids": {},
    }

    ok, msg, used = kavita_payload.apply_kavita_payload(
        FakeKavita(),
        60,
        "Series G2",
        built,
        ["summary"],
        {},
        ["ANILIST"],
        _t(),
    )

    assert ok is True
    assert len(general_calls) == 1
    assert general_calls[0][0] == 60
    assert general_calls[0][1] == "Localized Title"
    assert isolated_db.get_all_cached_data()[60]["status"] == "COMPLETED"


def test_nr_p2_meta_fail_skips_general(mocker, isolated_db):
    """NR-P2: metadata failure → update_series_general never called."""
    mocker.patch("services.kavita_payload._broadcast_enrichment_stats", lambda *a, **k: None)
    mocker.patch("services.kavita_payload._emit_series_status")

    general_calls = []

    class FakeKavita:
        def update_series_external_ids(self, *a, **k):
            return True, "ok"

        def update_series_metadata(self, meta):
            return False, "Code 400: bad payload", False

        def update_series_general(self, series_id, localized_name=None, format_val=None):
            general_calls.append((series_id, localized_name, format_val))
            return True, "Succès", True

        def upload_series_cover(self, *a, **k):
            return True, "ok"

    built = {
        "metadata": {"seriesId": 61, "summary": "Hi", "summaryLocked": True},
        "localized_name": "Should Not Write",
        "format_val": 1,
        "cover_url": None,
        "external_ids": {},
    }

    ok, msg, used = kavita_payload.apply_kavita_payload(
        FakeKavita(),
        61,
        "Series P2",
        built,
        ["summary"],
        {},
        ["ANILIST"],
        _t(),
    )

    assert ok is False
    assert general_calls == []
