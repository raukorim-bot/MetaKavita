"""C96 T1 — clés Auto-sync, migration INTERVAL, radios Config, save == 'true'."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config_env(tmp_path, monkeypatch):
    import config_manager

    monkeypatch.setattr(config_manager, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(config_manager, "_admin_password_env_warned", False)
    for key in (
        "AUTO_SYNC_INTERVAL", "AUTO_SYNC_ENABLED", "AUTO_SYNC_TRIGGER",
        "AUTO_SYNC_MODE", "AUTO_SYNC_CATCHUP_HOURS", "AUTO_SYNC_FORCE_UPDATE",
    ):
        monkeypatch.delenv(key, raising=False)
    return config_manager


@pytest.fixture
def config_client(tmp_path, monkeypatch, isolated_db):
    import config_manager
    from routes.config import config_bp

    monkeypatch.setattr(config_manager, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(tmp_path / "config.json"))
    for key in (
        "KAVITA_URL", "KAVITA_API_KEY", "UI_LANG",
        "AUTO_SYNC_INTERVAL", "AUTO_SYNC_ENABLED", "AUTO_SYNC_TRIGGER",
        "AUTO_SYNC_MODE", "AUTO_SYNC_CATCHUP_HOURS", "AUTO_SYNC_FORCE_UPDATE",
    ):
        monkeypatch.delenv(key, raising=False)

    config_manager.save_config({
        "SECRET_KEY": "test-secret",
        "WEBHOOK_TOKEN": "wh",
        "KAVITA_URL": "http://kavita.test",
        "KAVITA_API_KEY": "k",
        "UI_LANG": "fr",
        "AUTO_SYNC_INTERVAL": 360,
        "AUTO_SYNC_ENABLED": True,
        "AUTO_SYNC_TRIGGER": "interval",
        "AUTO_SYNC_MODE": "auto",
        "AUTO_SYNC_CATCHUP_HOURS": 24,
        "AUTO_SYNC_FORCE_UPDATE": False,
    })

    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    app.register_blueprint(config_bp)
    return app.test_client(), config_manager


def _saved(config_manager):
    with open(config_manager.CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def test_legacy_interval_positive_migrates_to_enabled_interval(config_env):
    config_env.save_config({
        "SECRET_KEY": "k",
        "WEBHOOK_TOKEN": "w",
        "AUTO_SYNC_INTERVAL": 360,
    })
    cfg = config_env.load_config()
    assert cfg["AUTO_SYNC_ENABLED"] is True
    assert cfg["AUTO_SYNC_TRIGGER"] == "interval"
    assert int(cfg["AUTO_SYNC_INTERVAL"]) == 360
    assert cfg["AUTO_SYNC_TRIGGER"] != "scan"
    assert "AUTO_SYNC_ENABLED" not in _saved(config_env)


def test_legacy_interval_zero_migrates_to_disabled(config_env):
    config_env.save_config({
        "SECRET_KEY": "k",
        "WEBHOOK_TOKEN": "w",
        "AUTO_SYNC_INTERVAL": 0,
    })
    cfg = config_env.load_config()
    assert cfg["AUTO_SYNC_ENABLED"] is False
    assert cfg["AUTO_SYNC_TRIGGER"] == "interval"


def test_file_enabled_false_keeps_interval_minutes(config_env):
    config_env.save_config({
        "SECRET_KEY": "k",
        "WEBHOOK_TOKEN": "w",
        "AUTO_SYNC_INTERVAL": 360,
        "AUTO_SYNC_ENABLED": False,
        "AUTO_SYNC_TRIGGER": "interval",
    })
    cfg = config_env.load_config()
    assert cfg["AUTO_SYNC_ENABLED"] is False
    assert int(cfg["AUTO_SYNC_INTERVAL"]) == 360


def test_file_wins_over_env_for_enabled(config_env, monkeypatch):
    monkeypatch.setenv("AUTO_SYNC_ENABLED", "true")
    config_env.save_config({
        "SECRET_KEY": "k",
        "WEBHOOK_TOKEN": "w",
        "AUTO_SYNC_ENABLED": False,
        "AUTO_SYNC_INTERVAL": 360,
    })
    assert config_env.load_config()["AUTO_SYNC_ENABLED"] is False


def test_env_seeds_catchup_hours_when_absent_from_file(config_env, monkeypatch):
    monkeypatch.setenv("AUTO_SYNC_CATCHUP_HOURS", "0")
    config_env.save_config({"SECRET_KEY": "k", "WEBHOOK_TOKEN": "w"})
    assert config_env.load_config()["AUTO_SYNC_CATCHUP_HOURS"] == 0


def test_save_config_round_trip_on_and_off(config_client):
    client, cm = config_client

    res = client.post("/save-config", data={
        "AUTO_SYNC_ENABLED": "true",
        "AUTO_SYNC_TRIGGER": "interval",
        "AUTO_SYNC_MODE": "review",
        "AUTO_SYNC_INTERVAL": "90",
        "AUTO_SYNC_CATCHUP_HOURS": "24",
        "AUTO_SYNC_FORCE_UPDATE": "false",
    })
    assert res.status_code == 200
    saved = _saved(cm)
    assert saved["AUTO_SYNC_ENABLED"] is True
    assert saved["AUTO_SYNC_TRIGGER"] == "interval"
    assert saved["AUTO_SYNC_MODE"] == "review"
    assert int(saved["AUTO_SYNC_INTERVAL"]) == 90

    res = client.post("/save-config", data={
        "AUTO_SYNC_ENABLED": "false",
        "AUTO_SYNC_TRIGGER": "interval",
        "AUTO_SYNC_MODE": "review",
        "AUTO_SYNC_INTERVAL": "90",
        "AUTO_SYNC_CATCHUP_HOURS": "24",
        "AUTO_SYNC_FORCE_UPDATE": "false",
    })
    assert res.status_code == 200
    saved = _saved(cm)
    assert saved["AUTO_SYNC_ENABLED"] is False
    assert int(saved["AUTO_SYNC_INTERVAL"]) == 90


def test_unchecked_enabled_is_false_not_truthy_string(config_client):
    """Même piège que les autres cases Config : absent/'false' ≠ 'true'."""
    client, cm = config_client
    res = client.post("/save-config", data={
        "AUTO_SYNC_ENABLED": "false",
        "AUTO_SYNC_TRIGGER": "scan",
        "AUTO_SYNC_MODE": "auto",
        "AUTO_SYNC_INTERVAL": "360",
        "AUTO_SYNC_CATCHUP_HOURS": "24",
    })
    assert res.status_code == 200
    assert _saved(cm)["AUTO_SYNC_ENABLED"] is False
    assert _saved(cm)["AUTO_SYNC_TRIGGER"] == "scan"


def test_catchup_zero_is_persisted(config_client):
    client, cm = config_client
    res = client.post("/save-config", data={
        "AUTO_SYNC_ENABLED": "true",
        "AUTO_SYNC_TRIGGER": "scan",
        "AUTO_SYNC_MODE": "auto",
        "AUTO_SYNC_INTERVAL": "360",
        "AUTO_SYNC_CATCHUP_HOURS": "0",
        "AUTO_SYNC_FORCE_UPDATE": "false",
    })
    assert res.status_code == 200
    assert _saved(cm)["AUTO_SYNC_CATCHUP_HOURS"] == 0


def test_interval_zero_while_enabled_clamps_to_one(config_client):
    client, cm = config_client
    res = client.post("/save-config", data={
        "AUTO_SYNC_ENABLED": "true",
        "AUTO_SYNC_TRIGGER": "interval",
        "AUTO_SYNC_MODE": "auto",
        "AUTO_SYNC_INTERVAL": "0",
    })
    assert res.status_code == 200
    assert int(_saved(cm)["AUTO_SYNC_INTERVAL"]) == 1


def test_partial_save_does_not_clobber_auto_sync(config_client):
    client, cm = config_client
    res = client.post("/save-config", data={"AUTO_COVER": "true"})
    assert res.status_code == 200
    saved = _saved(cm)
    assert saved["AUTO_SYNC_ENABLED"] is True
    assert int(saved["AUTO_SYNC_INTERVAL"]) == 360
    assert saved["AUTO_COVER"] is True


def test_scan_trigger_does_not_poll_interval(config_env):
    from services.background_tasks import _auto_sync_should_poll_interval

    assert _auto_sync_should_poll_interval({"AUTO_SYNC_INTERVAL": 60}) is True
    assert _auto_sync_should_poll_interval({
        "AUTO_SYNC_INTERVAL": 60, "AUTO_SYNC_ENABLED": True,
        "AUTO_SYNC_TRIGGER": "scan",
    }) is False
    assert _auto_sync_should_poll_interval({
        "AUTO_SYNC_INTERVAL": 60, "AUTO_SYNC_ENABLED": False,
        "AUTO_SYNC_TRIGGER": "interval",
    }) is False
    assert _auto_sync_should_poll_interval({
        "AUTO_SYNC_INTERVAL": 60, "AUTO_SYNC_ENABLED": True,
        "AUTO_SYNC_TRIGGER": "interval",
    }) is True


def test_config_js_appends_enabled_like_other_checkboxes():
    js = (ROOT / "static" / "js" / "config.js").read_text(encoding="utf-8")
    assert "function toggleAutoSyncCard" in js
    assert "AUTO_SYNC_ENABLED" in js
    assert "AUTO_SYNC_FORCE_UPDATE" in js


def test_config_modal_has_xor_radios_and_hides_review_in_light_mode():
    from jinja2 import Environment, FileSystemLoader
    from translations import translations

    env = Environment(loader=FileSystemLoader(str(ROOT / "templates")))
    t = translations["fr"]
    html = env.get_template("partials/_config_modal.html").render(
        t=t,
        config={
            "AUTO_SYNC_ENABLED": True,
            "AUTO_SYNC_TRIGGER": "interval",
            "AUTO_SYNC_MODE": "auto",
            "UI_SHOW_MANUAL_REVIEW": False,
        },
        scrapers_with_keys=[],
        scraper_has_api_key={},
        all_libraries=[],
        disabled_library_ids=[],
        request={"script_root": ""},
    )
    assert 'name="AUTO_SYNC_TRIGGER"' in html
    assert 'value="scan"' in html
    assert 'value="interval"' in html
    assert 'value="review"' not in html
    assert 'value="super"' not in html
    assert "toggleAutoSyncCard" in html
    interval_tag = html.split('id="config_auto_sync_interval"', 1)[1].split(">", 1)[0]
    assert 'min="0"' in interval_tag
    assert 'min="1"' not in interval_tag


def test_toggle_relaxes_interval_min_when_auto_sync_is_off():
    """min=1 sur un 0 hérité bloque le submit natif avant onsubmit : pas de
    saveConfig, pas de toast, pas de reload — alors que l'interrupteur est off."""
    js = (ROOT / "static" / "js" / "config.js").read_text(encoding="utf-8")
    fn = js.split("function toggleAutoSyncCard", 1)[1].split("\nfunction ", 1)[0]
    assert "config_auto_sync_interval" in fn
    assert "minutesRequired ? '1' : '0'" in fn
