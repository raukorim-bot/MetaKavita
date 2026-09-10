"""C96 T7 — hub live mocké, pas de JWT dans les logs, pas de socket réel."""
from __future__ import annotations

import logging
import queue
import time

import pytest

import services.background_tasks as bg
from services import kavita_hub as hub


@pytest.fixture(autouse=True)
def _stop_hub():
    yield
    hub.stop_hub()
    hub.reset_hub_logic_state()


def test_hub_ws_url_switches_scheme_and_path():
    assert hub.hub_ws_url("http://kavita.example:5000") == "ws://kavita.example:5000/hubs/messages"
    assert hub.hub_ws_url("https://kavita.example").startswith("wss://kavita.example/hubs/messages")


def test_plugin_jwt_is_never_logged(monkeypatch, caplog):
    class Fake:
        token = "secret.jwt.token.value"

        def __init__(self, *a, **k):
            pass

        def authenticate(self):
            return True

    monkeypatch.setattr("kavita_api.KavitaAPI", Fake)
    with caplog.at_level(logging.DEBUG):
        token = hub.plugin_jwt({"KAVITA_URL": "http://kavita.test", "KAVITA_API_KEY": "k"})
    assert token == "secret.jwt.token.value"
    assert "secret.jwt.token.value" not in caplog.text
    assert "secret.jwt" not in caplog.text


def test_negotiate_reads_connection_token(monkeypatch):
    monkeypatch.setattr(
        hub, "_http_request", lambda *a, **k: (200, b'{"connectionToken":"cid-1"}')
    )
    assert hub.negotiate("http://kavita.test", "tok") == "cid-1"


def test_hub_status_redacts_bearer_token():
    hub.set_hub_status(
        "error",
        "https://kavita.test/hubs/messages?access_token=super.secret.jwt",
    )
    body = hub.hub_public_status()
    assert "super.secret.jwt" not in str(body)
    assert body["status"] == "error"


def test_start_hub_uses_mocked_loop_not_tcp(monkeypatch):
    connects = []
    monkeypatch.setattr(hub, "_tcp_connect", lambda *a, **k: connects.append(a))
    monkeypatch.setattr(hub, "run_websocket_loop", lambda ev: ev.wait(0.3))
    hub.start_hub()
    hub.start_hub()
    time.sleep(0.05)
    hub.stop_hub()
    time.sleep(0.05)
    assert connects == []


class _StopLoop(Exception):
    pass


def _one_worker_pass(bg_mod, monkeypatch, config):
    monkeypatch.setattr(bg_mod, "load_config", lambda: config)

    def _get(timeout=None):
        raise queue.Empty()

    monkeypatch.setattr(bg_mod.auto_sync_wake_queue, "get", _get)
    monkeypatch.setattr(bg_mod.time, "sleep", lambda *_: (_ for _ in ()).throw(_StopLoop()))
    with pytest.raises(_StopLoop):
        bg_mod._auto_sync_worker()


def test_worker_starts_hub_when_scan_enabled(isolated_db, monkeypatch):
    isolated_db.replace_auto_sync_known_ids([1])
    calls = []
    monkeypatch.setattr("services.kavita_hub.start_hub", lambda: calls.append("start"))
    monkeypatch.setattr("services.kavita_hub.stop_hub", lambda: calls.append("stop"))
    monkeypatch.setattr(bg, "_seed_scan_snapshot", lambda *a, **k: True)
    _one_worker_pass(
        bg,
        monkeypatch,
        {
            "UI_LANG": "fr",
            "AUTO_SYNC_ENABLED": True,
            "AUTO_SYNC_TRIGGER": "scan",
            "AUTO_SYNC_CATCHUP_HOURS": 0,
            "KAVITA_URL": "http://kavita.test",
            "KAVITA_API_KEY": "key",
        },
    )
    assert calls == ["start"]


def test_worker_stops_hub_when_interval_or_off(monkeypatch):
    calls = []
    monkeypatch.setattr("services.kavita_hub.start_hub", lambda: calls.append("start"))
    monkeypatch.setattr("services.kavita_hub.stop_hub", lambda: calls.append("stop"))
    monkeypatch.setattr(bg, "_auto_sync_tick", lambda *a, **k: 0)
    _one_worker_pass(
        bg,
        monkeypatch,
        {
            "UI_LANG": "fr",
            "AUTO_SYNC_ENABLED": True,
            "AUTO_SYNC_TRIGGER": "interval",
            "AUTO_SYNC_INTERVAL": 1,
            "KAVITA_URL": "http://kavita.test",
            "KAVITA_API_KEY": "key",
        },
    )
    assert "start" not in calls
    assert "stop" in calls
