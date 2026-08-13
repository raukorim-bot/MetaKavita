"""
Short-lived embed tokens for MetaKavita Companion Super Review iframe.

Bypasses SameSite=Lax session cookies that are not sent in nested
chrome-extension → MetaKavita iframes on a different site.
"""
from __future__ import annotations

import secrets
import threading
import time
from typing import Any, Dict, Optional

_LOCK = threading.Lock()
# token -> {series_id, parent_origin, exp}
_TOKENS: Dict[str, Dict[str, Any]] = {}

# Durée de vie d'un jeton fraîchement émis.
#
# ⚠️ Plancher imposé par l'extension : `companion/background.js` réutilise un
# jeton déjà émis pendant 10 minutes (`EMBED_TOKEN_REUSE_MS`, un jeton par
# `base|seriesId` pour ne pas en semer une vingtaine à l'ouverture du cover
# picker). Descendre cette valeur sous ~11 minutes remettrait donc à l'embed un
# jeton qui meurt pendant la revue, sur les extensions déjà installées.
# L'exposition réelle est bornée ailleurs : `auth_manager` révoque le jeton dès
# que la revue est conclue, donc il ne survit plus à la fermeture du shell.
DEFAULT_TTL_SEC = 15 * 60


def _purge_expired(now: Optional[float] = None) -> None:
    ts = now if now is not None else time.time()
    dead = [k for k, v in _TOKENS.items() if float(v.get("exp") or 0) <= ts]
    for k in dead:
        _TOKENS.pop(k, None)


def issue_embed_token(
    series_id: int,
    parent_origin: str = "",
    ttl_sec: int = DEFAULT_TTL_SEC,
) -> str:
    """Create a one-shot-capable token bound to series_id (reusable until expiry)."""
    token = secrets.token_urlsafe(32)
    with _LOCK:
        _purge_expired()
        _TOKENS[token] = {
            "series_id": int(series_id),
            "parent_origin": str(parent_origin or "").strip(),
            "exp": time.time() + max(60, int(ttl_sec)),
        }
    return token


def peek_embed_token(token: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return token payload if valid; does not consume."""
    if not token:
        return None
    with _LOCK:
        _purge_expired()
        data = _TOKENS.get(str(token))
        if not data:
            return None
        return dict(data)


def validate_embed_token(token: Optional[str], series_id: int) -> Optional[Dict[str, Any]]:
    """Validate token for series_id. Keeps token until expiry (iframe reloads)."""
    data = peek_embed_token(token)
    if not data:
        return None
    try:
        if int(data["series_id"]) != int(series_id):
            return None
    except (TypeError, ValueError):
        return None
    return data


def request_embed_token() -> str:
    """Read embed token from header / query (Companion API + Socket.IO)."""
    from flask import request

    header = (request.headers.get("X-Companion-Embed-Token") or "").strip()
    if header:
        return header
    return (
        request.args.get("embed_token")
        or request.args.get("embedToken")
        or ""
    ).strip()


def authorize_companion_request(series_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    Validate Companion embed token for the current Flask/Socket request.

    If series_id is provided, the token must be bound to that series.
    If omitted, any still-valid token is accepted (caller must re-check scope).
    """
    token = request_embed_token()
    if not token:
        return None
    data = peek_embed_token(token)
    if not data:
        return None
    if series_id is not None:
        try:
            if int(data["series_id"]) != int(series_id):
                return None
        except (TypeError, ValueError):
            return None
    return data


def revoke_embed_token(token: Optional[str]) -> None:
    """Détruit un jeton avant son expiration (revue conclue, usage unique).

    Appelée par `auth_manager._revoke_embed_token_after_completion` : sans elle,
    un « Confirmer » / « Passer » laissait le jeton utilisable jusqu'au bout de
    son TTL, alors qu'il contourne la session et, dans son périmètre, le CSRF.
    """
    if not token:
        return
    with _LOCK:
        _TOKENS.pop(str(token), None)


def clear_all_embed_tokens() -> None:
    """Test helper."""
    with _LOCK:
        _TOKENS.clear()
