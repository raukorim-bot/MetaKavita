"""
CSP frame-ancestors for MetaKavita Companion embed (/companion/embed).

Always allows chrome-extension: and moz-extension: parents (extension overlay).
Optional extra HTTP(S) origins via COMPANION_FRAME_ANCESTORS (CSV env or config).
`*` is rejected.
"""
from __future__ import annotations

import os
from typing import Iterable, List, Optional
from urllib.parse import urlparse


EXTENSION_FRAME_ANCESTORS = ("chrome-extension:", "moz-extension:")


def parse_companion_frame_ancestors(raw: Optional[str] = None) -> List[str]:
    """Parse CSV of extra origins; ignore empties and `*`."""
    if raw is None:
        raw = os.environ.get("COMPANION_FRAME_ANCESTORS", "")
    origins: List[str] = []
    for part in str(raw or "").split(","):
        origin = part.strip().rstrip("/")
        if not origin or origin == "*":
            continue
        if origin not in origins:
            origins.append(origin)
    return origins


def build_frame_ancestors_csp(
    extra_origins: Optional[Iterable[str]] = None,
) -> str:
    """
    Build a Content-Security-Policy frame-ancestors directive value
    (without the 'frame-ancestors' keyword), e.g.
    \"chrome-extension: moz-extension: https://kavita.example\".
    """
    parts: List[str] = list(EXTENSION_FRAME_ANCESTORS)
    for origin in extra_origins or []:
        o = str(origin or "").strip().rstrip("/")
        if not o or o == "*" or o in parts:
            continue
        parts.append(o)
    return " ".join(parts)


def is_allowed_parent_origin(origin: Optional[str]) -> bool:
    """Validate postMessage / query parent_origin for Companion overlay."""
    if not origin or not isinstance(origin, str):
        return False
    o = origin.strip()
    return o.startswith("chrome-extension://") or o.startswith("moz-extension://")


def is_http_origin(origin: Optional[str]) -> bool:
    """
    Validate a bare HTTP(S) origin (scheme + host[:port], no path).

    Used to whitelist the top-level Kavita page as a frame ancestor: the
    Companion Super Review iframe is nested inside the extension overlay which
    is itself nested inside the Kavita page, so CSP frame-ancestors must list
    every ancestor origin, including the Kavita page.
    """
    if not origin or not isinstance(origin, str):
        return False
    try:
        parsed = urlparse(origin.strip())
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if not parsed.netloc:
        return False
    # A bare origin has no path/query/fragment.
    return not parsed.path.strip("/") and not parsed.query and not parsed.fragment


def normalize_origin(origin: Optional[str]) -> str:
    """Trim and strip a trailing slash from an origin string."""
    return str(origin or "").strip().rstrip("/")


def apply_companion_embed_framing_headers(response, extra_origins: Optional[Iterable[str]] = None):
    """Set CSP frame-ancestors on the response; drop conflicting X-Frame-Options."""
    value = build_frame_ancestors_csp(extra_origins)
    response.headers["Content-Security-Policy"] = f"frame-ancestors {value}"
    # Avoid DENY/SAMEORIGIN blocking the extension parent.
    response.headers.pop("X-Frame-Options", None)
    return response
