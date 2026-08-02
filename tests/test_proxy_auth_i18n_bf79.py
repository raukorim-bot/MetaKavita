"""BF79 — Security/Auth TRUSTED_PROXY / lockout Live Logs follow UI_LANG (#26)."""
import logging

import auth_manager
from translations import get_ui_translations, translations

LOG_KEYS = [
    "log_security_proxy_count_zero",
    "log_security_secret_key_ephemeral",
    "log_auth_proxy_count_unrecognized",
    "log_security_lockout_ip",
    "log_security_lockout_global",
]


def test_bf79_log_keys_parity_and_nonempty():
    assert set(translations["fr"]) == set(translations["en"])
    for key in LOG_KEYS:
        assert key in translations["fr"]
        assert key in translations["en"]
        assert translations["fr"][key].strip()
        assert translations["en"][key].strip()
    assert "en-têtes" in translations["fr"]["log_security_proxy_count_zero"]
    assert "X-Forwarded-*" in translations["en"]["log_security_proxy_count_zero"]
    assert "non reconnu" in translations["fr"]["log_auth_proxy_count_unrecognized"]
    assert "unrecognized" in translations["en"]["log_auth_proxy_count_unrecognized"]


def test_trusted_proxy_unrecognized_logs_english(monkeypatch, caplog):
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "abc")
    monkeypatch.setattr(
        auth_manager,
        "get_ui_translations",
        lambda config=None, ui_lang=None: translations["en"],
    )
    with caplog.at_level(logging.WARNING):
        assert auth_manager.get_trusted_proxy_count() == 1
    joined = " ".join(caplog.messages)
    assert "unrecognized" in joined
    assert "non reconnu" not in joined


def test_trusted_proxy_unrecognized_logs_french(monkeypatch, caplog):
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "2")
    monkeypatch.setattr(
        auth_manager,
        "get_ui_translations",
        lambda config=None, ui_lang=None: translations["fr"],
    )
    with caplog.at_level(logging.WARNING):
        assert auth_manager.get_trusted_proxy_count() == 1
    joined = " ".join(caplog.messages)
    assert "non reconnu" in joined


def test_english_security_proxy_zero_message():
    en = get_ui_translations(ui_lang="en")
    msg = en["log_security_proxy_count_zero"]
    assert "ignored" in msg.lower() or "TCP" in msg
    assert "en-têtes" not in msg
    assert "verrouillage" not in msg
