"""C88 C0 — clés mapping : overlay load_config, Light mode, save sidebar."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


MAP_KEY = "FIELD_PROVIDER_MAP_MANGA"
DEFAULT_KEY = "FIELD_MAPPING_DEFAULT_MANGA"


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    import config_manager

    monkeypatch.setattr(config_manager, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(tmp_path / "config.json"))
    for key in (
        "UI_SHOW_FIELD_MAPPING",
        "FIELD_MAPPING_ENABLED",
        "UI_LANG",
        "KAVITA_URL",
        "KAVITA_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    return config_manager


@pytest.fixture
def config_client(tmp_path, monkeypatch, isolated_db):
    import config_manager
    from routes.config import config_bp
    from flask import Flask

    monkeypatch.setattr(config_manager, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(tmp_path / "config.json"))
    for key in ("KAVITA_URL", "KAVITA_API_KEY", "UI_LANG"):
        monkeypatch.delenv(key, raising=False)
    config_manager.save_config({
        "SECRET_KEY": "test-secret",
        "WEBHOOK_TOKEN": "wh",
        "KAVITA_URL": "",
        "KAVITA_API_KEY": "",
        "UI_LANG": "fr",
        MAP_KEY: {"cover": "ANILIST"},
        DEFAULT_KEY: "MAL",
        "FIELD_MAPPING_ENABLED": True,
        "UI_SHOW_FIELD_MAPPING": True,
    })

    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    app.register_blueprint(config_bp)
    return app.test_client(), config_manager


def test_mapping_defaults_are_off_and_cascade(isolated_config):
    config = isolated_config.load_config()
    assert config["UI_SHOW_FIELD_MAPPING"] is False
    assert config["FIELD_MAPPING_ENABLED"] is False
    assert config[DEFAULT_KEY] == "CASCADE"
    assert config[MAP_KEY] == {}


def test_maps_overlay_from_file(isolated_config):
    with open(isolated_config.CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "SECRET_KEY": "s",
            "WEBHOOK_TOKEN": "w",
            MAP_KEY: {"staff": "mal", "cover": "ANILIST"},
            DEFAULT_KEY: "comicvine",
        }, f)
    config = isolated_config.load_config()
    assert config[MAP_KEY]["staff"] == "MAL"
    assert config[MAP_KEY]["cover"] == "ANILIST"
    assert config[DEFAULT_KEY] == "COMICVINE"


def test_hiding_mapping_disables_it():
    from config_manager import apply_light_mode

    config = {"UI_SHOW_FIELD_MAPPING": False, "FIELD_MAPPING_ENABLED": True}
    apply_light_mode(config)
    assert config["FIELD_MAPPING_ENABLED"] is False


def test_sidebar_save_without_maps_keeps_maps(config_client):
    client, cm = config_client
    res = client.post("/save-config", data={"AUTO_COVER": "true"})
    assert res.status_code == 200
    with open(cm.CONFIG_FILE, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved[MAP_KEY]["cover"] == "ANILIST"
    assert saved[DEFAULT_KEY] == "MAL"
    assert saved["FIELD_MAPPING_ENABLED"] is True


def test_partial_form_does_not_hide_mapping(config_client):
    client, cm = config_client
    res = client.post("/save-config", data={"AUTO_COVER": "true"})
    assert res.status_code == 200
    with open(cm.CONFIG_FILE, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["UI_SHOW_FIELD_MAPPING"] is True
    assert saved["FIELD_MAPPING_ENABLED"] is True


ROOT = Path(__file__).resolve().parents[1]
PLAN_IDS = (
    "MANGA",
    "COMIC",
    "BOOK",
    "COMICFLEXIBLE",
    "COMICFLEXIBLE_MANGA",
)


def _fake_usable(_config, fetch_lt):
    if fetch_lt == "Comic":
        return ["COMICVINE", "ANILIST"]
    if fetch_lt == "Book":
        return ["GOOGLEBOOKS"]
    return ["ANILIST", "MAL"]


def test_get_field_mapping_returns_five_plans(config_client, monkeypatch):
    monkeypatch.setattr("routes.config.usable_ids_for_fetch_type", _fake_usable)
    monkeypatch.setattr("services.field_mapping.usable_ids_for_fetch_type", _fake_usable)
    monkeypatch.setattr(
        "routes.config.dropdown_providers",
        lambda config, fetch_lt: [{"id": pid, "display_name": pid} for pid in _fake_usable(config, fetch_lt)],
    )
    client, _cm = config_client
    res = client.get("/api/config/field-mapping")
    assert res.status_code == 200
    body = res.get_json()
    assert body["success"] is True
    assert set(body["plans"]) == set(PLAN_IDS)
    assert body["plans"]["MANGA"]["fetch_library_type"] == "Manga"
    assert body["plans"]["COMIC"]["fetch_library_type"] == "Comic"
    assert body["plans"]["BOOK"]["fetch_library_type"] == "Book"
    assert body["plans"]["COMICFLEXIBLE"]["fetch_library_type"] == "Comic"
    assert body["plans"]["COMICFLEXIBLE_MANGA"]["fetch_library_type"] == "Manga"
    assert body["plans"]["MANGA"]["default"] == "MAL"
    assert body["plans"]["MANGA"]["overrides"]["cover"] == "ANILIST"


def test_get_field_mapping_never_asks_comicflexible(config_client, monkeypatch):
    from scrapers import ScraperRegistry

    real = ScraperRegistry.get_by_type

    def wrapped(lib_type, **kwargs):
        assert lib_type != "ComicFlexible"
        return real(lib_type, **kwargs)

    monkeypatch.setattr(ScraperRegistry, "get_by_type", wrapped)
    client, _cm = config_client
    res = client.get("/api/config/field-mapping")
    assert res.status_code == 200
    assert res.get_json()["plans"]["COMICFLEXIBLE"]["fetch_library_type"] == "Comic"


def test_post_field_mapping_parses_and_persists(config_client, monkeypatch):
    monkeypatch.setattr("routes.config.usable_ids_for_fetch_type", _fake_usable)
    monkeypatch.setattr("services.field_mapping.usable_ids_for_fetch_type", _fake_usable)
    client, cm = config_client
    payload = {
        "plans": {
            "MANGA": {
                "default": "CASCADE",
                "overrides": {"cover": "ANILIST", "staff": "MAL", "title": "MAL", "format": "MAL"},
            },
            "COMIC": {"default": "COMICVINE", "overrides": {"publisher": "ANILIST"}},
            "BOOK": {"default": "GOOGLEBOOKS", "overrides": {}},
            "COMICFLEXIBLE": {"default": "CASCADE", "overrides": {"summary": "COMICVINE"}},
            "COMICFLEXIBLE_MANGA": {"default": "ANILIST", "overrides": {"genres": "NOPE"}},
        }
    }
    res = client.post("/api/config/field-mapping", json=payload)
    assert res.status_code == 200
    assert res.get_json()["success"] is True
    saved = json.loads(Path(cm.CONFIG_FILE).read_text(encoding="utf-8"))
    assert saved["FIELD_MAPPING_DEFAULT_MANGA"] == "CASCADE"
    assert saved["FIELD_PROVIDER_MAP_MANGA"] == {"cover": "ANILIST", "staff": "MAL"}
    assert "title" not in saved["FIELD_PROVIDER_MAP_MANGA"]
    assert saved["FIELD_MAPPING_DEFAULT_COMIC"] == "COMICVINE"
    assert saved["FIELD_PROVIDER_MAP_COMIC"] == {"publisher": "ANILIST"}
    assert saved["FIELD_MAPPING_DEFAULT_BOOK"] == "GOOGLEBOOKS"
    assert saved["FIELD_PROVIDER_MAP_COMICFLEXIBLE"] == {"summary": "COMICVINE"}
    assert saved["FIELD_MAPPING_DEFAULT_COMICFLEXIBLE_MANGA"] == "ANILIST"
    assert saved["FIELD_PROVIDER_MAP_COMICFLEXIBLE_MANGA"] == {}


def test_post_field_mapping_rejects_non_json(config_client):
    client, _cm = config_client
    res = client.post("/api/config/field-mapping", data="nope")
    assert res.status_code == 400


def test_sidebar_save_after_mapping_post_keeps_maps(config_client, monkeypatch):
    monkeypatch.setattr("routes.config.usable_ids_for_fetch_type", _fake_usable)
    monkeypatch.setattr("services.field_mapping.usable_ids_for_fetch_type", _fake_usable)
    client, cm = config_client
    client.post("/api/config/field-mapping", json={
        "plans": {"MANGA": {"default": "ANILIST", "overrides": {"staff": "MAL"}}},
    })
    res = client.post("/save-config", data={"AUTO_COVER": "true"})
    assert res.status_code == 200
    saved = json.loads(Path(cm.CONFIG_FILE).read_text(encoding="utf-8"))
    assert saved["FIELD_MAPPING_DEFAULT_MANGA"] == "ANILIST"
    assert saved["FIELD_PROVIDER_MAP_MANGA"]["staff"] == "MAL"


def test_modal_skeleton_matches_g1_contract():
    html = (ROOT / "templates" / "partials" / "_field_mapping_modal.html").read_text(encoding="utf-8")
    assert html.count("class=\"fm-tab") >= 4
    assert "fm_wave('MANGA'" in html
    assert "fm_wave('COMIC'" in html
    assert "fm_wave('BOOK'" in html
    assert "fm_wave('COMICFLEXIBLE'" in html
    assert "fm_wave('COMICFLEXIBLE_MANGA'" in html
    assert 'data-plan="{{ plan }}"' in html
    assert "cascade-block--{{ block }}" in html
    assert "fm_wave('COMICFLEXIBLE', 'comic'" in html
    assert "fm_wave('COMICFLEXIBLE_MANGA', 'manga'" in html
    assert "fm_wave('BOOK', 'book'" in html
    for field in (
        "cover", "year", "status", "publisher", "age_rating",
        "localized_name", "summary", "genres", "tags", "staff",
    ):
        assert f"('{field}'" in html
    assert "('title'" not in html
    assert "('format'" not in html
    assert 'data-field="{{ field }}"' in html
    assert 'id="fmSaveBtn" disabled' in html
    css = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")
    for cls in (".fm-tabs", ".fm-grid", ".fm-field.is-override", ".modal-header--mapping"):
        assert cls in css
    js = (ROOT / "static" / "js" / "field_mapping.js").read_text(encoding="utf-8")
    assert "function loadFieldMapping" in js
    assert "function fillWaveBlock" in js
    assert "function saveFieldMapping" in js
    assert "_fmReady" in js
    assert "if (!_fmReady) return;" in js
    assert "innerHTML" not in js
    index = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert "js/field_mapping.js" in index
    assert "js/config.js" in index
    assert index.index("js/config.js") < index.index("js/field_mapping.js")
