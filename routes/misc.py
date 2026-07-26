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
        res, fetch_reason, final_url = fetch_with_safe_redirects(
            requests.get,
            img_url,
            allowed_domains,
            max_hops=3,
            headers=headers,
            timeout=12,
        )
        if res is None:
            logging.warning("[Proxy] Fetch refusé (%s) : %s", fetch_reason, img_url)
            return "Redirect not allowed", 403

        if res.status_code == 200:
            raw_type = (res.headers.get('Content-Type') or 'image/jpeg').split(';')[0].strip().lower()
            if raw_type not in _SAFE_IMAGE_MIMES and not raw_type.startswith('image/'):
                logging.warning("[Proxy] Content-Type non image refusé (%s) pour %s", raw_type, final_url)
                return "Unsupported media type", 415
            mimetype = raw_type if raw_type.startswith('image/') else 'image/jpeg'
            return send_file(io.BytesIO(res.content), mimetype=mimetype)

        logging.warning("[Proxy] Échec HTTP %s pour : %s", res.status_code, final_url)

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
