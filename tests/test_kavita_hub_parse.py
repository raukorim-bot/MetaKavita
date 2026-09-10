"""C96 T6 — parse SignalR fictif, debounce, pas de socket."""
from __future__ import annotations

import json

import pytest

import services.background_tasks as bg
from services import kavita_hub as hub


@pytest.fixture(autouse=True)
def _clean_hub():
    hub.reset_hub_logic_state()
    while True:
        try:
            bg.auto_sync_wake_queue.get_nowait()
        except Exception:
            break
    yield
    hub.reset_hub_logic_state()
    while True:
        try:
            bg.auto_sync_wake_queue.get_nowait()
        except Exception:
            break


def _frame(target, body):
    return json.dumps({"type": 1, "target": target, "arguments": [body]}) + hub.RECORD_SEPARATOR


def test_parse_invocation_reads_type1_and_ignores_ping():
    name, body = hub.parse_invocation(_frame("SeriesAdded", {"seriesId": 12}))
    assert name == "SeriesAdded"
    assert body["seriesId"] == 12
    assert hub.parse_invocation('{"type":6}' + hub.RECORD_SEPARATOR) is None
    assert hub.parse_invocation('{"protocol":"json","version":1}' + hub.RECORD_SEPARATOR) is None


def test_parse_invocation_accepts_target_in_arguments():
    raw = json.dumps({
        "type": 1,
        "target": "Receive",
        "arguments": ["ScanLibraryProgress", {"libraryId": 3, "leftToProcess": 2}],
    })
    name, body = hub.parse_invocation(raw)
    assert name == "ScanLibraryProgress"
    assert body["libraryId"] == 3


def test_user_progress_is_not_a_scanner_event():
    assert hub.is_scanner_event("UserProgressUpdate", {"seriesId": 1, "pagesRead": 9}) is False
    assert hub.is_scanner_event(
        "NotificationProgress",
        {"name": "UserProgressUpdate", "eventType": "updated"},
    ) is False


def test_series_added_and_scan_progress_are_scanner_events():
    assert hub.is_scanner_event("SeriesAdded", {"seriesId": 4}) is True
    assert hub.is_scanner_event("ScanSeries", {"seriesId": 4}) is True
    assert hub.is_scanner_event(
        "NotificationProgress",
        {"name": "ScanProgress", "eventType": "ended"},
    ) is True


def test_series_ended_is_not_library_idle():
    assert hub.is_library_scan_idle({
        "name": "ScanSeries",
        "eventType": "ended",
        "seriesId": 44,
        "leftToProcess": 0,
    }) is False
    assert hub.is_library_scan_idle({
        "libraryId": 1,
        "leftToProcess": 0,
    }) is True
    assert hub.is_library_scan_idle({
        "libraryId": 1,
        "leftToProcess": 3,
    }) is False


def test_burst_emits_a_single_wake():
    t0 = 1_000_000.0
    for i in range(8):
        hub.handle_invocation("SeriesAdded", {"seriesId": i}, now=t0 + i * 0.1)
    assert hub.maybe_emit_scan_wake(t0 + 5) is False
    assert hub.handle_invocation("SeriesAdded", {"seriesId": 99}, now=t0 + 1) is False
    assert hub.maybe_emit_scan_wake(t0 + 1 + hub.SCAN_DEBOUNCE_S) is True
    assert hub.maybe_emit_scan_wake(t0 + 1 + hub.SCAN_DEBOUNCE_S + 1) is False
    reasons = []
    while True:
        try:
            reasons.append(bg.auto_sync_wake_queue.get_nowait())
        except Exception:
            break
    assert reasons == ["scan"]


def test_library_idle_fires_after_short_quiet():
    t0 = 2_000_000.0
    hub.handle_invocation(
        "ScanLibraryProgress",
        {"libraryId": 2, "leftToProcess": 0},
        now=t0,
    )
    assert hub.maybe_emit_scan_wake(t0 + 1) is False
    assert hub.maybe_emit_scan_wake(t0 + hub.LIBRARY_IDLE_DEBOUNCE_S) is True
