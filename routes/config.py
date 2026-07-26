"""
Blueprint de configuration globale : /save-config, /regenerate-webhook-token.

⚠️ Endpoints réels : 'config.save_config_ajax' et 'config.regenerate_webhook_token'.
"""

import logging
import secrets

from flask import Blueprint, request, jsonify

from config_manager import load_config, save_config, CONFIG_LOCK
from scrapers import ScraperRegistry

config_bp = Blueprint('config', __name__)


@config_bp.route('/save-config', methods=['POST'])
def save_config_ajax():
    # CONFIG_LOCK englobe TOUT le cycle lire-modifier-écrire (pas seulement l'appel
    # à save_config()) : sinon, deux requêtes /save-config concurrentes (ex: deux
    # cases à cocher changées coup sur coup, voir config.js::saveConfig()) peuvent
    # quand même s'entrelacer ENTRE le load_config() et le save_config() de chacune,
    # et l'une écraserait silencieusement les changements de l'autre.
    with CONFIG_LOCK:
        config = load_config()

        config['TRANSLATION_PROVIDER'] = request.form.get('TRANSLATION_PROVIDER', 'GOOGLE').strip()
        config['KAVITA_URL'] = request.form.get('KAVITA_URL', '').strip().rstrip('/')
        config['KAVITA_EXTERNAL_URL'] = request.form.get('KAVITA_EXTERNAL_URL', '').strip().rstrip('/')

        kavita_key = request.form.get('KAVITA_API_KEY', '').strip()
        if kavita_key and kavita_key != '********':
            config['KAVITA_API_KEY'] = kavita_key

        deepl_key = request.form.get('DEEPL_API_KEY', '').strip()
        if deepl_key and deepl_key != '********':
            config['DEEPL_API_KEY'] = deepl_key

        azure_key = request.form.get('AZURE_API_KEY', '').strip()
        if azure_key and azure_key != '********':
            config['AZURE_API_KEY'] = azure_key
        elif not azure_key:
            config['AZURE_API_KEY'] = ''

        for s in ScraperRegistry.get_all():
            if getattr(s, 'needs_api_key', False):
                key_name = f"{s.id}_API_KEY"
                val = request.form.get(key_name, '').strip()
                if val and val != '********':
                    config[key_name] = val
                elif not val:
                    config[key_name] = ''

        config['AZURE_REGION'] = request.form.get('AZURE_REGION', '').strip()

        config['TARGET_LANG'] = request.form.get('TARGET_LANG', 'FR').strip()
        config['UI_LANG'] = request.form.get('UI_LANG', 'fr').strip()

        config['PUBLISHER_PREFERENCE'] = request.form.get('PUBLISHER_PREFERENCE', 'LOCALIZED').strip()

        config['PROVIDER_1'] = request.form.get('PROVIDER_1', 'MANGABAKA').strip()
        config['PROVIDER_2'] = request.form.get('PROVIDER_2', 'KITSU').strip()
        config['PROVIDER_3'] = request.form.get('PROVIDER_3', 'ANILIST').strip()

        config['COMIC_PROVIDER_1'] = request.form.get('COMIC_PROVIDER_1', 'COMICVINE').strip()
        config['COMIC_PROVIDER_2'] = request.form.get('COMIC_PROVIDER_2', 'ANILIST').strip()
        config['COMIC_PROVIDER_3'] = request.form.get('COMIC_PROVIDER_3', 'NONE').strip()

        config['BOOK_PROVIDER_1'] = request.form.get('BOOK_PROVIDER_1', 'GOOGLEBOOKS').strip()
        config['BOOK_PROVIDER_2'] = request.form.get('BOOK_PROVIDER_2', 'OPENLIBRARY').strip()
        config['BOOK_PROVIDER_3'] = request.form.get('BOOK_PROVIDER_3', 'NONE').strip()

        config['SMART_COMPLETION'] = request.form.get('SMART_COMPLETION') == 'true'
        config['SMART_SCORING'] = request.form.get('SMART_SCORING') == 'true'
        config['RESET_CONTEXT_ON_FORCE'] = request.form.get('RESET_CONTEXT_ON_FORCE') == 'true'

        config['TITLE_FALLBACK_TRANSLATION'] = request.form.get('TITLE_FALLBACK_TRANSLATION') == 'true'

        try:
            config['AUTO_SYNC_INTERVAL'] = int(request.form.get('AUTO_SYNC_INTERVAL', 0))
        except ValueError:
            config['AUTO_SYNC_INTERVAL'] = 0

        config['AUTO_COVER'] = request.form.get('AUTO_COVER') == 'true'
        config['AUTO_READING_DIR'] = request.form.get('AUTO_READING_DIR') == 'true'

        save_config(config)
    return jsonify(success=True)


@config_bp.route('/regenerate-webhook-token', methods=['POST'])
def regenerate_webhook_token():
    with CONFIG_LOCK:
        config = load_config()
        new_token = secrets.token_urlsafe(16)
        config['WEBHOOK_TOKEN'] = new_token
        save_config(config)
    logging.info("🔑 [Sécurité] Nouveau jeton Webhook généré depuis l'interface web.")
    return jsonify(success=True, new_token=new_token)
