"""
Blueprint divers : proxy d'images (contournement hotlink/CORS) et API du
changelog affiché dans l'interface.

⚠️ Endpoints réels : 'misc.proxy_image', 'misc.get_changelog_api'.
"""

import io
import logging
from urllib.parse import urlparse

import requests
from flask import Blueprint, request, jsonify, send_file

from scrapers import ScraperRegistry
from services.changelog_service import get_current_version, get_full_changelog_html

misc_bp = Blueprint('misc', __name__)


@misc_bp.route('/api/proxy-image')
def proxy_image():
    img_url = request.args.get('url')
    if not img_url: return "Missing URL", 400

    try:
        parsed = urlparse(img_url)
        domain = parsed.netloc.lower().split(':')[0]

        # Récupération dynamique en direct auprès du registre
        allowed_domains = ScraperRegistry.get_all_proxy_domains()
        is_safe = any(domain == d or domain.endswith('.' + d) for d in allowed_domains)

        if not is_safe:
            print(f"[Proxy] Domaine non autorisé : {domain}")
            return "Domain not allowed", 403
    except Exception as e:
        print(f"[Proxy] URL invalide : {e}")
        return "Invalid URL", 400

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        # Récupération dynamique du Referer auprès du scraper propriétaire du domaine
        for scraper in ScraperRegistry.get_all():
            if any(domain == d or domain.endswith('.' + d) for d in scraper.proxy_domains):
                if getattr(scraper, 'proxy_referer', None):
                    headers["Referer"] = scraper.proxy_referer
                break

        res = requests.get(img_url, headers=headers, timeout=12)

        if res.status_code == 200:
            content_type = res.headers.get('Content-Type', 'image/jpeg')
            return send_file(io.BytesIO(res.content), mimetype=content_type)
        else:
            print(f"[Proxy] Échec HTTP {res.status_code} pour : {img_url}")

    except Exception as e:
        print(f"[Proxy] Erreur interne : {e}")

    return "Error", 500


@misc_bp.route('/api/changelog', methods=['GET'])
def get_changelog_api():
    """Endpoint renvoyant l'intégralité du changelog et le numéro de version courante."""
    return jsonify({
        "success": True,
        "version": get_current_version(),
        "changelog": get_full_changelog_html()
    })
