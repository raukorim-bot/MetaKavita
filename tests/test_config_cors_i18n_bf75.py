"""BF75 — logs Config / CORS suivent UI_LANG (Live Logs)."""
import logging

import config_manager
from cors_config import log_cors_config
from translations import get_ui_translations, translations


LOG_KEYS = [
    "log_yes",
    "log_no",
    "log_empty",
    "log_config_file",
    "log_config_unreadable",
    "log_config_bak_written",
    "log_config_bak_failed",
    "log_config_admin_password_env",
    "log_config_sync_libs_empty",
    "log_config_reload_libs_fail",
    "log_config_persist_fail",
    "log_config_save_ok",
    "log_config_manual_purged",
    "log_config_manual_purge_fail",
    "log_config_confirm_purged",
    "log_config_confirm_purge_fail",
    "log_config_kavita_probe_fail",
    "log_webhook_token_regenerated",
    "log_cors_star_ignored",
    "log_cors_whitelist",
    "log_cors_same_origin",
]


def test_log_keys_parity_and_nonempty():
    assert set(translations["fr"]) == set(translations["en"])
    for key in LOG_KEYS:
        assert key in translations["fr"]
        assert key in translations["en"]
        assert translations["fr"][key].strip()
        assert translations["en"][key].strip()


def test_get_ui_translations_explicit_lang_no_load():
    fr = get_ui_translations(ui_lang="fr")
    en = get_ui_translations(ui_lang="en")
    assert "Fichier de configuration" in fr["log_config_file"]
    assert "Configuration file" in en["log_config_file"]
    assert "clé_API" in fr["log_config_save_ok"]
    assert "API_key" in en["log_config_save_ok"]


def test_get_ui_translations_from_config_dict():
    t = get_ui_translations(config={"UI_LANG": "en"})
    assert t["log_yes"] == "yes"
    assert t["log_no"] == "no"


def test_log_cors_same_origin_english(caplog, monkeypatch):
    monkeypatch.setattr(
        "translations.get_ui_translations",
        lambda config=None, ui_lang=None: translations["en"],
    )
    with caplog.at_level(logging.INFO):
        log_cors_config([], star_ignored=False)
    joined = " ".join(caplog.messages)
    assert "Same-Origin" in joined
    assert "aucune origine" not in joined


def test_log_cors_whitelist_and_star_french(caplog, monkeypatch):
    monkeypatch.setattr(
        "translations.get_ui_translations",
        lambda config=None, ui_lang=None: translations["fr"],
    )
    with caplog.at_level(logging.INFO):
        log_cors_config(["https://a.example"], star_ignored=True)
    joined = " ".join(caplog.messages)
    assert "Whitelist active" in joined
    assert "ignorée" in joined or "ignor" in joined.lower()


def test_load_config_path_log_follows_ui_lang(tmp_path, monkeypatch, caplog):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"UI_LANG": "en", "SECRET_KEY": "k", "WEBHOOK_TOKEN": "w"}', encoding="utf-8")
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(cfg))
    monkeypatch.setattr(config_manager, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config_manager, "_logged_config_path", False)

    with caplog.at_level(logging.INFO):
        config_manager.load_config()

    joined = " ".join(caplog.messages)
    assert "Configuration file:" in joined
    assert "Fichier de configuration" not in joined
