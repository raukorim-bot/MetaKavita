"""C96 T4 — filet heures (trigger scan), seed, pas de GET si filet 0."""
from __future__ import annotations

import time

from services import auto_sync as asy
from translations import translations


class _Kavita:
    def __init__(self, series, complete=True):
        self.series = list(series)
        self.last_inventory_complete = complete
        self.gets = 0
        self.auths = 0

    def authenticate(self):
        self.auths += 1
        return True

    def get_all_series(self, library_id=None):
        self.gets += 1
        return list(self.series)


def test_catchup_zero_is_never_due():
    assert asy.catchup_due(None, 0) is False
    assert asy.catchup_due(0, 0) is False


def test_catchup_hours_due_when_elapsed():
    assert asy.catchup_due(None, 24) is True
    assert asy.catchup_due(time.time(), 24) is False
    assert asy.catchup_due(time.time() - 25 * 3600, 24) is True


def test_needs_seed_on_empty_table_and_trigger_switch(isolated_db):
    cfg = {"AUTO_SYNC_TRIGGER": "scan"}
    assert asy.needs_seed(cfg) is True
    asy.seed_known_from_inventory([{"id": 1, "name": "A"}])
    assert asy.needs_seed(cfg, previous_trigger="scan") is False
    assert asy.needs_seed(cfg, previous_trigger="interval") is True
    assert asy.needs_seed({"AUTO_SYNC_TRIGGER": "interval"}) is False


def test_interval_tick_does_not_write_snapshot(isolated_db, monkeypatch):
    import services.background_tasks as bg

    kavita = _Kavita([{"id": 1, "name": "A", "libraryId": 1}], complete=True)
    monkeypatch.setattr(asy, "_auth_kavita", lambda config: kavita)
    monkeypatch.setattr(bg, "clean_orphaned_cache", lambda ids: 0)
    monkeypatch.setattr(bg, "get_all_cached_data", lambda: {})
    items = []
    monkeypatch.setattr(bg, "put_sync", lambda item: items.append(item))

    n = asy.run_interval_or_catchup(
        {"UI_LANG": "fr", "AUTO_SYNC_TRIGGER": "interval", "AUTO_SYNC_MODE": "auto"},
        translations["fr"],
    )
    assert n == 1
    assert items[0]["series_id"] == 1
    assert isolated_db.get_auto_sync_known_ids() == set()


def test_incomplete_catchup_leaves_snapshot_untouched(isolated_db, monkeypatch):
    isolated_db.replace_auto_sync_known_ids([99])
    kavita = _Kavita([{"id": 1, "name": "A"}], complete=False)
    monkeypatch.setattr(asy, "_auth_kavita", lambda config: kavita)
    n = asy.run_interval_or_catchup(
        {"UI_LANG": "fr", "AUTO_SYNC_TRIGGER": "scan", "AUTO_SYNC_CATCHUP_HOURS": 24},
        translations["fr"],
    )
    assert n == 0
    assert isolated_db.get_auto_sync_known_ids() == {99}
    assert kavita.gets == 1


def test_scan_fire_enqueues_only_added(isolated_db, monkeypatch):
    import services.background_tasks as bg

    isolated_db.replace_auto_sync_known_ids([1])
    items = []
    monkeypatch.setattr(bg, "put_sync", lambda item: items.append(item))
    kavita = _Kavita(
        [
            {"id": 1, "name": "Old", "libraryId": 1},
            {"id": 2, "name": "New", "libraryId": 1},
        ],
        complete=True,
    )
    monkeypatch.setattr(asy, "_auth_kavita", lambda config: kavita)
    monkeypatch.setattr(bg, "queued_series_ids", lambda **k: set())
    monkeypatch.setattr(bg, "get_all_cached_data", lambda: {})

    n = asy.run_scan_fire({"UI_LANG": "fr", "AUTO_SYNC_MODE": "auto"}, translations["fr"])
    assert n == 1
    assert items[0]["series_id"] == 2
    assert isolated_db.get_auto_sync_known_ids() == {1, 2}
