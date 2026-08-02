"""BF82 — INFO on every failed login attempt (username + IP + counter)."""
import logging

import auth_manager
from translations import translations

LOG_KEY = "log_auth_failed_attempt"


def test_bf82_log_key_parity_and_nonempty():
    assert set(translations["fr"]) == set(translations["en"])
    assert LOG_KEY in translations["fr"]
    assert LOG_KEY in translations["en"]
    assert translations["fr"][LOG_KEY].strip()
    assert translations["en"][LOG_KEY].strip()
    assert "Échec" in translations["fr"][LOG_KEY] or "échec" in translations["fr"][LOG_KEY].lower()
    assert "Failed login" in translations["en"][LOG_KEY]


def test_register_failed_attempt_logs_info_each_try(monkeypatch, caplog):
    auth_manager.reset_lockout_state()
    monkeypatch.setattr(
        auth_manager,
        "get_ui_translations",
        lambda config=None, ui_lang=None: translations["en"],
    )
    with caplog.at_level(logging.INFO):
        n = auth_manager.register_failed_attempt(ip="203.0.113.9", username="alice")
    assert n == 1
    joined = " ".join(caplog.messages)
    assert "Failed login" in joined
    assert "alice" in joined
    assert "203.0.113.9" in joined
    assert "1/5" in joined or "1/" in joined
    assert not any(r.levelno >= logging.WARNING for r in caplog.records)


def test_fifth_attempt_info_then_lockout_warning(monkeypatch, caplog):
    auth_manager.reset_lockout_state()
    monkeypatch.setattr(
        auth_manager,
        "get_ui_translations",
        lambda config=None, ui_lang=None: translations["en"],
    )
    with caplog.at_level(logging.INFO):
        for i in range(auth_manager.MAX_FAILED_ATTEMPTS - 1):
            auth_manager.register_failed_attempt(ip="203.0.113.10", username="bob")
        auth_manager.register_failed_attempt(ip="203.0.113.10", username="bob")
    infos = [r for r in caplog.records if r.levelno == logging.INFO and "Failed login" in r.getMessage()]
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(infos) == auth_manager.MAX_FAILED_ATTEMPTS
    assert len(warnings) == 1
    assert "lockout" in warnings[0].getMessage().lower() or "failed login attempts" in warnings[0].getMessage().lower()


def test_username_optional_and_sanitized(monkeypatch, caplog):
    auth_manager.reset_lockout_state()
    monkeypatch.setattr(
        auth_manager,
        "get_ui_translations",
        lambda config=None, ui_lang=None: translations["en"],
    )
    with caplog.at_level(logging.INFO):
        auth_manager.register_failed_attempt(ip="10.0.0.1")
        auth_manager.register_failed_attempt(
            ip="10.0.0.2",
            username="x" * 100 + "\nsecret",
        )
    assert any("'-'" in r.getMessage() for r in caplog.records)
    # Truncated to 64; newline stripped — never raw multiline password-like payload
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "\nsecret" not in joined
    assert "x" * 64 in joined
    assert "x" * 65 not in joined


def test_french_failed_attempt_message(monkeypatch, caplog):
    auth_manager.reset_lockout_state()
    monkeypatch.setattr(
        auth_manager,
        "get_ui_translations",
        lambda config=None, ui_lang=None: translations["fr"],
    )
    with caplog.at_level(logging.INFO):
        auth_manager.register_failed_attempt(ip="127.0.0.1", username="ops")
    joined = " ".join(caplog.messages)
    assert "Échec" in joined or "échec" in joined.lower()
    assert "Failed login" not in joined
