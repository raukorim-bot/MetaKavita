"""BF83 — INFO logs for CSRF reject and lockout-already-active rejects."""
import logging

import auth_manager
from translations import translations

LOG_KEYS = [
    "log_auth_lockout_reject",
    "log_security_csrf_rejected",
]


def test_bf83_log_keys_parity_and_nonempty():
    assert set(translations["fr"]) == set(translations["en"])
    for key in LOG_KEYS:
        assert key in translations["fr"]
        assert key in translations["en"]
        assert translations["fr"][key].strip()
        assert translations["en"][key].strip()
    assert "verrouillage" in translations["fr"]["log_auth_lockout_reject"].lower()
    assert "lockout" in translations["en"]["log_auth_lockout_reject"].lower()
    assert "CSRF" in translations["fr"]["log_security_csrf_rejected"]
    assert "CSRF" in translations["en"]["log_security_csrf_rejected"]


def test_log_lockout_reject_info_no_counter_bump(monkeypatch, caplog):
    auth_manager.reset_lockout_state()
    monkeypatch.setattr(
        auth_manager,
        "get_ui_translations",
        lambda config=None, ui_lang=None: translations["en"],
    )
    monkeypatch.setattr(auth_manager, "_client_ip", lambda: "203.0.113.50")
    with caplog.at_level(logging.INFO):
        auth_manager.log_lockout_reject(username="alice", remaining_seconds=600)
    joined = " ".join(caplog.messages)
    assert "lockout" in joined.lower()
    assert "alice" in joined
    assert "203.0.113.50" in joined
    assert "10" in joined  # ~10 min from 600s
    assert "203.0.113.50" not in auth_manager._failed_attempts
    assert not any(r.levelno >= logging.WARNING for r in caplog.records)


def test_csrf_reject_logs_info(isolated_db, monkeypatch, caplog):
    from flask import Flask

    from csrf_utils import csrf_protect_before_request
    from routes.auth import auth_bp

    monkeypatch.delenv("ADMIN_PASSWORD_HASH", raising=False)
    auth_manager.create_user("admin", "correct horse")
    monkeypatch.setattr(
        "csrf_utils.get_ui_translations",
        lambda config=None, ui_lang=None: translations["en"],
    )

    test_app = Flask(__name__, template_folder="../templates", static_folder="../static")
    test_app.config.update(TESTING=False, SECRET_KEY="test-secret")
    test_app.register_blueprint(auth_bp)
    test_app.before_request(csrf_protect_before_request)

    with caplog.at_level(logging.INFO):
        res = test_app.test_client().post(
            "/login", data={"username": "admin", "password": "correct horse"}
        )
    assert res.status_code == 403
    joined = " ".join(caplog.messages)
    assert "CSRF" in joined
    assert "/login" in joined
    assert "admin" in joined
    # Never leak a token
    assert "csrf_token" not in joined.lower() or "CSRF rejected" in joined


def test_french_lockout_reject_message(monkeypatch, caplog):
    auth_manager.reset_lockout_state()
    monkeypatch.setattr(
        auth_manager,
        "get_ui_translations",
        lambda config=None, ui_lang=None: translations["fr"],
    )
    monkeypatch.setattr(auth_manager, "_client_ip", lambda: "127.0.0.1")
    with caplog.at_level(logging.INFO):
        auth_manager.log_lockout_reject(username="ops", remaining_seconds=90)
    joined = " ".join(caplog.messages)
    assert "verrouillage" in joined.lower() or "refusée" in joined.lower()
    assert "lockout" not in joined.lower()
