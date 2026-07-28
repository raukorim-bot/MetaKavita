"""
Blueprint divers : proxy d'images (contournement hotlink/CORS) et API du
changelog affiché dans l'interface.

⚠️ Endpoints réels : 'misc.proxy_image', 'misc.get_changelog_api'.
"""

import io
import logging

import requests
from flask import Blueprint, request, jsonify, send_file

from scrapers import ScraperRegistry
from services.changelog_service import get_current_version, get_full_changelog_html
from url_allowlist import validate_proxied_image_url, fetch_with_safe_redirects
from secure_logging import safe_exc_str

misc_bp = Blueprint('misc', __name__)

_SAFE_IMAGE_MIMES = frozenset({
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/avif",
})

# Hard ceiling on what the image proxy will hold in memory for a single request.
#
# Why this exists: the proxy is reachable by any logged-in user with any URL whose
# host is in the scraper allowlist, and the response used to be read with
# `res.content`, which buffers the ENTIRE body before anything else runs. A single
# allowlisted host serving a multi-gigabyte file — compromised, misconfigured, or
# just hosting something that is not a cover — was therefore enough to exhaust the
# container's memory. That is especially damaging here because Gunicorn runs with
# `-w 1` and the eventlet worker: there is one process for the whole application,
# so one oversized fetch takes down every user's session, the batch queue and the
# background sync workers with it.
#
# 5 MB is the value agreed on issue #15: HD covers realistically top out at 2-3 MB,
# so this leaves headroom for a legitimately large cover while making the failure
# mode a cheap 413 instead of an OOM kill.
_MAX_PROXY_IMAGE_BYTES = 5 * 1024 * 1024

# Read granularity for the streamed download. Small enough that the overshoot past
# the cap is bounded by one chunk, large enough not to add meaningful syscall
# overhead on a normal 2 MB cover.
_PROXY_IMAGE_CHUNK_BYTES = 64 * 1024


@misc_bp.route('/api/proxy-image')
def proxy_image():
    img_url = request.args.get('url')
    if not img_url:
        return "Missing URL", 400

    try:
        allowed_domains = ScraperRegistry.get_all_proxy_domains()
        ok, reason, domain = validate_proxied_image_url(img_url, allowed_domains)
        if not ok:
            logging.warning("[Proxy] Refus (%s) : %s", reason, img_url)
            return "Domain not allowed", 403
    except Exception as e:
        logging.warning("[Proxy] URL invalide : %s", e)
        return "Invalid URL", 400

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        for scraper in ScraperRegistry.get_all():
            if any(domain == d or domain.endswith('.' + d) for d in scraper.proxy_domains):
                if getattr(scraper, 'proxy_referer', None):
                    headers["Referer"] = scraper.proxy_referer
                break

        # Redirects suivis uniquement si chaque hop reste dans l'allowlist (anti-SSRF CDN).
        # `stream=True` keeps the body unread until we ask for it, which is what makes
        # the size cap below possible: without it `requests` has already buffered the
        # whole response by the time this call returns, and refusing it afterwards
        # would be pointless.
        res, fetch_reason, final_url = fetch_with_safe_redirects(
            requests.get,
            img_url,
            allowed_domains,
            max_hops=3,
            headers=headers,
            timeout=12,
            stream=True,
        )
        if res is None:
            logging.warning("[Proxy] Fetch refusé (%s) : %s", fetch_reason, img_url)
            return "Redirect not allowed", 403

        # Streaming responses hold a live connection until the body is consumed or the
        # response is closed. Every exit path below therefore has to close it, so the
        # whole block is wrapped rather than relying on garbage collection — under the
        # single eventlet worker a leaked connection is a leaked greenthread.
        try:
            if res.status_code == 200:
                raw_type = (res.headers.get('Content-Type') or 'image/jpeg').split(';')[0].strip().lower()
                if raw_type not in _SAFE_IMAGE_MIMES and not raw_type.startswith('image/'):
                    logging.warning("[Proxy] Content-Type non image refusé (%s) pour %s", raw_type, final_url)
                    return "Unsupported media type", 415
                mimetype = raw_type if raw_type.startswith('image/') else 'image/jpeg'

                # Content-Length is only a hint: a hostile or simply misconfigured host
                # can omit it, lie about it, or use chunked encoding where it does not
                # exist at all. It is checked first purely to fail fast and avoid pulling
                # megabytes we are going to throw away — the running total below is the
                # check that actually enforces the limit.
                declared_length = res.headers.get('Content-Length')
                if declared_length is not None:
                    try:
                        if int(declared_length) > _MAX_PROXY_IMAGE_BYTES:
                            logging.warning(
                                "[Proxy] Image refusée : Content-Length %s > %s octets pour %s",
                                declared_length, _MAX_PROXY_IMAGE_BYTES, final_url,
                            )
                            return "Image too large", 413
                    except (TypeError, ValueError):
                        # Unparseable header — ignore it and let the streaming check decide.
                        pass

                buffer = io.BytesIO()
                downloaded = 0
                for chunk in res.iter_content(chunk_size=_PROXY_IMAGE_CHUNK_BYTES):
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    if downloaded > _MAX_PROXY_IMAGE_BYTES:
                        # Abandon mid-download. Overshoot is bounded by one chunk, so the
                        # worst case held in memory is the cap plus 64 KB rather than
                        # whatever the remote host felt like sending.
                        logging.warning(
                            "[Proxy] Image refusée : dépassement de %s octets en cours de "
                            "téléchargement pour %s",
                            _MAX_PROXY_IMAGE_BYTES, final_url,
                        )
                        return "Image too large", 413
                    buffer.write(chunk)

                buffer.seek(0)
                return send_file(buffer, mimetype=mimetype)

            logging.warning("[Proxy] Échec HTTP %s pour : %s", res.status_code, final_url)
        finally:
            res.close()

    except Exception as e:
        logging.warning("[Proxy] Erreur interne : %s", safe_exc_str(e))

    return "Error", 500


@misc_bp.route('/api/changelog', methods=['GET'])
def get_changelog_api():
    """Endpoint renvoyant l'intégralité du changelog et le numéro de version courante."""
    return jsonify({
        "success": True,
        "version": get_current_version(),
        "changelog": get_full_changelog_html()
    })
