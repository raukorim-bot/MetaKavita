"""
Journalisation sans fuite de secrets (clés API dans query strings d'exceptions).

Les timeouts / erreurs urllib3 incluent souvent l'URL complète de la requête,
y compris `?apiKey=` / `?api_key=`. Ces messages partent vers les fichiers de
log ET la console Live Logs (WebSocket) — il ne faut jamais logger `str(e)` brut
après un appel authentifié par query param.
"""

from __future__ import annotations

import re
from typing import Any


# apiKey / api_key / access_token / token / Authorization=... dans une URL ou un message
_SENSITIVE_QS = re.compile(
    r"([?&](?:api[_-]?key|apikey|access[_-]?token|token|authorization|auth)=)([^&\s'\"\\]+)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(Bearer\s+)(\S+)", re.IGNORECASE)


def redact_secrets(text: str) -> str:
    """Masque les secrets évidents dans une chaîne (URL, message d'exception, etc.)."""
    if not text:
        return ""
    out = _SENSITIVE_QS.sub(r"\1***", str(text))
    out = _BEARER.sub(r"\1***", out)
    return out


def safe_exc_str(exc: Any) -> str:
    """Représentation loggable d'une exception : type + message redacté."""
    name = type(exc).__name__ if exc is not None else "Exception"
    try:
        msg = redact_secrets(str(exc))
    except Exception:
        msg = "<unprintable>"
    return f"{name}: {msg}" if msg else name
