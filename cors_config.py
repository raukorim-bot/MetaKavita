"""
Whitelist CORS lue depuis la variable d'environnement Docker `CORS_ALLOWED_ORIGINS`.

Env-only (comme `ROOT_PATH`) : pas d'édition UI. Liste d'origins explicites
séparées par des virgules, appliquée à Flask HTTP et Socket.IO.

Exemple :
  CORS_ALLOWED_ORIGINS=https://metakavita.home.local.ltd,https://kavita.home.local.ltd

Liste vide / absente = pas d'ouverture CORS (comportement Same-Origin actuel).
`*` est explicitement rejeté (incompatible avec Allow-Credentials).
"""
from __future__ import annotations

import logging
import os
from typing import List, Optional, Tuple


def parse_cors_allowed_origins(raw: Optional[str] = None) -> List[str]:
    """
    Parse une chaîne CSV d'origins en liste normalisée.

    - strip espaces
    - ignore les entrées vides
    - retire un trailing `/`
    - ignore `*` (signalé au boot via log_cors_config)
    """
    origins, _ = parse_cors_allowed_origins_detailed(raw)
    return origins


def parse_cors_allowed_origins_detailed(raw: Optional[str] = None) -> Tuple[List[str], bool]:
    """Comme parse_cors_allowed_origins, plus un flag `star_ignored` si `*` était présent."""
    if raw is None:
        raw = os.environ.get("CORS_ALLOWED_ORIGINS", "")

    origins: List[str] = []
    star_ignored = False
    for part in str(raw).split(","):
        origin = part.strip().rstrip("/")
        if not origin:
            continue
        if origin == "*":
            star_ignored = True
            continue
        if origin not in origins:
            origins.append(origin)
    return origins, star_ignored


def log_cors_config(origins: List[str], star_ignored: bool = False) -> None:
    if star_ignored:
        logging.warning(
            "⚠️ [CORS] L'origine '*' est ignorée : incompatible avec "
            "Access-Control-Allow-Credentials. Utilisez des origins explicites "
            "(ex: https://metakavita.home.local.ltd)."
        )
    if origins:
        logging.info(f"🌐 [CORS] Whitelist active : {origins}")
    else:
        logging.info(
            "🌐 [CORS] Same-Origin (CORS_ALLOWED_ORIGINS vide ou absent — "
            "aucune origine cross-origin autorisée)."
        )


def is_origin_allowed(origin: Optional[str], allowed: List[str]) -> bool:
    if not origin or not allowed:
        return False
    normalized = origin.strip().rstrip("/")
    return normalized in allowed
