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


def series_label(name: Any, series_id: Any = None) -> str:
    """Comment une série se nomme dans le journal : « Blacksad » (6429).

    Le titre est ce que l'utilisateur cherche des yeux. L'identifiant Kavita
    permet de recouper avec l'API et le dashboard. Les deux figurent donc dès
    qu'ils sont connus. Sans titre, l'identifiant est annoncé comme tel
    (`« série 6429 »`), faute de quoi « 6429 » se lirait comme un titre.

    Ici et non dans un module de tomes : l'Inventaire, la passe par tome et
    l'enrichissement série écrivent dans le même journal, et l'utilisateur n'a
    aucune raison d'y trouver trois façons de nommer la même série.
    """
    text = str(name or "").strip()
    sid = str(series_id).strip() if series_id is not None else ""
    if text and sid:
        return f"« {text} » ({sid})"
    if text:
        return f"« {text} »"
    if sid:
        return f"« série {sid} »"
    return "« série inconnue »"


def safe_exc_str(exc: Any) -> str:
    """Représentation loggable d'une exception : type + message redacté."""
    name = type(exc).__name__ if exc is not None else "Exception"
    try:
        msg = redact_secrets(str(exc))
    except Exception:
        msg = "<unprintable>"
    return f"{name}: {msg}" if msg else name
