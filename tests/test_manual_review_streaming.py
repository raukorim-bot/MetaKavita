"""Progressive Super Review / MR candidate streaming."""
from __future__ import annotations

import json

import pytest

from services.manual_review import (
    append_streaming_candidate,
    begin_streaming_review,
    finalize_streaming_review,
)
from services.companion_embed_auth import clear_all_embed_tokens, issue_embed_token
from csrf_utils import CSRF_EXEMPT_ENDPOINTS


def test_embed_token_endpoint_is_csrf_exempt():
    assert "companion.companion_embed_token" in CSRF_EXEMPT_ENDPOINTS


def test_begin_append_finalize_streaming(isolated_db, monkeypatch):
    emitted = []

    def fake_emit(event, payload):
        emitted.append((event, payload))

    monkeypatch.setattr("services.manual_review._safe_emit", fake_emit)

    rid = begin_streaming_review(42, "One Piece", query="One Piece", library_id=1)
    assert rid
    assert any(e[0] == "manual_review_queued" and e[1].get("streaming") for e in emitted)

    append_streaming_candidate(
        rid,
        42,
        {"provider": "AniList", "score": 0.9, "title": "One Piece", "cover_url": "", "summary": ""},
        "above",
    )
    assert any(e[0] == "manual_review_candidate" for e in emitted)

    finalize_streaming_review(
        rid,
        42,
        "One Piece",
        {
            "above": [
                {
                    "provider": "AniList",
                    "score": 0.9,
                    "title": "One Piece",
                    "cover_url": "",
                    "summary": "ok",
                    "data": {"summary": "ok"},
                }
            ],
            "below": [],
            "query": "One Piece",
            "streaming": True,
        },
        library_id=1,
    )
    assert any(e[0] == "manual_review_scrape_complete" for e in emitted)

    from db_manager import get_pending_review

    row = get_pending_review(rid)
    assert row
    payload = json.loads(row["candidates_json"])
    assert payload.get("streaming") in (None, False)
    assert len(payload.get("above") or []) == 1


def test_authorize_companion_request_scoped(monkeypatch):
    clear_all_embed_tokens()
    tok = issue_embed_token(7, parent_origin="chrome-extension://abc")

    class FakeReq:
        headers = {"X-Companion-Embed-Token": tok}
        args = {}

    monkeypatch.setattr("services.companion_embed_auth.request", FakeReq(), raising=False)
    # authorize_companion_request imports flask.request inside request_embed_token
    import services.companion_embed_auth as mod

    monkeypatch.setattr(mod, "request_embed_token", lambda: tok)
    assert mod.authorize_companion_request(7) is not None
    assert mod.authorize_companion_request(99) is None
    clear_all_embed_tokens()
