"""
Protection CSRF double-submit (token session + header/form).

Exemptés : webhook (auth par jeton dédié), static, OPTIONS.
Désactivé automatiquement si app.config['TESTING'] (suite pytest).
"""

import secrets

from flask import session, request, jsonify, current_app


CSRF_SESSION_KEY = "_csrf_token"
CSRF_HEADER = "X-CSRF-Token"
CSRF_FORM_FIELD = "csrf_token"

# Endpoints exemptés (auth webhook = token query ; login GET n'est pas POST)
CSRF_EXEMPT_ENDPOINTS = frozenset({
    "sync.webhook",
    "static",
})


def ensure_csrf_token() -> str:
    """Garantit un token CSRF en session et le retourne."""
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_hex(32)
        session[CSRF_SESSION_KEY] = token
    return token


def validate_csrf() -> bool:
    """True si le token soumis correspond à la session (compare_digest)."""
    expected = session.get(CSRF_SESSION_KEY)
    if not expected:
        return False
    submitted = (
        request.headers.get(CSRF_HEADER)
        or request.form.get(CSRF_FORM_FIELD)
        or (request.get_json(silent=True) or {}).get(CSRF_FORM_FIELD)
    )
    if not submitted or not isinstance(submitted, str):
        return False
    try:
        return secrets.compare_digest(expected, submitted)
    except (TypeError, ValueError):
        return False


def csrf_protect_before_request():
    """À brancher en @app.before_request. Retourne une réponse 403 ou None."""
    if current_app.config.get("TESTING"):
        return None
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None
    endpoint = request.endpoint or ""
    if endpoint in CSRF_EXEMPT_ENDPOINTS:
        return None
    if endpoint.startswith("static"):
        return None
    if validate_csrf():
        return None
    # HTML form login → message simple ; API/AJAX → JSON
    wants_json = (
        request.accept_mimetypes.best == "application/json"
        or request.is_json
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.path.startswith("/api/")
        or "application/json" in (request.headers.get("Accept") or "")
    )
    if wants_json or request.headers.get(CSRF_HEADER) is not None or request.is_json:
        return jsonify({
            "success": False,
            "msg": "Jeton CSRF manquant ou invalide. Rechargez la page.",
        }), 403
    return ("CSRF token missing or invalid. Please reload the page.", 403)
