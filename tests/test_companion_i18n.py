"""C33 — Companion config blurb i18n FR/EN + template marker."""
from __future__ import annotations

from pathlib import Path

from translations import translations

KEYS = (
    "companion_config_title",
    "companion_config_blurb",
    "companion_config_howto",
    "companion_copy_base_url",
    "companion_copy_token",
    "companion_wait_title",
    "companion_wait_text",
    "companion_wait_timeout",
    "companion_embed_missing_series",
    "companion_embed_invalid_series",
    "msg_webhook_missing_fields",
    "msg_webhook_kavita_unreachable",
    "msg_webhook_series_not_found",
)


def test_companion_i18n_keys_fr_en_nonempty():
    for lang in ("fr", "en"):
        t = translations[lang]
        for key in KEYS:
            assert key in t, f"missing {key} in {lang}"
            assert str(t[key]).strip(), f"empty {key} in {lang}"


def test_config_modal_has_companion_marker():
    html = (Path(__file__).resolve().parents[1] / "templates" / "partials" / "_config_modal.html").read_text(
        encoding="utf-8"
    )
    assert 'data-companion-config="1"' in html
    assert "companion_config_title" in html
