"""C90 — le journal live se lit, il n'est plus une console Courier."""
from __future__ import annotations

import re
from pathlib import Path

from secure_logging import series_label

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "static" / "js" / "websocket.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")
SIDEBAR = (ROOT / "templates" / "partials" / "_sidebar.html").read_text(encoding="utf-8")

# Même expression que LOG_SERIES_RE dans websocket.js.
SERIES_RE = re.compile(r"^(?:\[)?(«\s*[^»]+?\s*»(?:\s*\(\d+\))?)(?:\])?\s*")
TIME_RE = re.compile(r"^(\d{2}:\d{2}:\d{2})\s*\|\s*")


def test_sidebar_has_readable_log_chrome():
    assert 'id="log-console"' in SIDEBAR
    assert 'id="logFollowBtn"' in SIDEBAR
    assert 'id="logClearBtn"' in SIDEBAR
    assert "logs-head" in SIDEBAR
    assert 'class="logs-container card card-tint-sky"' in SIDEBAR
    assert "Courier" not in SIDEBAR


def test_js_builds_dom_without_innerhtml():
    assert "function parseLiveLog" in JS
    assert "function appendLiveLog" in JS
    assert "function clearLiveLog" in JS
    assert "innerHTML" not in JS
    assert "textContent" in JS
    assert "is-processing" not in JS
    assert "LOG_MAX_LINES" in JS


def test_css_drops_the_green_terminal():
    assert ".log-series" in CSS
    assert ".log-time" in CSS
    assert ".logs-paused" in CSS
    chunk = CSS[CSS.index(".log-console {") : CSS.index(".log-console {") + 900]
    assert "var(--font-family)" in chunk
    assert "Courier" not in chunk
    assert "#a6e3a1" not in CSS


def test_c84_label_is_what_the_journal_parser_splits():
    label = series_label("One Piece", 5605)
    stamped = f"14:32:01 | [{label}] Smart Scoring activé"
    rest = TIME_RE.sub("", stamped, count=1)
    match = SERIES_RE.match(rest)
    assert match, rest
    assert "One Piece" in match.group(1)
    assert "5605" in match.group(1)
    assert rest[match.end():].startswith("Smart Scoring")

    fallback = series_label("", 6429)
    match2 = SERIES_RE.match(f"{fallback} phase")
    assert match2
    assert match2.group(1).startswith("«")


def test_live_log_i18n_keys_exist_in_both_languages():
    from translations import translations

    keys = (
        "live_logs",
        "live_logs_pause",
        "live_logs_resume",
        "live_logs_pause_hint",
        "live_logs_clear",
        "live_logs_paused",
        "terminal_ready",
        "waiting",
    )
    for lang in ("fr", "en"):
        for key in keys:
            assert translations[lang][key].strip()
    assert "Terminal" not in translations["fr"]["terminal_ready"]
    assert "Terminal" not in translations["en"]["terminal_ready"]
    assert translations["fr"]["live_logs"] != translations["en"]["live_logs"]
