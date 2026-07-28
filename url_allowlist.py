"""
Validation d'URL pour le proxy d'images et le téléchargement de couvertures.

Soft-fail uniquement : ne lève jamais d'exception vers l'appelant.
Les domaines autorisés viennent de ScraperRegistry.get_all_proxy_domains().
"""

from __future__ import annotations

import ipaddress
from typing import Callable, Optional, Tuple
from urllib.parse import urljoin, urlparse

_BLOCKED_HOSTS = frozenset({
    "localhost",
    "127.0.0.1",
    "::1",
    "0.0.0.0",
    "metadata.google.internal",
})

_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".intranet")


def _is_blocked_host(domain: str) -> Tuple[bool, str]:
    """Refuse localhost, link-local, metadata et plages IP privées / réservées."""
    if domain in _BLOCKED_HOSTS or any(domain.endswith(s) for s in _BLOCKED_SUFFIXES):
        return True, "Hôte local / interne refusé"
    if domain.startswith("169.254."):
        return True, "Hôte link-local / metadata refusé"

    # IP littérale dans l'URL (pas de résolution DNS — évite un second SSRF)
    try:
        ip = ipaddress.ip_address(domain.strip("[]"))
    except ValueError:
        return False, ""

    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return True, "Adresse IP privée / réservée refusée"
    return False, ""


def validate_proxied_image_url(url, allowed_domains):
    """Vérifie schéma, hôte et allowlist.

    Returns:
        (ok: bool, reason: str, domain: str | None)
    """
    if not url or not isinstance(url, str):
        return False, "URL manquante", None

    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False, "URL invalide", None

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return False, f"Schéma non autorisé: {scheme or '(vide)'}", None

    if parsed.username is not None or parsed.password is not None:
        return False, "URL avec credentials refusée", None

    domain = (parsed.netloc or "").lower().split(":")[0]
    if not domain:
        return False, "Hôte manquant", None

    blocked, block_reason = _is_blocked_host(domain)
    if blocked:
        return False, block_reason, domain

    allowed = allowed_domains or []
    is_safe = any(domain == d or domain.endswith("." + d) for d in allowed)
    if not is_safe:
        return False, f"Domaine non autorisé: {domain}", domain

    return True, "ok", domain


def fetch_with_safe_redirects(
    get_fn: Callable[..., object],
    url: str,
    allowed_domains,
    *,
    max_hops: int = 3,
    **get_kwargs,
) -> Tuple[Optional[object], str, str]:
    """GET avec suivi manuel des redirects, chaque hop re-validé contre l'allowlist.

    `get_fn` doit accepter `allow_redirects=False` (requests / curl_cffi).
    Returns:
        (response_or_None, reason, final_url)
    """
    current = (url or "").strip()
    if not current:
        return None, "URL manquante", current

    for _ in range(max(0, int(max_hops)) + 1):
        ok, reason, _domain = validate_proxied_image_url(current, allowed_domains)
        if not ok:
            return None, reason, current

        kwargs = dict(get_kwargs)
        kwargs["allow_redirects"] = False
        try:
            res = get_fn(current, **kwargs)
        except TypeError:
            # Client sans allow_redirects : ne pas suivre aveuglément
            return None, "Client HTTP sans contrôle de redirect", current

        status = getattr(res, "status_code", None)
        if status in (301, 302, 303, 307, 308):
            headers = getattr(res, "headers", {}) or {}
            loc = headers.get("Location") or headers.get("location")
            # The intermediate hop is finished with either way, so release it before
            # moving on. This matters once a caller passes `stream=True` (the image
            # proxy does, to enforce its size cap): a streaming response holds its
            # connection open until the body is read or the response is closed, so
            # abandoning one per redirect would leak a connection — and under the
            # single-worker eventlet deployment, a greenthread with it.
            closer = getattr(res, "close", None)
            if callable(closer):
                closer()
            if not loc:
                return None, "Redirect sans Location", current
            current = urljoin(current, loc)
            continue

        return res, "ok", current

    return None, "Trop de redirects", current
