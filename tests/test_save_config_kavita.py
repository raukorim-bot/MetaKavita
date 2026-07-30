"""
Non-régression : setup frais via la modal Config doit persister KAVITA_URL / clé.

Régression observée en 1.6.1 : migration 1.6.0→1.6.1 OK (clés déjà dans
config.json), mais un setup neuf via la modal semblait « ne pas écrire ».
Causes croisées : sentinel `********` dans le champ password + saves sidebar
qui renvoyaient un champ vide/autofill et pouvaient écraser ou ne jamais poser
la clé ; champ secret désormais toujours vide à l'affichage, vide = conserver.
"""
import json
import os

import pytest
from flask import Flask


@pytest.fixture
def config_client(tmp_path, monkeypatch, isolated_db):
    import config_manager
    from routes.config import config_bp

    monkeypatch.setattr(config_manager, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(tmp_path / "config.json"))
    for key in ("KAVITA_URL", "KAVITA_API_KEY", "UI_LANG"):
        monkeypatch.delenv(key, raising=False)

    # Seed minimal (secrets) comme un premier boot après /setup
    config_manager.save_config({
        "SECRET_KEY": "test-secret",
        "WEBHOOK_TOKEN": "wh",
        "KAVITA_URL": "",
        "KAVITA_API_KEY": "",
        "UI_LANG": "fr",
    })

    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    app.register_blueprint(config_bp)
    return app.test_client(), config_manager


def _read_file(config_manager):
    with open(config_manager.CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def test_fresh_setup_persists_kavita_url_and_api_key(config_client, mocker):
    client, cm = config_client
    mocker.patch("routes.config.KavitaAPI.authenticate", return_value=True)

    res = client.post("/save-config", data={
        "KAVITA_URL": "http://host.docker.internal:5001",
        "KAVITA_API_KEY": "fresh-kavita-key",
        "UI_LANG": "fr",
        "TRANSLATION_PROVIDER": "GOOGLE",
        "TARGET_LANG": "FR",
        "PUBLISHER_PREFERENCE": "LOCALIZED",
        "LOCALIZED_TITLE_MODE": "all",
        "SYNC_LIBRARIES_PRESENT": "1",
    })
    assert res.status_code == 200
    body = res.get_json()
    assert body["success"] is True
    assert body["has_kavita_api_key"] is True
    assert body["kavita_url"] == "http://host.docker.internal:5001"
    assert body["kavita_ok"] is True

    saved = _read_file(cm)
    assert saved["KAVITA_URL"] == "http://host.docker.internal:5001"
    assert saved["KAVITA_API_KEY"] == "fresh-kavita-key"
    # Chemin absolu (pas de dépendance au cwd)
    assert os.path.isabs(cm.CONFIG_FILE)
    assert os.path.isfile(cm.CONFIG_FILE)


def test_empty_api_key_field_keeps_existing_secret(config_client, mocker):
    """Simulate sidebar/modal save with blank password field (new UI contract)."""
    client, cm = config_client
    mocker.patch("routes.config.KavitaAPI.authenticate", return_value=True)

    cm.save_config({
        **_read_file(cm),
        "KAVITA_URL": "http://host.docker.internal:5001",
        "KAVITA_API_KEY": "keep-me",
    })

    res = client.post("/save-config", data={
        "KAVITA_URL": "http://host.docker.internal:5001",
        "KAVITA_API_KEY": "",  # champ vide = conserver
        "UI_LANG": "fr",
        "TRANSLATION_PROVIDER": "GOOGLE",
        "TARGET_LANG": "FR",
        "PUBLISHER_PREFERENCE": "LOCALIZED",
        "LOCALIZED_TITLE_MODE": "all",
        "SMART_SCORING": "true",
        "SYNC_LIBRARIES_PRESENT": "1",
    })
    assert res.status_code == 200
    assert res.get_json()["has_kavita_api_key"] is True
    assert _read_file(cm)["KAVITA_API_KEY"] == "keep-me"


def test_sentinel_stars_also_keeps_existing_secret(config_client, mocker):
    client, cm = config_client
    mocker.patch("routes.config.KavitaAPI.authenticate", return_value=True)
    cm.save_config({
        **_read_file(cm),
        "KAVITA_URL": "http://kavita:5000",
        "KAVITA_API_KEY": "legacy-stars",
    })

    res = client.post("/save-config", data={
        "KAVITA_URL": "http://kavita:5000",
        "KAVITA_API_KEY": "********",
        "UI_LANG": "en",
        "TRANSLATION_PROVIDER": "GOOGLE",
        "TARGET_LANG": "EN",
        "PUBLISHER_PREFERENCE": "LOCALIZED",
        "LOCALIZED_TITLE_MODE": "all",
        "SYNC_LIBRARIES_PRESENT": "1",
    })
    assert res.status_code == 200
    assert _read_file(cm)["KAVITA_API_KEY"] == "legacy-stars"
