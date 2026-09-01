"""C96 T3 — snapshot d'IDs : seed, diff, filtre, inventaire incomplet."""
from __future__ import annotations

from services import auto_sync as asy


class _Kavita:
    def __init__(self, series, complete=True):
        self._series = list(series)
        self.last_inventory_complete = complete

    def get_all_series(self, library_id=None):
        return list(self._series)


def test_incomplete_inventory_returns_none():
    kavita = _Kavita([{"id": 1, "name": "A"}], complete=False)
    assert asy.fetch_complete_inventory(kavita) is None


def test_complete_empty_inventory_is_a_list_not_none():
    kavita = _Kavita([], complete=True)
    assert asy.fetch_complete_inventory(kavita) == []


def test_seed_writes_snapshot_and_enqueues_nothing(isolated_db, monkeypatch):
    calls = []
    monkeypatch.setattr("services.background_tasks.put_sync", lambda item: calls.append(item))
    series = [{"id": 10, "name": "A"}, {"id": 20, "name": "B"}]
    assert asy.seed_known_from_inventory(series) == 0
    assert calls == []
    assert isolated_db.get_auto_sync_known_ids() == {10, 20}


def test_diff_added_skips_known_ids():
    series = [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}, {"id": 3, "name": "C"}]
    added = asy.diff_added(series, {1, 3})
    assert [s["id"] for s in added] == [2]


def test_replace_snapshot_is_atomic_not_a_merge(isolated_db):
    isolated_db.replace_auto_sync_known_ids([1, 2, 3])
    asy.replace_snapshot([{"id": 2, "name": "B"}, {"id": 9, "name": "Z"}])
    assert isolated_db.get_auto_sync_known_ids() == {2, 9}


def test_filter_excludes_ignored_pending_review_queued_and_disabled_libs():
    series = [
        {"id": 1, "name": "New", "libraryId": 1},
        {"id": 2, "name": "Ignored", "libraryId": 1},
        {"id": 3, "name": "Review", "libraryId": 1},
        {"id": 4, "name": "Queued", "libraryId": 1},
        {"id": 5, "name": "Other lib", "libraryId": 2},
        {"id": 6, "name": "Pending", "libraryId": 1},
    ]
    cached = {
        2: {"status": "IGNORED"},
        3: {"status": "PENDING_REVIEW"},
        6: {"status": "PENDING"},
    }
    out = asy.filter_enqueueable(
        series,
        cached,
        queued={4},
        config={"DISABLED_LIBRARIES": "2"},
    )
    assert [s["id"] for s in out] == [1, 6]


def test_enqueue_auto_uses_job_flags(isolated_db, monkeypatch):
    items = []
    monkeypatch.setattr("services.background_tasks.put_sync", lambda item: items.append(item))
    monkeypatch.setattr("services.background_tasks.broadcast_auto_sync_report", lambda *a, **k: None)
    n = asy.enqueue_auto(
        [{"id": 8, "name": "Eight", "libraryId": 1}],
        {"AUTO_SYNC_MODE": "review"},
    )
    assert n == 1
    assert items[0]["origin"] == "auto"
    assert items[0]["manual_review_override"] is True
    assert items[0]["force_auto"] is False
