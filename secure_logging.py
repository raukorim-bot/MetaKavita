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
    """Comment une série se nomme dans le journal : « Blacksad ».

    Les passes affichaient l'identifiant Kavita. C'est lisible pour la base de
    données et illisible pour qui suit une passe de trente séries et cherche
    laquelle prend une minute : personne ne connaît par cœur le numéro de ses
    séries. L'identifiant ne sert plus que de repli, quand Kavita n'a pas rendu
    de titre — et il est alors annoncé comme tel, faute de quoi « 6429 » se
    lirait comme un titre.

    Ici et non dans un module de tomes : l'Inventaire, la passe par tome et
    l'enrichissement série écrivent dans le même journal, et l'utilisateur n'a
    aucune raison d'y trouver trois façons de nommer la même série.
    """
    text = str(name or "").strip()
    if text:
        return f"« {text} »"
    if series_id is not None:
        return f"« série {series_id} »"
    return "« série inconnue »"


def safe_exc_str(exc: Any) -> str:
    """Représentation loggable d'une exception : type + message redacté."""
    name = type(exc).__name__ if exc is not None else "Exception"
    try:
        msg = redact_secrets(str(exc))
    except Exception:
        msg = "<unprintable>"
    return f"{name}: {msg}" if msg else name
