"""NEEDS_RELOCK : soft-fail re-lock → statut orange + seal différé."""

from services import kavita_payload


def test_apply_kavita_payload_sets_needs_relock_when_unsealed(mocker, isolated_db):
    mocker.patch("services.kavita_payload.translate_text", side_effect=lambda text, *a, **k: text)
    mocker.patch("services.kavita_payload._broadcast_enrichment_stats", lambda *a, **k: None)
    mocker.patch("services.kavita_payload._emit_series_status")
    mocker.patch("services.kavita_payload._schedule_seal_retry")

    class FakeKavita:
        def update_series_external_ids(self, *a, **k):
            return True, "ok"

        def update_series_metadata(self, meta):
            return True, "Succès (écriture OK ; re-lock échoué: timeout)", False

        def update_series_general(self, *a, **k):
            return True, "Succès", True

        def upload_series_cover(self, *a, **k):
            return True, "ok"

    built = {
        "metadata": {"seriesId": 55, "summary": "Hi", "summaryLocked": True},
        "localized_name": None,
        "format_val": None,
        "cover_url": None,
        "external_ids": {},
    }
    t = {"log_sending": "[{0}] send", "log_success": "[{0}] ok", "log_needs_relock": "[{0}] needs", "log_kavita_refused": "[{0}] refuse {1}"}

    ok, msg, used = kavita_payload.apply_kavita_payload(
        FakeKavita(),
        55,
        "Series X",
        built,
        ["summary"],
        {},
        ["ANILIST"],
        t,
    )

    assert ok is True
    assert msg == "NEEDS_RELOCK"
    assert isolated_db.get_all_cached_data()[55]["status"] == "NEEDS_RELOCK"
    kavita_payload._schedule_seal_retry.assert_called_once()


def test_apply_kavita_payload_completed_when_sealed(mocker, isolated_db):
    mocker.patch("services.kavita_payload._broadcast_enrichment_stats", lambda *a, **k: None)
    mocker.patch("services.kavita_payload._emit_series_status")
    sched = mocker.patch("services.kavita_payload._schedule_seal_retry")

    class FakeKavita:
        def update_series_external_ids(self, *a, **k):
            return True, "ok"

        def update_series_metadata(self, meta):
            return True, "Succès", True

        def update_series_general(self, *a, **k):
            return True, "Succès", True

        def upload_series_cover(self, *a, **k):
            return True, "ok"

    built = {
        "metadata": {"seriesId": 56, "summary": "Hi", "summaryLocked": True},
        "localized_name": None,
        "format_val": None,
        "cover_url": None,
        "external_ids": {},
    }
    t = {"log_sending": "[{0}] send", "log_success": "[{0}] ok", "log_needs_relock": "[{0}] needs", "log_kavita_refused": "[{0}] refuse {1}"}

    ok, msg, used = kavita_payload.apply_kavita_payload(
        FakeKavita(),
        56,
        "Series Y",
        built,
        ["summary"],
        {},
        ["ANILIST"],
        t,
    )

    assert ok is True
    assert msg == "Succès"
    assert isolated_db.get_all_cached_data()[56]["status"] == "COMPLETED"
    sched.assert_not_called()
