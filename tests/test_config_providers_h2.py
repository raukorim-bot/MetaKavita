"""
Non-régression : defaults/env Comic/Book providers + RESET_CONTEXT_ON_FORCE (H2).
"""
import json


def test_load_config_includes_comic_book_defaults(tmp_path, monkeypatch):
    import config_manager

    monkeypatch.setattr(config_manager, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.delenv("COMIC_PROVIDER_1", raising=False)
    monkeypatch.delenv("BOOK_PROVIDER_1", raising=False)
    monkeypatch.delenv("RESET_CONTEXT_ON_FORCE", raising=False)

    cfg = config_manager.load_config()
    assert cfg["COMIC_PROVIDER_1"] == "COMICVINE"
    assert cfg["BOOK_PROVIDER_1"] == "GOOGLEBOOKS"
    assert cfg["RESET_CONTEXT_ON_FORCE"] is False


def test_load_config_respects_env_for_comic_and_reset(tmp_path, monkeypatch):
    import config_manager

    monkeypatch.setattr(config_manager, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(tmp_path / "config.json"))
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")

    monkeypatch.setenv("COMIC_PROVIDER_1", "BEDETHEQUE")
    monkeypatch.setenv("BOOK_PROVIDER_2", "HARDCOVER")
    monkeypatch.setenv("RESET_CONTEXT_ON_FORCE", "true")

    cfg = config_manager.load_config()
    assert cfg["COMIC_PROVIDER_1"] == "BEDETHEQUE"
    assert cfg["BOOK_PROVIDER_2"] == "HARDCOVER"
    assert cfg["RESET_CONTEXT_ON_FORCE"] is True
